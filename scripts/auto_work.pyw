"""Starts AUTO-WORK from source (double-click: .pyw opens no console window)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from billing_automation.auto_work.app import main  # noqa: E402

if __name__ == "__main__":
    main()
