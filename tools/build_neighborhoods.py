"""
Preload a WORLDWIDE neighborhoods database from OpenStreetMap.

Why: the app can fetch a city's neighborhoods live from OSM, but doing it live
is slow and OSM rate-limits. This script crawls every city in regions.json ONCE
and writes neighborhoods.json, so the app then reads it instantly & offline.

Where the data comes from: OpenStreetMap (the same source the app uses live) —
place=suburb/neighbourhood/borough/quarter + low-level admin boundaries. Nothing
is hand-typed; it's all pulled from OSM.

Output format:
    { "United States": { "New York": ["Queens", ...], ... }, ... }

It is RESUMABLE: re-run it any time and it skips cities already saved. It saves
after every city, so you can stop (Ctrl+C) and continue later.

Usage (from the project root, using this project's venv):
    venv\\Scripts\\python.exe tools\\build_neighborhoods.py
    venv\\Scripts\\python.exe tools\\build_neighborhoods.py --country "United Kingdom"
    venv\\Scripts\\python.exe tools\\build_neighborhoods.py --limit 50   (max cities per country)
    venv\\Scripts\\python.exe tools\\build_neighborhoods.py --min 3      (skip cities with <3 hoods)

When done, drop the resulting neighborhoods.json next to LeadScrapper.exe
(or into app/data/) and the app will use it automatically.
"""

import os
import sys
import json
import time
import argparse

# Make the app's packages importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")
sys.path.insert(0, _APP)

from scraper import osm  # noqa: E402


def _load_regions():
    path = os.path.join(_APP, "data", "regions.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_existing(out_path):
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(out_path, data):
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out_path)


def main():
    ap = argparse.ArgumentParser(description="Preload world neighborhoods from OSM")
    ap.add_argument("--out", default=os.path.join(_APP, "data", "neighborhoods.json"),
                    help="output json path")
    ap.add_argument("--country", default=None,
                    help="only this country (default: whole world)")
    ap.add_argument("--limit", type=int, default=0,
                    help="max cities per country (0 = all)")
    ap.add_argument("--min", type=int, default=1,
                    help="skip cities with fewer than N neighborhoods")
    ap.add_argument("--sleep", type=float, default=1.0,
                    help="seconds to wait between cities (be polite to OSM)")
    args = ap.parse_args()

    regions = _load_regions()
    data = _load_existing(args.out)

    countries = [args.country] if args.country else sorted(regions.keys())
    total_cities = sum(len(regions.get(c, [])) for c in countries)
    print(f"Crawling {len(countries)} countr(y/ies), ~{total_cities} cities. "
          f"Output: {args.out}\n(Ctrl+C to stop; resumable.)\n")

    done = 0
    found = 0
    for country in countries:
        cities = regions.get(country, [])
        if args.limit:
            cities = cities[:args.limit]
        data.setdefault(country, {})

        for city in cities:
            done += 1
            if city in data[country]:      # resume: already have it
                continue
            try:
                hoods = osm.fetch_live(city, country)
            except KeyboardInterrupt:
                _save(args.out, data)
                print("\nStopped by user. Progress saved.")
                return
            except Exception as e:
                hoods = []
                print(f"  ! {city}, {country}: error {e}")

            if len(hoods) >= args.min:
                data[country][city] = hoods
                found += 1
                _save(args.out, data)      # save after every hit (resumable)
                print(f"[{done}/{total_cities}] {city}, {country}: {len(hoods)}")
            else:
                print(f"[{done}/{total_cities}] {city}, {country}: -")

            time.sleep(args.sleep)

    _save(args.out, data)
    print(f"\nDone. Cities with neighborhoods: {found}. Saved to {args.out}")


if __name__ == "__main__":
    main()
