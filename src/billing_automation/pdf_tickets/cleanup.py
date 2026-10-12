"""Collecting the files to clean up before a new week."""
from __future__ import annotations

import os


def collect_files(root):
    """{folder: [files]} for all folders inside root (root itself included)."""
    found = {}
    for dirpath, _, filenames in os.walk(root):
        if filenames:
            found[dirpath] = [os.path.join(dirpath, n) for n in filenames]
    return found
