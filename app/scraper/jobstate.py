"""
Persists the in-progress Location-mode batch to disk so it can be picked back
up later — either via Pause/Resume in the same session, or via the "Resume"
option in the History tab after the app was closed (or crashed) mid-run.

Only one job is tracked at a time (a single checkpoint file). Starting a new
location-mode batch overwrites it.
"""

import json
import os
from datetime import datetime

from settings import OUTPUT_PATH

_PATH = os.path.join(OUTPUT_PATH, ".job_state.json")


def save(query, city_name, output_format, headless, run_web, locations, completed,
         mode="maps", max_results=None):
    """mode: "maps" (Google Maps location batch) or "web" (Web Search location
    batch) — tells the History tab's Resume button which backend to relaunch."""
    try:
        if not os.path.exists(OUTPUT_PATH):
            os.makedirs(OUTPUT_PATH)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "mode": mode,
                "query": query,
                "city_name": city_name,
                "output_format": output_format,
                "headless": headless,
                "run_web": run_web,
                "max_results": max_results,
                "locations": locations,
                "completed": completed,
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }, f, indent=2)
    except Exception:
        pass


def load():
    """Returns the saved job dict, or None if there's nothing left to resume."""
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if len(data.get("completed", [])) >= len(data.get("locations", [])):
            return None
        return data
    except Exception:
        return None


def clear():
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:
        pass
