"""Typing into the website and saving files through the Windows "Save As" dialog via a staging folder."""
from __future__ import annotations

import os
import time

import keyboard
import pyautogui
import pyperclip

from ..recycle_bin import to_recycle_bin
from . import state
from .applog import LOG_DIR
from .settings import T
from .state import ui_queue


PATH_CHAR_DELAY = 0.005   # pause between the characters of the path typed into the save dialog


def _folder_state(folder):
    """{file name: modification time} in the folder."""
    try:
        return {e.name: e.stat().st_mtime for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return {}


SAVE_STAGING = os.path.join(LOG_DIR, "saving")   # empty staging folder for the "Save" dialog


def _recycle(paths):
    to_recycle_bin(paths)


def prepare_staging():
    """Staging folder, emptied (leftovers from a previous failure go to the Recycle Bin). '' - failed."""
    try:
        os.makedirs(SAVE_STAGING, exist_ok=True)
        left = [os.path.join(SAVE_STAGING, n) for n in os.listdir(SAVE_STAGING)]
        if left:
            print(f"   [!] Files left in the staging folder ({len(left)}) - moving them to the Recycle Bin.")
            _recycle(left)
        return SAVE_STAGING
    except Exception as e:
        print(f"   [ERROR] Staging folder {SAVE_STAGING}: {e}")
        return ""


def move_from_staging(save_dir, wait=10):
    """Waits for the saved PDF in the staging folder and moves it to save_dir
    (if such a file already exists there, the old copy goes to the Recycle Bin). Returns the file name, or '' if there is no file."""
    import shutil
    last = None
    for _ in range(int(wait / 0.5)):
        try:
            files = [e for e in os.scandir(SAVE_STAGING)
                     if e.is_file() and e.name.lower().endswith(".pdf")]
        except OSError:
            files = []
        if files:
            f = max(files, key=lambda e: e.stat().st_mtime)
            size = f.stat().st_size
            if size and last == (f.name, size):   # the size no longer changes - the file is fully written
                target = os.path.join(save_dir, f.name)
                try:
                    if os.path.exists(target):
                        _recycle([target])
                        print(f"   -> {f.name} was already in the folder - old copy moved to the Recycle Bin.")
                    os.makedirs(save_dir, exist_ok=True)
                    shutil.move(f.path, target)
                    return f.name
                except Exception as e:
                    print(f"   [ERROR] Could not move {f.name}: {e}")
                    return ""
            last = (f.name, size)
        time.sleep(0.5)
    return ""


def file_not_saved(save_dir):
    """The file did not appear in the save folder (path not typed?) - pause, program window, beep."""
    state.page_lost_count += 1   # main_pdf will repeat this ticket
    state.is_paused = True
    print(f"\n[!!! FILE DID NOT APPEAR IN THE FOLDER - PAUSED]\n    {save_dir}\n"
          f"    The file never appeared in the staging folder {SAVE_STAGING} -\n"
          "    the save dialog did not save the file. Check the dialog (the 'File name' field must\n"
          "    start with the staging folder path), then press F9 - this ticket will be redone.")
    try:
        import winsound
        for _ in range(3):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            time.sleep(0.4)
    except Exception:
        pass
    ui_queue.put("file_not_saved")


def hold_key(key, seconds=0.1):
    """Press and hold: the browser sometimes misses a key press that is too short."""
    pyautogui.keyDown(key)
    time.sleep(seconds)
    pyautogui.keyUp(key)


def paste_text(text):
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.2)


def type_text_safe(text):
    """
    Types text character by character via keyboard.write (supports Unicode and special characters).
    If that fails, falls back to pyperclip + Ctrl+V.
    """
    try:
        keyboard.write(text, delay=T("type_char_delay"))
    except Exception as e:
        print(f"   [WARN] keyboard.write failed ({e}), using the clipboard...")
        paste_text(text)
