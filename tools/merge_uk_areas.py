"""
Merges freshly-fetched UK area lists into app/data/neighborhoods.json.

SAFETY: this only ADDS/IMPROVES. It never deletes anything already in
neighborhoods.json (not the "United States" section, not any UK place already
there) — a place is only overwritten if the new list is longer than what's
already saved for it.

Usage (from the project root, using this project's venv):
    venv\\Scripts\\python.exe tools\\merge_uk_areas.py --source path\\to\\new_data.json
    venv\\Scripts\\python.exe tools\\merge_uk_areas.py                 (uses tools\\uk_areas_progress.json)
"""

import os
import sys
import json
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")
_NEIGHBORHOODS_PATH = os.path.join(_APP, "data", "neighborhoods.json")
_DEFAULT_SOURCE = os.path.join(_HERE, "uk_areas_progress.json")


def main():
    ap = argparse.ArgumentParser(description="Merge new UK area lists into neighborhoods.json")
    ap.add_argument("--source", default=_DEFAULT_SOURCE,
                    help="JSON file: { \"Place Name\": [\"Area1\", \"Area2\", ...], ... }")
    ap.add_argument("--min-areas", type=int, default=15,
                    help="only merge a place in if it has at least this many areas")
    args = ap.parse_args()

    with open(args.source, encoding="utf-8") as f:
        new_data = json.load(f)

    if os.path.exists(_NEIGHBORHOODS_PATH):
        with open(_NEIGHBORHOODS_PATH, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {}

    uk = existing.setdefault("United Kingdom", {})   # ADDS a new top-level key; never touches "United States"

    added, improved, skipped = 0, 0, 0
    for place, areas in new_data.items():
        if not areas or len(areas) < args.min_areas:
            skipped += 1
            continue
        current = uk.get(place, [])
        if len(areas) > len(current):
            if place in uk:
                improved += 1
            else:
                added += 1
            uk[place] = sorted(set(areas))
        # else: keep what's already there — never overwrite with something smaller

    tmp = _NEIGHBORHOODS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _NEIGHBORHOODS_PATH)

    print(f"Added {added} new places, improved {improved} existing ones, "
          f"skipped {skipped} (too few areas found).")
    print(f"United Kingdom now has {len(uk)} places in neighborhoods.json.")


if __name__ == "__main__":
    main()
