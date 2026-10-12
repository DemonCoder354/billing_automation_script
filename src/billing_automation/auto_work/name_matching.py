"""Finding the ticket's patient in the website search results (blue names, OCR + fuzzy matching)."""
from __future__ import annotations

import re

import cv2
import numpy as np
import pytesseract
from PIL import ImageGrab
from thefuzz import fuzz

from .state import wait_if_paused


def find_matching_names_in_region(region, target_name):
    wait_if_paused()
    img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3]))
    img_np = np.array(img)
    img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

    # Upscale the image for better OCR.
    # The scale is a variable (used below when converting the click coordinates back).
    SCALE = 4
    img_cv_scaled = cv2.resize(img_cv, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)

    # --- Filter blue text (the characteristic color of names in the list) ---
    # IMPORTANT: there used to be a hard RGB cube here. The problem with that approach is that
    # antialiased pixels on the edges of thin letters (especially narrow letters like
    # "I", "L", "U") are lighter and less saturated than "pure" blue and
    # do NOT fall into a narrow RGB range. As a result the letters come out ragged,
    # Tesseract sees a broken outline and returns conf=0 (as happened with "JULIA") - the whole word
    # was lost from the name block.
    #
    # Solution: 1) work in HSV, where blue is separated by hue
    # almost independently of brightness/saturation - robust to antialiasing;
    # 2) apply morphological closing (CLOSE) to "heal" broken
    # letter strokes that still dropped out of the mask at the edges.
    img_hsv = cv2.cvtColor(img_cv_scaled, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([90, 30, 50])
    upper_blue = np.array([140, 255, 255])
    blue_mask_u8 = cv2.inRange(img_hsv, lower_blue, upper_blue)

    # A small "closing" (dilate -> erode) joins broken letters
    # without letting them merge with neighbouring words (the kernel is small, 2x2).
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    blue_mask_u8 = cv2.morphologyEx(blue_mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
    blue_mask = blue_mask_u8 > 0

    # Create a black-and-white image: blue text -> black, everything else -> white
    processed = np.ones(img_cv_scaled.shape[:2], dtype=np.uint8) * 255
    processed[blue_mask] = 0

    # OCR: use --psm 4 (Assume a single column of text of variable sizes)
    config = '--psm 4 -l eng'
    data = pytesseract.image_to_data(processed, config=config, output_type=pytesseract.Output.DICT)

    # Collect text blocks (merge multi-line names within one cell)
    matches = []
    blocks_by_id = {}   # block_id -> block data (collected regardless of the OCR order)

    # DIAGNOSTICS: keep ALL recognized words (including those filtered by conf),
    # so the log shows whether a word was not read by Tesseract at all
    # or was read but with low confidence
    raw_debug = []

    for i in range(len(data['text'])):
        raw_text = data['text'][i]
        if raw_text.strip():
            raw_debug.append(f"{raw_text.strip()!r}(conf={data['conf'][i]})")

        # Threshold lowered from 30 to 0 (was 10) - even a word with conf=0 (like "JULIA" in
        # the example) still goes into the block. Previously such words were discarded
        # ENTIRELY, so part of the full name went missing and the final similarity
        # dropped artificially. A little noise from truly junk words is not
        # a problem: the final comparison uses fuzzy matching with a 70% threshold.
        if int(data['conf'][i]) >= 0 and raw_text.strip():
            # Completely remove OCR junk characters from anywhere in the word (not just the edges),
            # but keep the comma - it is needed to join the first and last names
            word = re.sub(r'[|()\[\]{}_~`^*]', '', raw_text).strip()
            if not word:
                continue

            # Group by block and paragraph, not by line
            block_id = f"{data['block_num'][i]}_{data['par_num'][i]}"

            if block_id not in blocks_by_id:
                word_center_x = data['left'][i] + (data['width'][i] // 2)
                word_center_y = data['top'][i] + (data['height'][i] // 2)

                blocks_by_id[block_id] = {
                    'text': [],
                    # Divide by SCALE to go from the resize() scale back to real screen coordinates
                    'click_x': word_center_x // SCALE,
                    'click_y': word_center_y // SCALE,
                    # Raw coordinates (in the OCR image scale) - needed to sort by rows,
                    # since the block_num/par_num order from Tesseract sometimes gets mixed up on table layouts
                    'raw_top': data['top'][i],
                    'raw_left': data['left'][i],
                }

            blocks_by_id[block_id]['text'].append(word)

    print(f"   [OCR-DEBUG] All recognized words (all are used, including conf=0): {raw_debug}")

    # Sort blocks by real coordinates (top to bottom, left to right) -
    # more reliable than the block_num/par_num order, which Tesseract may
    # mix up on a multi-column table (Name/DOB/Gender/...)
    blocks_list = sorted(blocks_by_id.values(), key=lambda b: (b['raw_top'], b['raw_left']))

    print("   OCR lines in the results list:")

    # Clean the target (source) name of pipes and extra characters for a correct comparison
    clean_target_name = target_name.replace('|', ' ').strip()

    n_blocks = len(blocks_list)
    consumed = set()  # indices of blocks already "used" as the second half of a name

    for idx in range(n_blocks):
        if idx in consumed:
            continue

        single_text = " ".join(blocks_list[idx]['text']).strip()
        # fuzz.token_sort_ratio sorts the words before comparing, so it is already
        # insensitive to "First Last" / "Last First" order WITHIN a single line
        best_text = single_text
        best_score = fuzz.token_sort_ratio(single_text.lower(), clean_target_name.lower())
        will_consume_next = False

        # Try merging with the NEXT block (by real coordinates, see the sorting above) -
        # not only when there is a comma. This is needed when the first and last names are on
        # different lines WITHOUT a comma and/or in swapped order (last name on top, first name below)
        if idx + 1 < n_blocks:
            next_block = blocks_list[idx + 1]
            next_text = " ".join(next_block['text']).strip()
            merged_text = f"{single_text} {next_text}".strip()
            merged_score = fuzz.token_sort_ratio(merged_text.lower(), clean_target_name.lower())

            # Protection against false merges: check how close the blocks are vertically.
            # Merging by comma (a strong explicit sign) allows a larger spread
            # than merging just because the similarity improved (could be a coincidence)
            vertical_gap = abs(next_block['raw_top'] - blocks_list[idx]['raw_top'])
            comma_signal = single_text.endswith(',')
            close_enough = vertical_gap < (250 if comma_signal else 60)

            # Merge if: (a) explicit sign - a comma at the end of the first line,
            # or (b) merging noticeably improves the match (not random noise) -
            # and in both cases the blocks must not be too far apart
            if close_enough and (comma_signal or merged_score > best_score + 5):
                best_text = merged_text
                best_score = merged_score
                will_consume_next = True

        print(f"     '{best_text}' -> similarity {best_score}%")

        if best_score >= 70:
            # Calculate absolute screen click coordinates right on the first word
            abs_x = region[0] + blocks_list[idx]['click_x']
            abs_y = region[1] + blocks_list[idx]['click_y']

            matches.append((abs_x, abs_y, best_text, best_score))
            print(f"   [MATCH] '{best_text}' ({best_score}%) -> click exactly on the text at: ({abs_x}, {abs_y})")

            if will_consume_next:
                consumed.add(idx + 1)

    return matches
