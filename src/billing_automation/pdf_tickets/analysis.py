"""Finding missing tickets: SEQ NO gaps and pauses between printed files."""
from __future__ import annotations

import os
import statistics

from .config import MAX_SEQ_GAP, NEW_PRINT_PAUSE, PAUSE_MIN
from .ticket import ticket_key


def describe(t):
    seq = t["seq"] if t["seq"] is not None else "?"
    return f"SEQ {seq} {t['name']} ({t['date']} {t['time']})"


def analyze(files, tickets, mtimes, expected):
    """Report text: what is missing and where."""
    blanks = {i for i, t in enumerate(tickets) if t.get("blank")}
    # a reprinted ticket is counted once (the first copy is kept)
    first_of, dups = {}, {}
    for i, t in enumerate(tickets):
        key = ticket_key(t)
        if key and key in first_of:
            dups[i] = first_of[key]
        elif key:
            first_of[key] = i
    keep = [i for i in range(len(files)) if i not in blanks and i not in dups]
    dup_lines = [f"  file {i + 1} = file {j + 1}: {describe(tickets[i])}" for i, j in sorted(dups.items())]
    files = [files[i] for i in keep]
    tickets = [tickets[i] for i in keep]
    mtimes = [mtimes[i] for i in keep]
    n = len(files)
    skipped = ([f"blank pages: {len(blanks)}"] if blanks else []) + ([f"duplicates: {len(dups)}"] if dups else [])
    lines = [f"Tickets: {n}" + (f", in MedLedger: {expected}" if expected else "")
             + (f" (not counting {', '.join(skipped)})" if skipped else "")]
    if dup_lines:
        lines += ["Duplicates of the same ticket (the extra ones can be deleted):"] + dup_lines
    if not n:
        return "\n".join(lines + ["The folder is empty."])

    # a number that OCR could not read is restored from its neighbours (56, ?, 58 -> 57)
    seqs = [t["seq"] for t in tickets]
    unreadable = []
    for i, s in enumerate(seqs):
        if s is None:
            prev = next((seqs[j] for j in range(i - 1, -1, -1) if seqs[j] is not None), None)
            nxt = next((seqs[j] for j in range(i + 1, n) if seqs[j] is not None), None)
            if prev is not None and nxt is not None and nxt - prev == 2:
                seqs[i] = prev + 1
            else:
                unreadable.append(i)

    # 1) gaps in SEQ NO. SEQ numbering is separate for each creation date and contains
    #    other doctors' numbers - so only a "hole" between two ADJACENT printed files
    #    with the same date counts as a gap (..., 17, [no 18], 19, ...).
    seq_gaps = []  # (missing SEQs, index of the file before)
    for i in range(n - 1):
        a, b = seqs[i], seqs[i + 1]
        if a is None or b is None or tickets[i]["date"] != tickets[i + 1]["date"]:
            continue
        if 1 < b - a <= MAX_SEQ_GAP + 1:
            seq_gaps.append((list(range(a + 1, b)), i))

    # 2) long pauses during printing; each missing ticket adds ~8 s to the pause
    gaps = [mtimes[i] - mtimes[i - 1] for i in range(1, n)]
    typical = statistics.median(gaps) if gaps else 0
    limit = max(PAUSE_MIN, typical * 2.2)
    pauses = {i: gaps[i - 1] for i in range(1, n) if gaps[i - 1] > limit}  # pause before file i

    # 3) combine: a loss = a place in print order (after file k), lost = how many tickets.
    #    The main sign is the pause (all losses found so far had a pause of ~+8 s per ticket);
    #    a SEQ gap between neighbours only confirms it: SEQ contains other doctors' numbers.
    missing_total = (expected - n) if expected else None
    seq_at = {k: missing for missing, k in seq_gaps}
    places = {}  # k -> {"reasons": [...], "lost": n}
    if missing_total is None or missing_total > 0:
        for i, sec in pauses.items():
            if sec > NEW_PRINT_PAUSE:
                continue  # this is already a separate print job (e.g. a reprint), not a loss
            k = i - 1
            by_pause = max(1, round((sec - typical) / 8))
            reasons = [f"print pause {sec:.0f} s (usually {typical:.0f} s) - looks like {by_pause} ticket(s)"]
            lost = by_pause
            if k in seq_at:
                reasons.insert(0, "missing SEQ " + ", ".join(map(str, seq_at[k]))
                               + f" (between {seqs[k]} and {seqs[k + 1]})")
                lost = max(lost, len(seq_at[k]))
            places[k] = {"reasons": reasons, "lost": lost}

    found = sorted(places)
    if missing_total is not None:
        if missing_total > 0:
            lines.append(f"MISSING {missing_total} ticket(s).")
        elif missing_total == 0:
            lines.append("The count matches: all tickets are in place.")
        else:
            lines.append(f"There are {-missing_total} more files than tickets - there may be duplicates or extra files.")

    of = f" of {expected}" if expected else ""
    accounted = sum(places[k]["lost"] for k in found)
    # a loss at the very start of printing is visible neither by a pause nor by neighbours - only by the count
    unexplained = (missing_total - accounted) if missing_total else 0
    if not found and not unexplained:
        lines.append("No signs of losses between files.")
    if found:
        lines.append("")
        lines.append("Where tickets went missing (in print order):")
        shift = max(unexplained, 0)  # if the first ticket(s) went missing, the MedLedger numbers are shifted
        for k in found:
            p = places[k]
            reasons = p["reasons"]
            strong = any(r.startswith("missing SEQ") for r in reasons) and any(r.startswith("print pause") for r in reasons)
            mark = "CERTAIN" if strong else "likely"
            positions = [k + 2 + shift + j for j in range(p["lost"])]  # numbers in MedLedger
            shift += p["lost"]
            nums = ", ".join(str(x) for x in positions)
            lines.append(f"• [{mark}] Fee Tickets {nums}{of}"
                         + (f"  ({p['lost']} pcs)" if p["lost"] > 1 else ""))
            lines.append(f"    after file {k + 1}: {describe(tickets[k])}")
            if k + 1 < n:
                lines.append(f"    before file {k + 2}: {describe(tickets[k + 1])}")
            lines.append("    reasons: " + "; ".join(reasons))
    if unexplained > 0:
        lines.append("")
        lines.append(f"{unexplained} more ticket(s) without signs between files - most likely the very first "
                     f"of the print job: check Fee Tickets 1{f'-{unexplained}' if unexplained > 1 else ''}{of} "
                     f"(first file - {describe(tickets[0])}). "
                     f"If everything is in place there, then it is the last ones ({expected - unexplained + 1}{of} and on).")
    elif unexplained < 0:
        lines.append("")
        lines.append(f"More places than missing tickets ({accounted} > {missing_total}): "
                     "check the ones marked 'CERTAIN' and 'likely' first.")

    if unreadable:
        lines.append("")
        lines.append("Could not read SEQ NO (check by eye):")
        for i in unreadable:
            lines.append(f"  file {i + 1}: {os.path.basename(files[i])} - {tickets[i]['name']} {tickets[i]['time']}")
    return "\n".join(lines)
