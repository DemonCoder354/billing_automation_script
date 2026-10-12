"""Work with the website: search by date of birth, open the found patients and save their records."""
from __future__ import annotations

import time

import keyboard
import pyautogui

from . import state
from .name_matching import find_matching_names_in_region
from .save_dialog import (PATH_CHAR_DELAY, file_not_saved, hold_key, move_from_staging, prepare_staging,
                          type_text_safe)
from .screen_checks import check_for_red_dots, check_for_target_color, ensure_page
from .settings import T, fmt_sec
from .state import wait_if_paused


def process_record(match_coords, btn_three_dots, btn_three_dots_option, btn_dark_green, dropdown_opt, region_results, region_red_dots, region_target_color,
                   pt_explorer_path=None, save_dir=None, pt_close_tab=None):
    """
    Returns True if the record was actually saved (a red dot was
    found and all save steps were completed), otherwise False.
    """
    print(f"   Clicking the record: {match_coords[2]} ({match_coords[3]}%)")
    pyautogui.click(match_coords[0], match_coords[1])
    time.sleep(T("page_load"))  # wait for the record page to load

    # Clicking a name opens a new tab - close the previous, unneeded one (X button).
    # Only here, i.e. only if a name was clicked. The website window is set up so that the previous
    # tab is always in the same place - the X is calibrated once.
    if pt_close_tab:
        print("   -> Closing the previous tab (X button)...")
        pyautogui.click(pt_close_tab[0], pt_close_tab[1])
        time.sleep(T("after_close_tab"))

    # did the patient page open normally? Otherwise - pause, the ticket will be repeated
    lost = state.page_lost_count
    ensure_page("after the patient page loaded")
    if state.page_lost_count != lost:
        print("   -> The page got kicked out - this record is not saved (the ticket will be repeated).")
        return False

    # Check the target color (sample color) in the calibrated region.
    # If the color is found, the button clicks below (before clicking the document
    # center) are shifted 25 pixels down.
    color_found = check_for_target_color(region_target_color)
    y_offset = 25 if color_found else 0
    if color_found:
        print(f"   -> Target color found. Shifting button clicks {y_offset}px down.")
    else:
        print("   -> Target color not found. Clicks without offset.")

    def click_shifted(point):
        pyautogui.click(point[0], point[1] + y_offset)

    # 1. Dark-green button
    click_shifted(btn_dark_green)
    time.sleep(T("after_dark_green"))

    # 2. Dropdown menu
    click_shifted(dropdown_opt)
    time.sleep(T("after_dropdown"))

    has_red_dots = check_for_red_dots(region_red_dots)

    if has_red_dots:
        print("   -> Red dot found. Saving...")

        # 3. "3 dots" button
        print("   -> Clicking the '3 dots' button...")
        click_shifted(btn_three_dots)
        time.sleep(T("after_three_dots"))

        # 4. Option in the "3 dots" menu
        print("   -> Selecting the option in the '3 dots' menu...")
        click_shifted(btn_three_dots_option)
        time.sleep(T("after_three_dots_option"))

        # 5. Enter - first press (browser dialog)
        print("   -> Pressing Enter (first time)...")
        pyautogui.press('enter')
        time.sleep(T("after_enter1"))

        # 5a. Save folder. The file is saved to the EMPTY staging folder SAVE_STAGING
        #     (the path is typed into the "File name" field before the file name) - there is nothing to replace,
        #     so Windows never asks "replace?". Then the program moves the file to save_dir itself.
        staging = save_dir and prepare_staging()
        if staging:
            print(f"   -> Save folder: {save_dir}")
            pyautogui.hotkey('alt', 'n')   # cursor into the "File name" field
            time.sleep(0.3)
            pyautogui.press('home')        # to the start of the name, the selection is cleared
            time.sleep(0.1)
            keyboard.write(staging + "\\", delay=PATH_CHAR_DELAY)   # character by character, fast
            time.sleep(0.3)

        # 6. Enter - second press (Windows Explorer)
        print("   -> Pressing Enter (second time, Explorer)...")
        pyautogui.press('enter')

        time.sleep(T("after_enter2"))

        # 8. Enter + Esc + Esc - close any dialogs after saving
        print("   -> Enter + Esc + Esc (closing dialogs after saving)...")
        pyautogui.press('enter')
        time.sleep(T("after_final_enter"))
        hold_key('esc')
        time.sleep(T("after_esc1"))
        hold_key('esc')
        time.sleep(T("after_esc2"))

        # was the file saved? - move it from the staging folder to the doctor/day folder
        if staging:
            moved = move_from_staging(save_dir)
            if not moved:
                file_not_saved(save_dir)
                return False
            print(f"   -> File {moved} moved to the save folder.")

        print("   -> Record saved.")
        return True
    else:
        print("   -> No red dots, skipping save.")
        return False


