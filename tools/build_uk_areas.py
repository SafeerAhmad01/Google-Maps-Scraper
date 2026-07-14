"""
Pulls a REAL list of constituent areas/suburbs/districts for big UK cities and
council areas straight from Wikipedia, and merges them into
app/data/neighborhoods.json under "United Kingdom".

Why: the bundled countries_states_cities.json dataset only has ~12 entries for
a city the size of Birmingham, when the real number (per Wikipedia) is 262.
That means location-mode batches barely subdivide big UK cities, so a lot of
each search still gets cut off by Google Maps' ~120-result cap.

How it works, per place name:
  1. Try a short list of likely Wikipedia page titles ("List of areas in X",
     "List of districts in X", etc.) via the MediaWiki API.
  2. If none of those exist, fall back to a full-text search and use the best
     hit IF its title looks like a "list of areas" style page.
  3. Pull that page's wikitext and parse the flat bullet list of wikilinks
     Wikipedia uses for these pages (see sample: "* [[Acocks Green]]",
     "* [[Alum Rock, Birmingham|Alum Rock]]").
  4. Only keep the result if it's a real improvement (more areas than the
     dataset already has, and at least MIN_AREAS long) — otherwise the
     existing data is left alone.

Resumable: saves progress after every place, safe to Ctrl+C and re-run.

Usage (from the project root, using this project's venv):
    venv\\Scripts\\python.exe tools\\build_uk_areas.py
    venv\\Scripts\\python.exe tools\\build_uk_areas.py --only "Bradford,Leeds"
    venv\\Scripts\\python.exe tools\\build_uk_areas.py --min-areas 15
"""

import os
import re
import sys
import json
import time
import argparse

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")

_DATASET_PATH = os.path.join(_APP, "data", "countries_states_cities.json")
_NEIGHBORHOODS_PATH = os.path.join(_APP, "data", "neighborhoods.json")
_PROGRESS_PATH = os.path.join(_HERE, "uk_areas_progress.json")

_API = "https://en.wikipedia.org/w/api.php"
_HEADERS = {"User-Agent": "LeadScrapperDataBuild/1.0 (one-time offline data build)"}

# These show up as top-level UK "states" in the source dataset but are broken
# duplicate/parent entries (0 cities, not a real single place to subdivide).
_SKIP = {"England", "Scotland", "Wales", "Northern Ireland", "London"}

_TITLE_TEMPLATES = [
    "List of areas in {p}",
    "List of areas of {p}",
    "List of districts of {p}",
    "List of districts in {p}",
    "List of localities in {p}",
    "List of wards of {p}",
    "List of wards in {p}",
    "List of places in {p}",
    "List of settlements in {p}",
]

# Many cities (Manchester, Sheffield, Liverpool, ...) don't have a "List of
# areas in X" ARTICLE, but Wikipedia almost always still has a CATEGORY
# grouping the area/suburb articles together — and category membership needs
# no wikitext parsing at all, just the article titles themselves.
_CATEGORY_TEMPLATES = [
    "Category:Areas of {p}",
    "Category:Districts of {p}",
    "Category:Suburbs of {p}",
    "Category:Neighbourhoods of {p}",
    "Category:Neighborhoods of {p}",
    "Category:Places in {p}",
    "Category:Wards of {p}",
]

_CUT_HEADINGS = re.compile(
    r"^==+\s*(References|See also|External links|Notes|Sources|"
    r"Bibliography|Footnotes)\s*==+", re.MULTILINE | re.IGNORECASE)


def _load_uk_places():
    """Every UK "state" name from the raw dataset + its current city count,
    excluding the broken duplicate entries."""
    with open(_DATASET_PATH, encoding="utf-8") as f:
        data = json.load(f)
    uk = next((c for c in data if c.get("name") == "United Kingdom"), None)
    if not uk:
        return []
    out = []
    for s in uk.get("states", []):
        name = s.get("name")
        if name in _SKIP:
            continue
        out.append((name, len(s.get("cities", []))))
    return out


