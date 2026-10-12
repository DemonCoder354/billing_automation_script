"""Settings and log files, document numbering and the index of saved tickets."""
from __future__ import annotations

import json
import os
import re
import time

from ..paths import PDF_TICKETS_DIR
from .config import ALL_FOLDER_NAME, DEFAULT_INBOX, FOLDER_COUNT
from .ticket import ticket_key


def data_dir():
    folder = PDF_TICKETS_DIR
    os.makedirs(folder, exist_ok=True)
    return folder


def documents_log_path():
    """Log of saved numbers: the logs folder next to the program."""
    folder = os.path.join(PDF_TICKETS_DIR, "logs")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "pdf_saver_numbers.txt")


def append_log(name, line):
    try:
        with open(os.path.join(data_dir(), name), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_json(name, default):
    try:
        with open(os.path.join(data_dir(), name), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError, TypeError):
        return default


def save_json(name, data):
    with open(os.path.join(data_dir(), name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_saver_config():
    data = load_json("settings.json", {})
    folders = list(data.get("folders", []))[:FOLDER_COUNT]
    folders += [""] * (FOLDER_COUNT - len(folders))
    try:
        selected = int(data.get("selected", 0))
    except (TypeError, ValueError):
        selected = 0
    if not 0 <= selected < FOLDER_COUNT:
        selected = 0
    return {"folders": folders, "selected": selected, "inbox": data.get("inbox") or DEFAULT_INBOX}


def last_document_number():
    last = 0
    try:
        with open(documents_log_path(), "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\S+ \S+\t(\d+)\t", line)
                if m:
                    last = max(last, int(m.group(1)))
    except OSError:
        pass
    return last


def next_document(folder):
    """Next number and a docN.pdf path that does not exist in the folder yet."""
    n = last_document_number() + 1
    while os.path.exists(os.path.join(folder, f"doc{n}.pdf")):
        n += 1
    return n, os.path.join(folder, f"doc{n}.pdf")


def record_document(n, path):
    with open(documents_log_path(), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{n}\t{path}\n")


def all_folder(folder):
    """The shared pdf_all folder next to the doctors' folders."""
    return os.path.join(os.path.dirname(os.path.normpath(folder)), ALL_FOLDER_NAME)


def all_copy_path(target):
    """Path of the copy in pdf_all: doctor name + file name (SMITH_doc5.pdf), without overwriting."""
    folder = os.path.dirname(target)
    stem, ext = os.path.splitext(f"{os.path.basename(folder)}_{os.path.basename(target)}")
    dest = os.path.join(all_folder(folder), stem + ext)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(all_folder(folder), f"{stem} ({i}){ext}")
        i += 1
    return dest


class TicketIndex:
    """Keys of already saved tickets: {path to docN.pdf: key}, file pdf_saver_data\\ticket_index3.json."""

    FILE = "ticket_index3.json"  # v3: the header is read cell by cell (SEQ NO is found more often)

    def __init__(self):
        self.data = load_json(self.FILE, {})

    def save(self):
        try:
            save_json(self.FILE, self.data)
        except OSError:
            pass

    def ensure(self, folder, read, log):
        """Computes keys for files in the doctor's folder that are not in the index yet (e.g. saved earlier)."""
        folder = os.path.normcase(os.path.normpath(folder))
        self.data = {p: k for p, k in self.data.items() if os.path.exists(p)}
        try:
            files = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".pdf")]
        except OSError:
            files = []
        todo = [p for p in files if os.path.normcase(p) not in self.data]
        if todo:
            log(f"Checking against the tickets already saved in the folder: recognizing {len(todo)} file(s)…")
            for p in todo:
                self.data[os.path.normcase(p)] = ticket_key(read(p))
            log("Check ready: duplicates of new tickets will be removed.")
        self.save()

    def duplicate_of(self, key, folder):
        """Path of an already saved ticket with the same key in the doctor's folder (or None)."""
        if not key:
            return None
        folder = os.path.normcase(os.path.normpath(folder))
        for path, k in self.data.items():
            if k == key and os.path.dirname(path) == folder and os.path.exists(path):
                return path
        return None

    def add(self, path, key):
        self.data[os.path.normcase(os.path.normpath(path))] = key
        self.save()
