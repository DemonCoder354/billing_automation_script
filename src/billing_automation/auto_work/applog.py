"""Program output: the main log file (log<MMDDYYYY>[_N].txt) and the stdout tee to the window."""
from __future__ import annotations

import os
import threading
import time

from ..paths import AUTO_WORK_DIR
from .state import console_queue


LOG_DIR = os.path.join(AUTO_WORK_DIR, "logs")
MAIN_LOG_PREFIX = "log"   # log file: log<MMDDYYYY>[_N].txt

# Console output lines that are NOT written to the log (OCR voting output).
# Everything else (all of it is visible in the window anyway) goes to logXXXX.txt as is.
MAIN_LOG_SKIP_MARKERS = (
    "[DATE-DEBUG] All OCR variants",
    "[DATE-DEBUG] Candidates",
    "[NAME-DEBUG] All OCR variants",
    "[NAME-DEBUG] Candidate groups",
)


main_log_path = None      # path to the current log (None = logging disabled)


def _log_stamp():
    """Computer date in MMDDYYYY format."""
    return time.strftime("%m%d%Y")


def _new_log_path(prefix, sep):
    """Creates a NEW empty log file: <prefix><sep><MMDDYYYY>.txt, or with a suffix _2, _3... if it already exists."""
    os.makedirs(LOG_DIR, exist_ok=True)
    base = f"{prefix}{sep}{_log_stamp()}"
    path = os.path.join(LOG_DIR, base + ".txt")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(LOG_DIR, f"{base}_{n}.txt")
    open(path, "a", encoding="utf-8").close()
    return path


def _latest_log_path(prefix):
    """The most recently CREATED log file whose name starts with prefix (or None)."""
    if not os.path.isdir(LOG_DIR):
        return None
    candidates = []
    for fn in os.listdir(LOG_DIR):
        if fn.lower().endswith(".txt") and fn.lower().startswith(prefix.lower()):
            full = os.path.join(LOG_DIR, fn)
            candidates.append((os.path.getctime(full), full))
    return max(candidates)[1] if candidates else None


def _path_from_name(name):
    """Log name from the input field (without extension) -> path in the logs folder. Empty name -> None."""
    name = os.path.basename((name or "").strip())
    if name.lower().endswith(".txt"):
        name = name[:-4]
    if not name:
        return None
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, name + ".txt")


def setup_main_log(name="", new_session=False):
    """
    Chooses the log file:
      - new_session=True -> a NEW file is created;
      - otherwise, if a name (without extension) is given, it is used (the file is created if missing);
      - otherwise the most recently created log is used (a new one is created if there are no logs yet).
    Returns the file path.
    """
    global main_log_path
    if new_session:
        path = _new_log_path(MAIN_LOG_PREFIX, "")
    else:
        path = _path_from_name(name)
        if path is None:
            path = _latest_log_path(MAIN_LOG_PREFIX) or _new_log_path(MAIN_LOG_PREFIX, "")
        elif not os.path.exists(path):
            open(path, "a", encoding="utf-8").close()
    main_log_path = path
    return path


class TeeStdout:
    """
    Intercepts program output (print): sends lines to the program window,
    writes them to the main log (logXXXX.txt, without OCR voting lines) and, if a console
    exists, mirrors them there too. Without a console (pythonw) stream may be None.
    """

    def __init__(self, stream):
        self._stream = stream
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s):
        if self._stream is not None:
            try:
                self._stream.write(s)
            except Exception:
                pass
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._write_line(line)
        return len(s)

    def _write_line(self, line):
        console_queue.put(line)
        path = main_log_path
        if not path:
            return
        if any(marker in line for marker in MAIN_LOG_SKIP_MARKERS):
            return
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
        except Exception:
            pass

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except Exception:
                pass

    def __getattr__(self, name):
        if self._stream is None:
            raise AttributeError(name)
        return getattr(self._stream, name)
