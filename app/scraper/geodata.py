"""
Offline Country -> State -> City data (from the dr5hn countries+states+cities
dataset). Replaces the flaky live OSM lookups for the location picker.

Loads the slim ``geodata.json`` = { "Country": { "State": ["City", ...] } }.
Looked for next to the .exe first (user-updatable), then the bundled data folder.
"""

import os
import json

from scraper.resource import resource_path, app_base_dir

_cache = None


def _load():
    global _cache
    if _cache is not None:
        return _cache
    for path in (os.path.join(app_base_dir(), "geodata.json"),
                 resource_path(os.path.join("data", "geodata.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                _cache = json.load(f)
                return _cache
        except Exception:
            continue
    _cache = {}
    return _cache


def get_countries():
    return sorted(_load().keys())


def get_states(country):
    return sorted(_load().get(country, {}).keys())


def get_cities(country, state):
    return list(_load().get(country, {}).get(state, []))


def all_cities(country):
    """Every city in a country across all states, de-duplicated + sorted."""
    seen = set()
    out = []
    for cities in _load().get(country, {}).values():
        for c in cities:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return sorted(out)
