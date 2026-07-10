"""
Fetch a city's neighborhoods/boroughs from OpenStreetMap.

Two free, no-key services are used:
  1. Nominatim  -> resolve a city name (+ country) to its OSM area id.
  2. Overpass   -> list place=suburb/neighbourhood/borough/quarter inside that area.

This gives real neighborhoods for (almost) any city worldwide, e.g. New York ->
Queens, Brooklyn, Manhattan, Bronx, Harlem, ... Returns [] on any failure so the
caller can fall back to searching the plain city.
"""

import os
import json
import time
import requests

from scraper.resource import resource_path, app_base_dir

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Several mirrors — if one is busy/rate-limiting, we try the next.
_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]
_HEADERS = {"User-Agent": "LeadScrapper/1.0 (lead scraping tool)"}

_PLACE = r'^(suburb|neighbourhood|borough|quarter|city_district|city_block|hamlet)$'


def _area_id(city, country=None):
    params = {"city": city, "format": "json", "limit": 1}
    if country:
        params["country"] = country
    try:
        r = requests.get(_NOMINATIM, params=params, headers=_HEADERS, timeout=25)
        data = r.json()
        if not data:
            return None
        osm_type = data[0].get("osm_type")
        osm_id = int(data[0].get("osm_id"))
        if osm_type == "relation":
            return 3600000000 + osm_id
        if osm_type == "way":
            return 2400000000 + osm_id
        return None  # a node has no area to search inside
    except Exception:
        return None


def _query_area(area, retries=3):
    """List neighborhood-ish places + low-level admin boundaries in an area.

    Retries with backoff across mirrors, and treats non-JSON / error responses
    as failures (rate-limit pages) rather than as 'no neighborhoods'."""
    query = f"""
    [out:json][timeout:90];
    area({area})->.a;
    (
      node(area.a)["place"~"{_PLACE}"]["name"];
      way(area.a)["place"~"{_PLACE}"]["name"];
      relation(area.a)["place"~"{_PLACE}"]["name"];
      relation(area.a)["boundary"="administrative"]["admin_level"~"^(9|10)$"]["name"];
    );
    out tags;
    """
    for attempt in range(retries):
        for url in _OVERPASS_ENDPOINTS:
            try:
                r = requests.post(url, data={"data": query},
                                  headers=_HEADERS, timeout=100)
                if r.status_code != 200:
                    continue
                if "json" not in r.headers.get("Content-Type", "").lower():
                    continue  # got an HTML error / rate-limit page
                elements = r.json().get("elements", [])
            except Exception:
                continue

            names, seen = [], set()
            for el in elements:
                name = el.get("tags", {}).get("name")
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    names.append(name)
            if names:
                return sorted(names)
        # All mirrors failed/empty this round — wait and retry (handles throttling)
        time.sleep(3 * (attempt + 1))
    return []


# If a country-specific match returns fewer than this, also try a global lookup
# and keep whichever gives MORE neighborhoods (so tiny/ambiguous matches don't win).
_ENOUGH = 10


# ── Preloaded (offline) neighborhoods database ──────────────────────────────────
_local_cache = None


def _load_local():
    """Load a preloaded neighborhoods.json if present.

    Format: { "Country": { "City": ["Neighborhood", ...] } }. Looked for next to
    the .exe first (user-updatable), then in the bundled data folder."""
    global _local_cache
    if _local_cache is not None:
        return _local_cache
    for path in (os.path.join(app_base_dir(), "neighborhoods.json"),
                 resource_path(os.path.join("data", "neighborhoods.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                _local_cache = json.load(f)
                return _local_cache
        except Exception:
            continue
    _local_cache = {}
    return _local_cache


def local_lookup(city, country=None):
    """Return preloaded neighborhoods for a city, or None if not in the file."""
    data = _load_local()
    if not data:
        return None
    if country and country in data and city in data[country]:
        return data[country][city]
    cl = city.lower()
    for cities in data.values():
        for cname, hoods in cities.items():
            if cname.lower() == cl:
                return hoods
    return None


def get_neighborhoods(city, country=None):
    """Preloaded file first (instant/offline), otherwise live OpenStreetMap."""
    pre = local_lookup(city, country)
    if pre:
        return pre
    return fetch_live(city, country)


def fetch_live(city, country=None):
    """Live OpenStreetMap lookup (used by the app and by the preloader script).

    1) Look up the city in the chosen country.
    2) If that gives a good number, use it.
    3) Otherwise ALSO do a global (country-free) lookup and keep whichever set
       is bigger. This makes the result consistent and maximizes coverage."""
    best = []

    if country:
        area = _area_id(city, country)
        if area:
            best = _query_area(area)
            if len(best) >= _ENOUGH:
                return best
        time.sleep(1)  # be polite to Nominatim between lookups

    # Global fallback — helps small towns and same-name cities elsewhere.
    area = _area_id(city, None)
    if area:
        alt = _query_area(area)
        if len(alt) > len(best):
            best = alt

    return best
