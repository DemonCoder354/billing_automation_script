"""Settings file (logs/settings.json) and the adjustable timings."""
from __future__ import annotations

import json
import os
import threading

from ..paths import DEFAULT_CALIBRATION_FILE
from .applog import LOG_DIR


# All values are in seconds. The defaults match the former hard-coded pauses.
# Settings are stored in the shared file logs/settings.json (key "timings").


TIMING_MAX_SEC = 600

TIMING_GROUPS = [
    ("Startup", [
        ("start_delay", 5, "Delay after Start / Calibration / Continue"),
    ]),
    ("Record page (after clicking the found patient)", [
        ("page_load", 6.5, "Record page load"),
        ("after_close_tab", 1, "After closing the tab (X button)"),
        ("after_dark_green", 1, "After the dark-green button"),
        ("after_dropdown", 1, "After the dropdown menu option"),
        ("after_three_dots", 1, "After the '3 dots' button"),
        ("after_three_dots_option", 5, "After the '3 dots' menu option"),
        ("after_enter1", 3, "After the 1st Enter (browser dialog)"),
        ("path_click", 0.5, "After clicking the path bar in Explorer"),
        ("after_path_enter", 1.5, "After typing the folder path (navigating to the folder)"),
        ("after_enter2", 2, "After the 2nd Enter (Explorer)"),
        ("after_final_enter", 0.5, "After the last Enter"),
        ("after_esc1", 0.5, "After the 1st Esc"),
        ("after_esc2", 1, "After the 2nd Esc"),
    ]),
    ("Search by date", [
        ("search_click1", 0.4, "After the 1st click on the date field"),
        ("search_click2", 0.4, "After the 2nd click on the date field"),
        ("search_triple", 0.3, "After the triple click"),
        ("search_ctrl_a", 0.1, "After Ctrl+A"),
        ("search_delete", 0.2, "After Delete"),
        ("type_char_delay", 0.05, "Pause between characters when typing the date"),
        ("search_after_type", 3, "After typing the date (before the search button)"),
        ("search_after_click", 5, "Waiting for results after the search button"),
    ]),
    ("Moving between tickets", [
        ("after_nextgen_click", 1, "After clicking the center of NextGen"),
        ("after_next_arrow", 5, "After the 'next ticket' arrow"),
        ("error_pause", 5, "Pause after an error in the main loop"),
    ]),
]
TIMING_DEFAULTS = {key: default for _title, _items in TIMING_GROUPS for key, default, _label in _items}
timings = dict(TIMING_DEFAULTS)


def T(key):
    """Current timing value (sec) by key."""
    return timings.get(key, TIMING_DEFAULTS[key])


def fmt_sec(value):
    """5.0 -> '5', 6.5 -> '6.5' (for messages and input fields)."""
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _apply_timings(raw):
    """Copies valid values from the raw dict into timings. Invalid/missing ones keep their defaults."""
    for key in TIMING_DEFAULTS:
        v = raw.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= TIMING_MAX_SEC:
            timings[key] = float(v)
        elif key in raw:
            print(f"[TIMINGS] [!] '{key}' = {v!r} is invalid, using {fmt_sec(TIMING_DEFAULTS[key])}.")


def load_timings():
    """Loads timings from the settings (logs/settings.json)."""
    raw = SETTINGS.get("timings")
    if isinstance(raw, dict) and raw:
        _apply_timings(raw)


def save_timings():
    """Writes the current timings to logs/settings.json. Returns True/False."""
    with settings_lock:
        SETTINGS["timings"] = dict(timings)
    return save_settings()


# SETTINGS FILE (logs/settings.json) - independent of the program version
# Stores: calibration file path, last doctor, last selected logs, timings.
# A newer version reads the same file: missing keys get defaults,
# unknown keys (from other versions) are kept as is.
# Edit it by hand only while the program is closed (otherwise it is overwritten from memory).
SETTINGS_FILE = os.path.join(LOG_DIR, "settings.json")
SETTINGS_FORMAT = 1
settings_lock = threading.RLock()
SETTINGS = {}


def _default_settings():
    return {
        "settings_format": SETTINGS_FORMAT,
        "calibration_file": DEFAULT_CALIBRATION_FILE,
        "logs": {"main": ""},
        "timings": {},   # empty = default values (see TIMING_GROUPS)
        "ticket_source": "pdf",   # 'pdf' - tickets from PDF files, 'nextgen' - from the NextGen screen
        "pdf_folder": "",         # folder with docN.pdf (empty = default pdf_text folder)
    }


def load_settings():
    """Reads logs/settings.json (if present) and fills in defaults."""
    data = _default_settings()
    raw = None
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("the file root is not a dict")
        except Exception as e:
            raw = None
            try:
                os.replace(SETTINGS_FILE, SETTINGS_FILE + ".bad")
                print(f"[SETTINGS] [ERROR] Settings file is corrupted ({e}); renamed to settings.json.bad, "
                      "using default values.")
            except OSError:
                print(f"[SETTINGS] [ERROR] Settings file is corrupted ({e}). Using default values.")
    if raw:
        for k, v in raw.items():          # keep unknown keys (from other versions)
            if k not in data and k != "timings_help":
                data[k] = v
        cal = raw.get("calibration_file")
        if isinstance(cal, str) and cal.strip():
            data["calibration_file"] = cal.strip()
        if isinstance(raw.get("logs"), dict):
            for k, v in raw["logs"].items():
                if isinstance(v, str):
                    data["logs"][k] = v.strip()
        if isinstance(raw.get("timings"), dict):
            data["timings"] = dict(raw["timings"])
        if raw.get("ticket_source") in ("pdf", "nextgen"):
            data["ticket_source"] = raw["ticket_source"]
        if isinstance(raw.get("pdf_folder"), str):
            data["pdf_folder"] = raw["pdf_folder"].strip()
    with settings_lock:
        SETTINGS.clear()
        SETTINGS.update(data)
    return data


def save_settings():
    """Atomically writes settings to logs/settings.json. Returns True/False."""
    with settings_lock:
        data = dict(SETTINGS) if SETTINGS else _default_settings()
        data["settings_format"] = SETTINGS_FORMAT
        data["timings"] = dict(timings)
        data["timings_help"] = {key: label for _t, items in TIMING_GROUPS for key, _d, label in items}
        tmp = SETTINGS_FILE + ".tmp"
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SETTINGS_FILE)
            return True
        except Exception as e:
            print(f"[SETTINGS] [ERROR] Could not save '{SETTINGS_FILE}': {e}")
            return False


def update_settings(**changes):
    """Changes top-level keys (calibration_file, logs, ...) and saves the file."""
    with settings_lock:
        if not SETTINGS:
            SETTINGS.update(_default_settings())
        SETTINGS.update(changes)
    return save_settings()