# SEARCH BY DATE


def do_search(dob_text, pt_brown_input, pt_search_btn):
    ensure_page("before search")
    print(f"   Typing the date into the search field: '{dob_text}'")

    # 1. Click the field twice to make sure it gets focus
    pyautogui.click(pt_brown_input)
    time.sleep(T("search_click1"))
    pyautogui.click(pt_brown_input)
    time.sleep(T("search_click2"))

    # 2. Triple click - selects all text in the field
    pyautogui.tripleClick(pt_brown_input)
    time.sleep(T("search_triple"))

    # 3. Delete the selection
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(T("search_ctrl_a"))
    pyautogui.press('delete')
    time.sleep(T("search_delete"))

    # 4. Type the date character by character (works even with date-picker fields)
    type_text_safe(dob_text)
    time.sleep(T("search_after_type"))

    # 5. Click the search button
    pyautogui.click(pt_search_btn)
    print(f"   Waiting for the results to load ({fmt_sec(T('search_after_click'))} sec)...")
    time.sleep(T("search_after_click"))


def handle_ticket(dob_text, source_name, c, save_dir=""):
    """Searches the website for the patient by date of birth and saves all found records (to save_dir, if given).
    Returns the number of saved records (both Saves completed)."""
    if not dob_text or not source_name:
        print("! Could not read text from the document. Skipping the ticket.")
        return 0

    print(f"Read: name = '{source_name}', DOB = '{dob_text}'")
    if save_dir:
        print(f"Save folder: {save_dir}")

    # Search on the website
    do_search(dob_text, c["pt_brown_input"], c["pt_search_btn"])

    # Find matching names
    matches = find_matching_names_in_region(c["reg_results"], source_name)
    print(f"Name matches found (>=70%): {len(matches)}")

    match_count = len(matches)
    if match_count == 0:
        print("No matches found. Skipping.")
        return 0

    print(f"Found {match_count} record(s). Processing them one by one (no limit on the number)...")
    record_args = (c["pt_three_dots_btn"], c["pt_three_dots_option"], c["pt_dark_green_btn"],
                   c["pt_dropdown_opt"], c["reg_results"], c["reg_red_dots"], c["reg_target_color"],
                   c.get("pt_explorer_path"), save_dir, c.get("pt_close_tab"))

    saved = 0
    # Process the first record right away from the already found matches list
    try:
        saved += bool(process_record(matches[0], *record_args))
    except Exception as e:
        print(f"   [ERROR] While processing record #1: {e}")

    # The remaining records (2nd, 3rd, ... Nth) - after the previous one is saved
    # the results list on the page may be rebuilt, so before
    # each next record the search is repeated and the record with
    # the corresponding index is taken. If the repeated search returns fewer records
    # than expected, the last available one is taken.
    for i in range(1, match_count):
        wait_if_paused()
        print(f"Repeated search for record #{i + 1} of {match_count}...")
        try:
            do_search(dob_text, c["pt_brown_input"], c["pt_search_btn"])
            new_matches = find_matching_names_in_region(c["reg_results"], source_name)

            if len(new_matches) > i:
                target = new_matches[i]
            elif len(new_matches) >= 1:
                print(f"   [!] The repeated search found only {len(new_matches)} "
                      f"record(s) instead of the expected {i + 1}. Taking the last available one.")
                target = new_matches[-1]
            else:
                print("   [!] The repeated search found no records. "
                      "Skipping the remaining records for this ticket.")
                break

            print(f"Processing record #{i + 1}...")
            saved += bool(process_record(target, *record_args))
        except Exception as e:
            print(f"   [ERROR] While processing record #{i + 1}: {e}")
    return saved
