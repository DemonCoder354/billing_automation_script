"""PDF Tickets entry point."""
from __future__ import annotations

import multiprocessing


def main() -> None:
    multiprocessing.freeze_support()   # the OCR process pool must work in the .exe build
    from .gui.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
