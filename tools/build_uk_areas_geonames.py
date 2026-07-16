"""
Pulls REAL populated-place names for every UK county/borough/council area from
GeoNames' free, official gazetteer dump — a comprehensive alternative/supplement
to scraping Wikipedia place-by-place (tools/build_uk_areas.py).

Why: GeoNames' "admin2" division almost exactly matches our UK "state" list
(county/unitary authority/council area level), and includes ALL populated
places under it with no naming guesswork, no redirects, no per-place network
round trips — one clean dataset covering ~183 of our 216 UK places directly.

Source: https://download.geonames.org/export/dump/{GB.zip,admin2Codes.txt}
License: Creative Commons Attribution 4.0 (free, no API key).

Usage (from the project root, using this project's venv):
    venv\\Scripts\\python.exe tools\\build_uk_areas_geonames.py
"""

import os
import re
import csv
import json
import zipfile
import argparse

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")
_DATASET_PATH = os.path.join(_APP, "data", "countries_states_cities.json")
_NEIGHBORHOODS_PATH = os.path.join(_APP, "data", "neighborhoods.json")
_CACHE_DIR = os.path.join(_HERE, "_geonames_cache")

_GB_ZIP_URL = "https://download.geonames.org/export/dump/GB.zip"
_ADMIN2_URL = "https://download.geonames.org/export/dump/admin2Codes.txt"

_SKIP = {"England", "Scotland", "Wales", "Northern Ireland", "London"}

# These 32 London boroughs were already fixed by the "List of areas of
# London" borough-column split (see build_uk_areas.py's merge history) — no
# need to also process them from GeoNames (Greater London isn't broken down
# by borough in GeoNames' admin2 layer anyway).
_LONDON_BOROUGHS_ALREADY_DONE = {
    "Barking and Dagenham", "Barnet", "Bexley", "Brent", "Bromley", "Camden",
    "Croydon", "Ealing", "Enfield", "Greenwich", "Hackney",
    "Hammersmith and Fulham", "Haringey", "Harrow", "Havering", "Hillingdon",
    "Hounslow", "Islington", "Kensington and Chelsea", "Kingston upon Thames",
    "Lambeth", "Lewisham", "Merton", "Newham", "Redbridge",
    "Richmond upon Thames", "Southwark", "Sutton", "Tower Hamlets",
    "Waltham Forest", "Wandsworth", "Westminster",
}

_PREFIXES = [
    "City and Borough of", "City and County of", "Royal Borough of",
    "Metropolitan Borough of", "County Borough of", "London Borough of",
    "City of", "Borough of", "District of", "Isle of", "County of", "The", "Sir",
]
_SUFFIXES = ["County Borough", "county borough", "City", "Council"]

_MANUAL_ALIASES = {
    "outer hebrides": "eilean siar",
    "armagh, banbridge and craigavon": "armagh city banbridge and craigavon",
}


def _normalize(name):
    name = name.replace(".", "").replace(",", "")
    for p in _PREFIXES:
        name = re.sub(rf"^{p}\s+", "", name, flags=re.IGNORECASE)
    for s in _SUFFIXES:
        name = re.sub(rf"\s+{s}$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\bCounty\b", "", name, flags=re.IGNORECASE)  # "County Durham" <-> "Durham"
    return re.sub(r"\s+", " ", name).strip().lower()


def _download(url, dest):
    if os.path.exists(dest):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)


def _load_admin2():
    path = os.path.join(_CACHE_DIR, "admin2.txt")
    _download(_ADMIN2_URL, path)
    admin2 = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts[0].startswith("GB."):
                admin2[parts[0]] = parts[1]
    return admin2


def _load_gb_places():
    zip_path = os.path.join(_CACHE_DIR, "GB.zip")
    txt_path = os.path.join(_CACHE_DIR, "GB.txt")
    _download(_GB_ZIP_URL, zip_path)
    if not os.path.exists(txt_path):
        with zipfile.ZipFile(zip_path) as z:
            z.extract("GB.txt", _CACHE_DIR)

    places_by_admin2 = {}
    with open(txt_path, encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) < 15:
                continue
            name, feat_class, country, admin1, admin2c = row[1], row[6], row[8], row[10], row[11]
            if feat_class != "P" or country != "GB" or not admin2c:
                continue
            key = f"GB.{admin1}.{admin2c}"
            places_by_admin2.setdefault(key, set()).add(name)
    return places_by_admin2


def build_place_to_areas():
    admin2 = _load_admin2()
    places_by_admin2 = _load_gb_places()

    geoname_by_norm = {}
    for code, name in admin2.items():
        geoname_by_norm.setdefault(_normalize(name), []).append(code)

    with open(_DATASET_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    uk_raw = next((c for c in raw if c.get("name") == "United Kingdom"), None)
    our_places = [s["name"] for s in uk_raw.get("states", [])]

    result = {}
    for place in our_places:
        if place in _SKIP or place in _LONDON_BOROUGHS_ALREADY_DONE:
            continue
        norm = _normalize(place)
        norm = _MANUAL_ALIASES.get(norm, norm)
        codes = geoname_by_norm.get(norm)
        if not codes:
            continue
        areas = set()
        for code in codes:
            areas.update(places_by_admin2.get(code, []))
        if areas:
            result[place] = sorted(areas)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pull UK area lists from GeoNames")
    ap.add_argument("--out", default=os.path.join(_HERE, "uk_areas_geonames.json"))
    args = ap.parse_args()

    mapping = build_place_to_areas()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)

    print(f"Matched {len(mapping)} UK places to GeoNames data.")
    print(f"Total areas: {sum(len(v) for v in mapping.values())}")
    print(f"Saved to {args.out}")
