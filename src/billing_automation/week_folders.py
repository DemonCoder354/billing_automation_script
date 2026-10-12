"""Week folders on the desktop: CAREPORTAL <Mon>-<Fri>\\<DOCTOR>\\<DOCTOR> <MMDDYYYY>."""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import date, timedelta

WEEK_FOLDER_PREFIX = "CAREPORTAL"
DATE_FORMAT = "%m%d%Y"  # MMDDYYYY
WEEK_FOLDER_RE = re.compile(rf"^{WEEK_FOLDER_PREFIX} \d{{8}}-\d{{8}}$", re.IGNORECASE)


def week_folder_name(monday: date) -> str:
    """'CAREPORTAL 08242026-08282026' for the week that starts on the given Monday."""
    friday = monday + timedelta(days=4)
    return f"{WEEK_FOLDER_PREFIX} {monday.strftime(DATE_FORMAT)}-{friday.strftime(DATE_FORMAT)}"


def create_week_folders(base_path: str, doctors: list[str], start_date: date,
                        log: Callable[[str], None]) -> str:
    """Creates the week folder and the nested doctor/day folders (Mon-Fri). log(str) prints lines."""
    week_dates = [start_date + timedelta(days=i) for i in range(5)]  # Mon-Fri
    week_folder_path = os.path.join(base_path, week_folder_name(start_date))

    for doctor in doctors:
        doctor_path = os.path.join(week_folder_path, doctor)
        for day in week_dates:
            day_folder_path = os.path.join(doctor_path, f"{doctor} {day.strftime(DATE_FORMAT)}")
            os.makedirs(day_folder_path, exist_ok=True)
            log(f"Created: {day_folder_path}")

    log(f"\nDone! The structure was created in: {week_folder_path}")
    return week_folder_path
