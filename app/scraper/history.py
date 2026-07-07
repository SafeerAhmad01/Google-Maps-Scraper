"""
Simple persistent run history, shown in the app's History tab.

Every scrape (Google Maps or Web Search) appends one entry to
``<OUTPUT_PATH>/history.json`` so the log survives restarts and works the same
way inside the packaged .exe.
"""

import os
import json
import threading
from datetime import datetime

from settings import OUTPUT_PATH

_lock = threading.Lock()


def _path():
    return os.path.join(OUTPUT_PATH, "history.json")


def load():
    """Return the history list, newest first. Never raises."""
    p = _path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add_entry(query, source, scope, records, output_file, status):
    """Record one run at the top of the history."""
    with _lock:
        try:
            if not os.path.exists(OUTPUT_PATH):
                os.makedirs(OUTPUT_PATH)
            data = load()
            data.insert(0, {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "query": query,
                "source": source,
                "scope": scope or "-",
                "records": records,
                "file": os.path.basename(output_file) if output_file else "-",
                "status": status,
            })
            with open(_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            # History is best-effort; never break a scrape because of it.
            pass
