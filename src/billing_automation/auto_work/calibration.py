"""Calibration of screen points and regions (saved to a JSON file)."""
from __future__ import annotations

import json
import os
import time

import keyboard
import pyautogui

from ..paths import DEFAULT_CALIBRATION_FILE


def calibrate_point(element_name, description):
    print(f"\n>>> STEP: {element_name} <<<")
    print(f"Hint: {description}")
    print("Action: hover the cursor over this element and press SPACE...")
    while True:
        if keyboard.is_pressed('space'):
            pos = pyautogui.position()
            print(f"[OK] Saved: {pos}")
            time.sleep(0.5)
            return pos
        time.sleep(0.05)

def calibrate_region(region_name, description):
    print(f"\n>>> STEP: {region_name} (REGION) <<<")
    print(f"Hint: {description}")

    print("Action 1: hover over the TOP-LEFT corner of the region and press SPACE...")
    while True:
        if keyboard.is_pressed('space'):
            p1 = pyautogui.position()
            print(f"[OK] Point 1: {p1}")
            time.sleep(0.5)
            break
        time.sleep(0.05)

    print("Action 2: hover over the BOTTOM-RIGHT corner of the region and press SPACE...")
    while True:
        if keyboard.is_pressed('space'):
            p2 = pyautogui.position()
            print(f"[OK] Point 2: {p2}")
            time.sleep(0.5)
            break
        time.sleep(0.05)

    return (p1.x, p1.y, p2.x - p1.x, p2.y - p1.y)

CALIBRATION_FILE = DEFAULT_CALIBRATION_FILE   # replaced by the GUI when another file is chosen

# Order and names of the calibration fields - used both when saving and when
# building the final variables after loading.
CALIBRATION_STEPS = [
    ("reg_source_dob", "region", "Date of birth in the document",
     "Select the DOB cell in NextGen MCS where the date is written."),
    ("reg_source_name", "region", "Full name in the document",
     "Select the LAST NAME and FIRST NAME cells in NextGen MCS."),
    ("pt_brown_input", "point", "Date input field on the website",
     "Hover over the center of the website field where the program will type the date."),
    ("pt_search_btn", "point", "Search button",
     "Hover over the search button on the website."),
    ("reg_page_check", "region", "Website page check region",
     "Select a small area that ALWAYS looks the same on the working website page - both on the search "
     "page and on the patient page (logo, header, section title). If the page gets kicked out, it changes "
     "and the program pauses."),
    ("reg_results", "region","Name list region (search results)",
     "Select the area on the website where the list of names appears after searching."),
    ("pt_close_tab", "point", "X of the PREVIOUS tab (closed after the patient opens)",
     "Click a name in the search results - a new tab opens. Wait for it to load and hover "
     "over the X of the PREVIOUS (unneeded) tab."),
    ("reg_red_dots", "region","Red dots region (patient record page)",
     "Select the area on the patient record page where red circles appear."),
    ("pt_dark_green_btn", "point", "Dark-green button",
     "Hover over the dark-green button (clicked FIRST when saving)."),
    ("pt_dropdown_opt", "point", "Dropdown menu option",
     "Open the menu yourself and hover over the required option."),
    ("pt_three_dots_btn", "point", "'3 dots' button (actions menu)",
     "Hover over the three-dots button '⋯' (clicked AFTER the dark-green one)."),
    ("pt_three_dots_option", "point", "Option in the '3 dots' menu",
     "Open the 3-dots menu manually, hover over the required option, then press SPACE."),
    ("pt_explorer_path", "point", "Explorer path bar (save dialog)",
     "Manually get to the Explorer window (after the first Save) and hover over the path bar at the top of the window."),
    ("pt_nextgen_center", "point", "Center of the NextGen document",
     "Hover over the center of the NextGen MCS window (so the program can focus it before moving to the next ticket)."),
    ("pt_next_arrow", "point", "NEXT ticket arrow (►)",
     "Hover over the orange arrow '►' (next record/Fee Ticket) in NextGen MCS."),
    ("reg_ticket_counter", "region", "Ticket counter ('Fee Tickets 1 of 17')",
     "Select the area where the ticket counter is shown."),
    ("reg_target_color", "region", "Color search region",
     "Select the area in which to look for the sample color (TARGET_COLOR_RGB)."),
]


def run_calibration(only=None, base=None):
    """
    Goes through the calibration steps (point and region coordinates) and
    returns a dict {field_name: value}. only - list of fields to
    calibrate (the rest are taken from base).
    """
    print("\n===================================================")
    print("=== CALIBRATION MODE (SETUP BEFORE START) ===")
    print("===================================================")

    result = dict(base or {})
    for field_name, kind, title, hint in CALIBRATION_STEPS:
        if only is not None and field_name not in only:
            continue
        if kind == "point":
            result[field_name] = tuple(calibrate_point(title, hint))
        else:
            result[field_name] = tuple(calibrate_region(title, hint))
    return result


def save_calibration(data):
    """Writes the calibration result to a JSON file."""
    try:
        with open(CALIBRATION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[CALIBRATION] Saved to file '{CALIBRATION_FILE}'.")
    except Exception as e:
        print(f"[CALIBRATION] [ERROR] Failed to save calibration file: {e}")


def load_calibration():
    """
    Tries to load calibration from the file. Returns a dict of coordinates,
    or None if the file is missing, corrupted or lacks fields.
    """
    if not os.path.exists(CALIBRATION_FILE):
        return None
    try:
        with open(CALIBRATION_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        data = {}
        for field_name, _kind, _title, _hint in CALIBRATION_STEPS:
            if field_name not in raw:
                print(f"[CALIBRATION] Field '{field_name}' is missing in the file. Recalibration required.")
                return None
            data[field_name] = tuple(raw[field_name])
        return data
    except Exception as e:
        print(f"[CALIBRATION] [ERROR] Could not read the calibration file ({e}). Recalibration required.")
        return None


def missing_calibration_fields():
    """(calibration file data, [fields missing from it]); (None, None) - file missing or corrupted."""
    try:
        with open(CALIBRATION_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return None, None
    except Exception:
        return None, None
    return raw, [name for name, _k, _t, _h in CALIBRATION_STEPS if name not in raw]


def get_calibration():
    """
    Main entry point: if a calibration file already exists, use it right away
    (no waiting). If not, run calibration and save the result.
    """
    calib = load_calibration()

    if calib is not None:
        return calib

    calib = run_calibration()
    save_calibration(calib)
    return calib
