"""
Pulls real area/community lists for the UAE's 7 emirates from Wikipedia and
merges them into app/data/geodata.json (the file the app's picker actually
reads) — same approach and same safety guarantees as build_uk_areas.py:
union-merge only, nothing is ever removed or shrunk.

Usage (from the project root, using this project's venv):
    venv\\Scripts\\python.exe tools\\build_uae_areas.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_uk_areas import fetch_areas  # noqa: E402 (reuses the same Wikipedia fetch logic)

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")
_GEODATA_PATH = os.path.join(_APP, "data", "geodata.json")

_EMIRATES = ["Abu Dhabi", "Ajman", "Dubai", "Fujairah",
            "Ras Al Khaimah", "Sharjah", "Umm Al Quwain"]


def main():
    with open(_GEODATA_PATH, encoding="utf-8") as f:
        geo = json.load(f)
    uae = geo.setdefault("United Arab Emirates", {})

    for emirate in _EMIRATES:
        print(f"Checking Wikipedia for {emirate}...")
        wiki_areas = fetch_areas(emirate)
        before = len(uae.get(emirate, []))
        combined = sorted(set(uae.get(emirate, [])) | set(wiki_areas))
        after = len(combined)
        uae[emirate] = combined
        print(f"  {emirate}: {before} -> {after} areas "
             f"(Wikipedia found {len(wiki_areas)})")

    with open(_GEODATA_PATH, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, indent=1)

    print("\nSaved. Final UAE state:")
    for emirate in _EMIRATES:
        print(f"  {emirate}: {len(uae[emirate])} areas")


if __name__ == "__main__":
    main()
