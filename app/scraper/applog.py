"""
Application logging that works even in the windowed .exe (which has no console).

Everything — Python logging, print()/traceback output (stdout/stderr), uncaught
exceptions, and worker-thread crashes — is written to a log file next to the app.
The GUI's "View Logs" button reads this file, so users can see the real technical
details without running from a terminal.
"""

import os
import sys
import logging
import threading

from scraper.resource import app_base_dir

_LOG_PATH = None
_SETUP_DONE = False


def log_path():
    global _LOG_PATH
    if _LOG_PATH:
        return _LOG_PATH
    logdir = os.path.join(app_base_dir(), "logs")
    try:
        os.makedirs(logdir, exist_ok=True)
    except Exception:
        logdir = app_base_dir()
    _LOG_PATH = os.path.join(logdir, "leadscrapper.log")
    return _LOG_PATH


class _Tee:
    """Write to the original stream (if any) and also to the log file."""

    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, data):
        try:
            if self._stream:
                self._stream.write(data)
        except Exception:
            pass
        try:
            self._fh.write(data)
            self._fh.flush()
        except Exception:
            pass

    def flush(self):
        for s in (self._stream, self._fh):
            try:
                if s:
                    s.flush()
            except Exception:
                pass


def setup():
    """Wire up file logging + stdout/stderr capture + exception hooks. Idempotent."""
    global _SETUP_DONE
    if _SETUP_DONE:
        return log_path()

    path = log_path()

    logging.basicConfig(
        filename=path, filemode="a", level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.info("==================== LeadScrapper started ====================")

    # Tee stdout/stderr so print()s and tracebacks land in the file too.
    try:
        fh = open(path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(getattr(sys, "__stdout__", None), fh)
        sys.stderr = _Tee(getattr(sys, "__stderr__", None), fh)
    except Exception:
        pass

    def _excepthook(exc_type, exc, tb):
        logging.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        try:
            if sys.__excepthook__:
                sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _excepthook

    def _threadhook(args):
        logging.error(
            "Uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    try:
        threading.excepthook = _threadhook
    except Exception:
        pass

    _SETUP_DONE = True
    return path


def read_log(max_bytes=300000):
    """Return the log contents (tail-limited) for display in the GUI."""
    path = log_path()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        if len(data) > max_bytes:
            data = "...(older lines truncated)...\n\n" + data[-max_bytes:]
        return data or "(Log is empty.)"
    except FileNotFoundError:
        return "(No log file yet — it will appear after the first run.)"
    except Exception as e:
        return f"(Could not read log: {e})"
