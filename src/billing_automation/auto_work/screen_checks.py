"""Checks of the screen: the website page did not change, red dots, the target color."""
from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import ImageGrab

from . import state
from .state import ui_queue, wait_if_paused


page_ref = None          # reference image of the check region (taken at start)
page_region = None


def _grab_gray(region):
    img = ImageGrab.grab(bbox=(region[0], region[1], region[0] + region[2], region[1] + region[3]))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)


def take_page_reference(region):
    """Remembers what the check region looks like on a normal page."""
    global page_ref, page_region
    page_region = region
    page_ref = _grab_gray(region) if region and region[2] > 8 and region[3] > 8 else None
    if page_ref is not None:
        print("[PAGE CHECK] Reference of the check region taken - if the page gets kicked out, the program will pause.")


def _page_diff():
    """Difference between the check region and the reference (0 = identical; a shift of a couple of pixels does not count)."""
    cur = _grab_gray(page_region).astype(np.float32)
    m = 3
    ref = page_ref[m:-m, m:-m].astype(np.float32)
    res = cv2.matchTemplate(cur, ref, cv2.TM_SQDIFF)
    return float(np.sqrt(res.min() / ref.size))


PAGE_DIFF_LIMIT = 25   # mean brightness difference (0-255); above this the page is considered different


def ensure_page(where):
    """Checks the check region; if the page is different (kicked out) - pause, program window, beep.
    After F9 it checks again."""
    if page_ref is None:
        return
    while True:
        wait_if_paused()
        for attempt in range(3):   # the page may still be loading
            diff = _page_diff()
            if diff <= PAGE_DIFF_LIMIT:
                return
            time.sleep(2)
        state.page_lost_count += 1
        state.is_paused = True
        print(f"\n[!!! WEBSITE PAGE CHANGED - PAUSED] ({where}, difference {diff:.0f})\n"
              "    Looks like the page got kicked out. Return the website to the working page and press F9 -\n"
              "    the program will check the page and repeat the current ticket.\n"
              "    If the page is fine but the pause keeps happening, recalibrate the 'Website page check region'.")
        try:
            import winsound
            for _ in range(3):
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                time.sleep(0.4)
        except Exception:
            pass
        ui_queue.put("page_lost")


def check_for_red_dots(region):
    wait_if_paused()
    img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3]))
    img_np = np.array(img)
    red_mask = (
        (img_np[:, :, 0] > 180) &
        (img_np[:, :, 1] < 90) &
        (img_np[:, :, 2] < 90)
    )
    red_pixel_count = np.sum(red_mask)
    print(f"   Red pixels found: {red_pixel_count}")
    return red_pixel_count >= 5

# Sample color (averaged over the sample image)
TARGET_COLOR_RGB = (255, 224, 178)
TARGET_COLOR_TOLERANCE = 15  # tolerance per RGB channel

def check_for_target_color(region, target_rgb=TARGET_COLOR_RGB, tolerance=TARGET_COLOR_TOLERANCE, min_pixels=100):
    wait_if_paused()
    img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3]))
    img_np = np.array(img.convert('RGB')).astype(int)
    r, g, b = target_rgb
    color_mask = (
        (np.abs(img_np[:, :, 0] - r) <= tolerance) &
        (np.abs(img_np[:, :, 1] - g) <= tolerance) &
        (np.abs(img_np[:, :, 2] - b) <= tolerance)
    )
    color_pixel_count = np.sum(color_mask)
    print(f"   Target-color pixels found: {color_pixel_count}")
    return color_pixel_count > min_pixels
