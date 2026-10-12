"""Runtime state shared by the AUTO-WORK threads: the pause flag, the page counter and the GUI queues."""
from __future__ import annotations

import queue
import time

import keyboard

is_paused = False
page_lost_count = 0      # how many times the page got kicked out (main_pdf repeats the ticket)

# program output lines -> 'Program output' panel in the window
console_queue: queue.Queue = queue.Queue()
# Command queue for the GUI: hotkeys arrive from the keyboard library's thread,
# while Tkinter may only be touched from its own thread.
ui_queue: queue.Queue = queue.Queue()


def toggle_pause() -> None:
    global is_paused
    is_paused = not is_paused
    status = "PAUSED" if is_paused else "RESUMED"
    print(f"\n[F9] -> {status}")


def wait_if_paused() -> None:
    while is_paused:
        time.sleep(0.3)


def open_pause_menu() -> None:
    """F10 hotkey handler. Asks the GUI to show the pause menu."""
    ui_queue.put("pause_menu")


def register_hotkeys() -> None:
    """Global hotkeys (they work while the window is minimized): F9 pause, F10 pause menu, F6 start."""
    keyboard.add_hotkey('f9', toggle_pause)
    keyboard.add_hotkey('f10', open_pause_menu)
    keyboard.add_hotkey('f6', lambda: ui_queue.put("start"))
