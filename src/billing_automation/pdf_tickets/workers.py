"""Background work: the OCR process pool, the inbox watcher (saving) and the OCR worker."""
from __future__ import annotations

import os
import shutil
import threading
import time

from ..recycle_bin import to_recycle_bin
from .config import ALL_FOLDER_NAME, BLANK_FOLDER_NAME, OCR_POLL_SECONDS, SAVER_POLL_SECONDS, WORKERS
from .deps import ensure_packages
from .storage import TicketIndex, all_copy_path, all_folder, next_document, record_document
from .text_layer import ocr_pdf
from .ticket import file_complete, is_blank, read_ticket, ticket_key
from .windows_ocr import WindowsOcr


# Parallel processing: several processes, each with its own OCR
# (pymupdf cannot be used from several threads of one process)
_PROCESS_OCR = None


def _process_init():
    global _PROCESS_OCR
    _PROCESS_OCR = WindowsOcr()


def _process_ocr_file(src, dst):
    return ocr_pdf(src, dst, _PROCESS_OCR)


def _process_read_ticket(path):
    return read_ticket(path, _PROCESS_OCR)


class Services:
    """Recognition process pool shared by the tabs; prepared in the background at startup."""

    def __init__(self, log):
        self.log = log
        self.ready = threading.Event()
        self.failed = False
        self.pool = None
        self.lang = ""
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        if not ensure_packages(self.log):
            self.failed = True
            return
        try:
            self.lang = WindowsOcr().lang  # check that Windows OCR is available
        except Exception as e:  # noqa: BLE001
            self.log(f"Windows OCR is unavailable: {e}")
            self.failed = True
            return
        from concurrent.futures import ProcessPoolExecutor
        self.pool = ProcessPoolExecutor(WORKERS, initializer=_process_init)
        self.ready.set()


class InboxWatcher(threading.Thread):
    """Sorting: inbox -> doctor's folder (docN.pdf) + copy in pdf_all; duplicate tickets go to the Recycle Bin."""

    def __init__(self, get_folder, get_inbox, log):
        super().__init__(daemon=True)
        self.get_folder = get_folder
        self.get_inbox = get_inbox
        self.log = log
        self.running = threading.Event()
        self.sizes = {}
        self.index = TicketIndex()
        self.indexed_folder = None
        self.ocr = None          # recognition for the duplicate check (created in this thread)
        self.ocr_failed = False

    def read(self, path):
        """Ticket header for the duplicate check; None if recognition is unavailable."""
        if self.ocr is None and not self.ocr_failed:
            try:
                self.ocr = WindowsOcr()
            except Exception as e:  # noqa: BLE001
                self.ocr_failed = True
                self.log(f"Recognition is unavailable ({e}) - duplicates are not checked.")
        if self.ocr is None:
            return None
        try:
            return read_ticket(path, self.ocr)
        except Exception:  # noqa: BLE001
            return None

    def stop(self):
        self.running.clear()

    def run(self):
        while True:
            time.sleep(SAVER_POLL_SECONDS)
            if not self.running.is_set():
                continue
            inbox = self.get_inbox()
            folder = self.get_folder()
            if not folder:
                self.log("The path to the selected folder is not set. Paused.")
                self.stop()
                continue
            if self.indexed_folder != folder:   # new doctor: find out what is already in their folder
                os.makedirs(folder, exist_ok=True)
                self.index.ensure(folder, self.read, self.log)
                self.indexed_folder = folder
            try:
                os.makedirs(inbox, exist_ok=True)
                files = [os.path.join(inbox, n) for n in os.listdir(inbox)
                         if n.lower().endswith(".pdf")]
            except OSError as e:
                self.log(f"No access to the inbox folder: {e}. Paused.")
                self.stop()
                continue
            # in print order: oldest first
            files.sort(key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0, p))
            self.sizes = {p: s for p, s in self.sizes.items() if p in files}
            for src in files:
                if not self.running.is_set():
                    break
                if not file_complete(src, self.sizes):
                    break  # wait until it is fully written, so as not to break the order
                try:
                    self.take(src, folder)
                except Exception as e:  # noqa: BLE001
                    self.log(f"WARNING! Could not process {os.path.basename(src)}: {e}")
                    break

    def take(self, src, folder):
        info = self.read(src)
        if (info.get("blank") if info else is_blank(src)):
            # a blank page gets no number: it goes to pdf\blank (cleared by "Cleanup")
            blank_dir = os.path.join(os.path.dirname(os.path.dirname(src)), BLANK_FOLDER_NAME)
            os.makedirs(blank_dir, exist_ok=True)
            shutil.move(src, os.path.join(blank_dir, os.path.basename(src)))
            self.sizes.pop(src, None)
            self.log(f"Blank page moved to {BLANK_FOLDER_NAME}: {os.path.basename(src)}")
            return
        key = ticket_key(info)
        same = self.index.duplicate_of(key, folder)
        if same:
            # this ticket is already saved (printed again) - the extra file goes to the Recycle Bin
            to_recycle_bin([src])
            self.sizes.pop(src, None)
            self.log(f"Duplicate removed (to the Recycle Bin): {info['name']} SEQ {info['seq'] if info['seq'] is not None else '?'} - "
                     f"already have {os.path.basename(same)}")
            return
        os.makedirs(folder, exist_ok=True)
        n, target = next_document(folder)
        shutil.move(src, target)
        self.sizes.pop(src, None)
        self.index.add(target, key)
        try:
            record_document(n, target)
        except OSError as e:
            self.log(f"Could not write the number to the log: {e}")
        self.log(f"Saved #{n}: {target}"
                 + ("" if key or info is None else " (could not read the header - no duplicate check)"))
        try:
            os.makedirs(all_folder(folder), exist_ok=True)
            dest = all_copy_path(target)
            shutil.copy2(target, dest)
            self.log(f"Copy: {dest}")
        except OSError as e:
            self.log(f"Could not copy to {ALL_FOLDER_NAME}: {e}")


