"""
Helpers for locating bundled resources both in normal (source) runs and inside
a PyInstaller one-file .exe (where files are unpacked to a temp dir at runtime).
"""

import os
import sys


def resource_path(relative):
    """Absolute path to a bundled resource.

    In a PyInstaller build the files added via the spec live under sys._MEIPASS.
    In a normal run they live inside the ``app`` directory (the parent of the
    ``scraper`` package), so we anchor relative paths there.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)

    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../app
    return os.path.join(app_dir, relative)


def app_base_dir():
    """Directory the user thinks the app lives in.

    For a frozen .exe that's the folder containing the .exe (so files the user
    drops next to it are found); otherwise the current working directory.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()
