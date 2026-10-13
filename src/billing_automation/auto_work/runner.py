"""The main work loop: PDF mode (tickets from pdf_text) and MedLedger mode (tickets read from the screen)."""
from __future__ import annotations

import os
import time

import pyautogui

from . import pdf_source, state
from .calibration import get_calibration
from .pdf_source import (DONE_LOG, check_week_folder, done_pdfs, list_ticket_pdfs, mark_pdf_done, pdf_doctor,
                         pdf_run, pdf_start_index, read_ticket_pdf, save_folder_for_ticket)
from .portal import handle_ticket
from .screen_checks import take_page_reference
from .screen_ocr import read_date_from_region, read_name_from_region, read_ticket_counter
from .settings import SETTINGS, T
from .state import ui_queue, wait_if_paused


def main():
    calib = get_calibration()
    check_week_folder()
    take_page_reference(calib.get("reg_page_check"))
    if SETTINGS.get("ticket_source") == "pdf":
        main_pdf(calib)
    else:
        main_medledger(calib)


def main_pdf(calib):
    """PDF mode: files from pdf_text one by one, starting from the last one in the finished log (done_pdfs.txt)."""
    folder = pdf_run["folder"]
    all_tickets = list_ticket_pdfs(folder)
    start = pdf_start_index(all_tickets)
    names = [os.path.basename(p).lower() for _n, p in all_tickets]
    manual = pdf_run.get("start_name", "").lower() in names
    if manual:
        start = names.index(pdf_run["start_name"].lower())
    tickets = all_tickets[start:]
    total = len(tickets)
    print(f"[PDF] Folder: {folder}")
    if manual:
        print(f"[PDF] Start chosen manually: {os.path.basename(all_tickets[start][1])}.")
    elif done_pdfs():
        print(f"[PDF] Last in {os.path.basename(DONE_LOG)}: {os.path.basename(all_tickets[start][1])} "
              f"- starting from it again.")
    print(f"[PDF] Tickets to process: {total}"
          + (f" (from {os.path.basename(tickets[0][1])})." if tickets else "."))

    for i, (n, path) in enumerate(tickets, 1):
        try:
            wait_if_paused()
            print("\n" + "=" * 50)
            print(f"--- Ticket {i} of {total}: {os.path.basename(path)} ---")
            dob_text, source_name, info = read_ticket_pdf(path)
            if dob_text is None and source_name is None:
                print("Blank page - skipping.")
                continue
            save_dir = save_folder_for_ticket(info, pdf_doctor(path))
            while True:
                lost = state.page_lost_count
                saved = handle_ticket(dob_text, source_name, calib, save_dir)
                if state.page_lost_count == lost:
                    break
                print(f"[PDF] The page got kicked out during {os.path.basename(path)} - repeating this ticket.")
            if saved:
                mark_pdf_done(path, saved)
                print(f"[PDF] Done: {os.path.basename(path)} (records saved: {saved}).")
            else:
                print(f"[PDF] {os.path.basename(path)}: nothing saved - not writing it to the finished log.")
        except Exception as e:
            print(f"\n[ERROR] {os.path.basename(path)}: {e}")
            time.sleep(T("error_pause"))

    print("\n" + "=" * 50)
    print(f"ALL PDF TICKETS PROCESSED ({total}, folder {os.path.basename(folder)}).")
    print("=" * 50)
    # reconcile the saved records with the tickets: are there records of "unknown people"?
    try:
        from ..pdf_tickets import reconcile, storage
        report = reconcile.reconcile(pdf_source.week_folder or None, folder)
        storage.append_log("reconcile_log.txt", f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} (AUTO-WORK)\n{report}\n")
        head, _sep, tail = report.partition("Tickets without records")
        print("\n[RECONCILIATION WITH THE WEEK FOLDER]\n" + head.rstrip())
        if tail:
            print("Tickets without records" + tail.split("\n")[0]
                  + "  (full list - 'CarePortal reconciliation' tab in 'PDF Tickets')")
    except Exception as e:
        print(f"[RECONCILE] [ERROR] {e}")
    state.is_paused = True
    ui_queue.put("pdf_done")


def main_medledger(calib):
    """MedLedger mode (as in V30): the ticket is read from the screen, the next one is opened with the ► arrow."""
    ticket_num = 0

    while True:
        try:
            wait_if_paused()
            ticket_num += 1
            print("\n" + "="*50)
            print(f"--- Ticket #{ticket_num} ---")

            dob_text, _ = read_date_from_region(calib["reg_source_dob"])
            source_name, _ = read_name_from_region(calib["reg_source_name"])
            handle_ticket(dob_text, source_name, calib)

            # Check the counter AFTER processing the ticket (before clicking the arrow)
            wait_if_paused()
            current, total = read_ticket_counter(calib["reg_ticket_counter"])
            if current is not None and total is not None:
                print(f"   Counter: {current} of {total}")
                if current >= total:
                    print("\n" + "="*50)
                    print(f"ALL TICKETS PROCESSED ({current} of {total}).")
                    print("[PAUSE] The last ticket is done. Press F9 to continue.")
                    print("="*50)
                    state.is_paused = True
                    wait_if_paused()
                    # After unpausing - do not click the arrow, just continue the loop
                    continue
            else:
                print("   [COUNTER] Not recognized - continuing without the limit check.")

            print("\nClicking the center of MedLedger to give it focus...")
            pyautogui.click(calib["pt_medledger_center"])
            time.sleep(T("after_medledger_click"))
            print("Moving to the next ticket (► arrow)...")
            pyautogui.click(calib["pt_next_arrow"])
            time.sleep(T("after_next_arrow"))

        except Exception as e:
            print(f"\n[ERROR] An error occurred in the loop: {e}")
            time.sleep(T("error_pause"))
