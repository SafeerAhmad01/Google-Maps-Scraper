"""
Merges freshly-fetched UK area lists into app/data/neighborhoods.json.

SAFETY: this only ADDS/IMPROVES, never regresses. For each place, the final
list is the UNION of:
  - whatever is already in neighborhoods.json for it (if anything),
  - the original city list from countries_states_cities.json (the dataset the
    app falls back to), and
  - the newly-fetched Wikipedia area list.
A place's area count can only go up or stay the same from this script —
never down. (An earlier version of this script only compared against
neighborhoods.json, which started empty, so a Wikipedia list smaller than the
ORIGINAL dataset's list could still look like an "improvement" and silently
replace a bigger list — e.g. Suffolk had 63 towns in the dataset but only 41
came back from Wikipedia's page for it. This version fixes that by unioning
instead of replacing.)

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
_DATASET_PATH = os.path.join(_APP, "data", "countries_states_cities.json")
_DEFAULT_SOURCE = os.path.join(_HERE, "uk_areas_progress.json")


def _load_original_uk_cities():
    """Place name -> its original city list from the raw dataset (not just a
    count), so we can union against it instead of just comparing lengths."""
    with open(_DATASET_PATH, encoding="utf-8") as f:
        data = json.load(f)
    uk = next((c for c in data if c.get("name") == "United Kingdom"), None)
    if not uk:
        return {}
    return {s["name"]: [c["name"] for c in s.get("cities", [])]
           for s in uk.get("states", [])}


def _dedupe_ci(items):
    """Case-insensitive de-dupe that keeps the first-seen casing."""
    seen, out = set(), []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def main():
    ap = argparse.ArgumentParser(description="Merge new UK area lists into neighborhoods.json")
    ap.add_argument("--source", default=_DEFAULT_SOURCE,
                    help="JSON file: { \"Place Name\": [\"Area1\", \"Area2\", ...], ... }")
    ap.add_argument("--min-areas", type=int, default=15,
                    help="only pull in a Wikipedia list if it has at least this many areas")
    args = ap.parse_args()

    with open(args.source, encoding="utf-8") as f:
        new_data = json.load(f)

    if os.path.exists(_NEIGHBORHOODS_PATH):
        with open(_NEIGHBORHOODS_PATH, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {}

    uk = existing.setdefault("United Kingdom", {})   # ADDS a new top-level key; never touches "United States"
    original_cities = _load_original_uk_cities()

    # Only touch a place if it's already in neighborhoods.json, or Wikipedia
    # actually found a real list for it — never pull in the other UK places
    # that had nothing useful (that's still all 216 in new_data, just with a
    # too-short list), since that would blow up this file with no benefit.
    good_wiki_places = {p for p, a in new_data.items() if len(a) >= args.min_areas}
    places_to_process = set(uk.keys()) | good_wiki_places

    added, improved, skipped = 0, 0, 0
    for place in places_to_process:
        before_n = len(uk.get(place, []))
        combined = _dedupe_ci(uk.get(place, [])
                              + original_cities.get(place, [])
                              + new_data.get(place, []))

        if not combined:
            continue
        if len(combined) > before_n:
            if place in uk:
                improved += 1
            else:
                added += 1
            uk[place] = sorted(combined)
        else:
            skipped += 1

    tmp = _NEIGHBORHOODS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _NEIGHBORHOODS_PATH)

    print(f"Added {added} new places, improved {improved} existing ones "
          f"(union of existing + original dataset + Wikipedia, never smaller).")
    print(f"United Kingdom now has {len(uk)} places in neighborhoods.json.")


if __name__ == "__main__":
    main()
