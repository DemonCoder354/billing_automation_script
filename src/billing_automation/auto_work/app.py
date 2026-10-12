"""AUTO-WORK entry point."""
from __future__ import annotations

import multiprocessing
import os
import sys
import traceback

from ..paths import AUTO_WORK_DIR


def main() -> None:
    multiprocessing.freeze_support()
    os.makedirs(AUTO_WORK_DIR, exist_ok=True)
    from .applog import TeeStdout
    sys.stdout = TeeStdout(sys.stdout)   # output -> program window + main log
    sys.stderr = TeeStdout(sys.stderr)   # errors are shown in the window too (there is no console)
    try:
        from ..tesseract import configure_pytesseract
        from .gui import AutoWorkApp
        from .state import register_hotkeys
        configure_pytesseract()
        register_hotkeys()
        AutoWorkApp().run()
    except Exception:
        with open(os.path.join(AUTO_WORK_DIR, "crash.log"), "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