def _api_get(params, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(_API, params=params, headers=_HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(2)
    return None


def _page_wikitext(title):
    data = _api_get({
        "action": "parse", "page": title, "prop": "wikitext",
        "format": "json", "formatversion": 2, "redirects": 1,
    })
    if not data or "error" in data:
        return None
    try:
        return data["parse"]["wikitext"]
    except (KeyError, TypeError):
        return None


def _search_best_title(place):
    """Full-text search fallback when none of the guessed titles exist."""
    data = _api_get({
        "action": "query", "list": "search",
        "srsearch": f"list of areas OR districts OR wards in {place}",
        "srlimit": 5, "format": "json", "formatversion": 2,
    })
    if not data:
        return None
    hits = data.get("query", {}).get("search", [])
    for h in hits:
        title = h.get("title", "")
        if re.search(r"^List of (areas|districts|wards|localities|places|settlements)\b",
                    title, re.IGNORECASE):
            return title
    return None


def _extract_name(item):
    """Pull a clean place name out of one bullet-list item or table cell —
    handles a piped wikilink, a plain wikilink (stripping a disambiguation
    suffix like "(Birmingham)"), or plain text."""
    m = re.search(r"\[\[([^\]|]+)\|([^\]]+)\]\]", item)   # piped link
    if m:
        name = m.group(2).strip()
    else:
        m = re.search(r"\[\[([^\]|]+)\]\]", item)          # plain link
        if m:
            name = re.sub(r"\s*\([^)]*\)\s*$", "", m.group(1)).strip()
        else:
            name = re.sub(r"'''?|\[\[|\]\]", "", item).split("|")[-1].strip()
    return name.strip(" .")


def _valid_name(name):
    return bool(name) and 1 < len(name) < 60 and not name.lower().startswith("http")


def _parse_area_list(wikitext):
    """Pull area names out of a Wikipedia "list of areas/places" page.

    These pages come in two common shapes, so both are handled:
      - a flat bullet list:      "* [[Acocks Green]]"
      - a sortable wikitable:    "| [[Aberford]] || [[Harewood]] || ..."
        (first cell only — the rest are ward/postcode/etc columns)

    Table-cell lines are only read while genuinely INSIDE a "{| ... |}"
    wikitable block — otherwise "| param = value" lines from an unrelated
    {{Infobox ...}} template elsewhere on the page (which use the same
    leading "|") get misread as list entries.

    Stops before References/See also/etc. so citations don't leak in.
    """
    cut = _CUT_HEADINGS.search(wikitext)
    body = wikitext[:cut.start()] if cut else wikitext

    areas = []
    table_depth = 0
    for raw_line in body.splitlines():
        line = raw_line.strip()

        if line.startswith("{|"):
            table_depth += 1
            continue
        if line.startswith("|}"):
            table_depth = max(0, table_depth - 1)
            continue

        if line.startswith("*"):
            item = line.lstrip("*").strip()
        elif table_depth > 0 and line.startswith("|") and not line.startswith(("|-", "|+", "!")):
            item = line.lstrip("|").split("||")[0].strip()
            if not item or "=" in item.split("[[")[0]:
                continue   # a cell-formatting attribute (e.g. class="..."), not content
        else:
            continue

        name = _extract_name(item)
        if _valid_name(name):
            areas.append(name)

    seen, out = set(), []
    for a in areas:
        key = a.lower()
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def _category_members(place):
    """Article titles from a "Category:Areas of X"-style category — the
    fallback for cities (Manchester, Sheffield, Liverpool, ...) that have no
    "List of areas in X" article but do group their suburb articles this way.
    No wikitext parsing needed: category membership IS the area list."""
    for template in _CATEGORY_TEMPLATES:
        cat_title = template.format(p=place)
        data = _api_get({
            "action": "query", "list": "categorymembers",
            "cmtitle": cat_title, "cmlimit": 500, "cmnamespace": 0,
            "format": "json", "formatversion": 2,
        })
        if not data:
            continue
        members = data.get("query", {}).get("categorymembers", [])
        if len(members) >= 5:
            names = []
            for m in members:
                # Category article titles are often disambiguated as
                # "Name, City" or "Name (City)" — neither form has a piped
                # short display like the list-page links do, so strip both
                # disambiguation styles ourselves to get the plain area name.
                name = re.sub(r"\s*\([^)]*\)\s*$", "", m["title"])
                name = re.sub(r",\s*[^,]+$", "", name).strip()
                if _valid_name(name):
                    names.append(name)
            return names
    return []


def fetch_areas(place):
    """Returns a list of area names for `place`, or [] if nothing usable
    was found on Wikipedia. Tries, in order:
      1. Direct "List of areas/districts/wards/... in X" article guesses.
      2. A "Category:Areas of X"-style category (works for cities that group
         suburb articles this way but have no single list article).
      3. A generic full-text search as a last resort.
    Keeps the BEST (longest) result across all tiers tried, rather than
    stopping at the first one that clears a low bar — a category with 20
    members shouldn't beat a list article with 150 entries just because it
    was tried first."""
    best = []

    for template in _TITLE_TEMPLATES:
        title = template.format(p=place)
        wt = _page_wikitext(title)
        if wt:
            areas = _parse_area_list(wt)
            if len(areas) > len(best):
                best = areas
            if len(best) >= 30:   # clearly a good list article — no need to keep guessing titles
                return best

    cat_areas = _category_members(place)
    if len(cat_areas) > len(best):
        best = cat_areas

    if len(best) < 15:
        fallback_title = _search_best_title(place)
        if fallback_title:
            wt = _page_wikitext(fallback_title)
            if wt:
                areas = _parse_area_list(wt)
                if len(areas) > len(best):
                    best = areas

    return best


def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description="Pull real UK area lists from Wikipedia")
    ap.add_argument("--only", default=None,
                    help="comma-separated place names to (re)fetch, skipping the rest")
    ap.add_argument("--min-areas", type=int, default=15,
                    help="only keep a result if it has at least this many areas")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="seconds to wait between Wikipedia requests")
    args = ap.parse_args()

    places = _load_uk_places()
    if args.only:
        wanted = {p.strip().lower() for p in args.only.split(",")}
        places = [(name, n) for name, n in places if name.lower() in wanted]

    progress = _load_json(_PROGRESS_PATH, {})
    total = len(places)
    print(f"{total} UK places to check. Output: {_PROGRESS_PATH}\n"
          f"(Ctrl+C to stop; re-run to resume.)\n")

    for i, (place, current_n) in enumerate(places, start=1):
        if place in progress and not args.only:
            continue   # already fetched in a previous run

        try:
            areas = fetch_areas(place)
        except KeyboardInterrupt:
            _save_json(_PROGRESS_PATH, progress)
            print("\nStopped by user. Progress saved.")
            return
        except Exception as e:
            areas = []
            print(f"[{i}/{total}] {place}: error {e}")

        progress[place] = areas
        _save_json(_PROGRESS_PATH, progress)

        if len(areas) >= args.min_areas and len(areas) > current_n:
            print(f"[{i}/{total}] {place}: {current_n} -> {len(areas)} areas  [improved]")
        else:
            print(f"[{i}/{total}] {place}: {current_n} -> {len(areas)} areas  (kept as-is)")

        time.sleep(args.sleep)

    print(f"\nDone checking all {total} places. Now run:\n"
          f"  venv\\Scripts\\python.exe tools\\merge_uk_areas.py")


if __name__ == "__main__":
    main()