class OcrWorker(threading.Thread):
    """OCR: all new PDFs from 'source' -> PDFs with text in 'destination'."""

    def __init__(self, services, get_paths, log):
        super().__init__(daemon=True)
        self.services = services
        self.get_paths = get_paths
        self.log = log
        self.running = threading.Event()

    def run(self):
        self.services.ready.wait()
        pool = self.services.pool
        inflight = {}      # future -> file name
        sizes = {}
        batch_done = 0
        batch_start = None
        next_scan = 0.0
        while True:
            time.sleep(0.1)
            for fut in [f for f in inflight if f.done()]:
                name = inflight.pop(fut)
                if fut.cancelled():
                    continue
                batch_done += 1
                try:
                    self.log(f"[{batch_done}] {name}: words recognized - {fut.result()}")
                except Exception as e:  # noqa: BLE001
                    self.log(f"WARNING! {name}: {e}")
            if batch_start and not inflight:
                self.log(f"Done: files - {batch_done}, time - {time.time() - batch_start:.1f} s.")
                batch_start, batch_done = None, 0

            if not self.running.is_set():
                for fut in inflight:
                    fut.cancel()  # not yet started ones are cancelled, started ones finish
                continue
            if time.time() < next_scan:
                continue
            next_scan = time.time() + OCR_POLL_SECONDS

            src_dir, dst_dir = self.get_paths()
            try:
                os.makedirs(dst_dir, exist_ok=True)
                names = sorted(n for n in os.listdir(src_dir) if n.lower().endswith(".pdf"))
            except OSError as e:
                self.log(f"No access to the folder: {e}. Stopped.")
                self.running.clear()
                continue
            busy = set(inflight.values())
            for name in names:
                if name in busy or os.path.exists(os.path.join(dst_dir, name)):
                    continue
                src = os.path.join(src_dir, name)
                try:
                    size = os.path.getsize(src)
                except OSError:
                    continue
                if sizes.get(src) != size:  # the file is still being copied - take it on the next round
                    sizes[src] = size
                    continue
                if batch_start is None:
                    batch_start = time.time()
                inflight[pool.submit(_process_ocr_file, src, os.path.join(dst_dir, name))] = name
