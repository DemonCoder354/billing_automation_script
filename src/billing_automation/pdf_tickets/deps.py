"""Installing the optional libraries (pymupdf, winsdk) on first run from source."""
from __future__ import annotations

import subprocess
import sys


def ensure_packages(log):
    """First run: silently installs pymupdf and winsdk (without a console window)."""
    if getattr(sys, "frozen", False):
        return True   # release build: the libraries are bundled into the .exe
    missing = []
    for module, package in (("pymupdf", "pymupdf"), ("winsdk", "winsdk")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if not missing:
        return True
    log(f"First run: installing {', '.join(missing)}, this will take about a minute…")
    python = sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-len("pythonw.exe")] + "python.exe"
    res = subprocess.run([python, "-m", "pip", "install", "--user", *missing],
                         capture_output=True, text=True, creationflags=0x08000000)
    if res.returncode != 0:
        log("Could not install the libraries:\n" + (res.stderr or res.stdout)[-800:])
        return False
    import importlib
    import site
    for d in site.getsitepackages() + [site.getusersitepackages()]:
        site.addsitedir(d)
    importlib.invalidate_caches()
    return True
