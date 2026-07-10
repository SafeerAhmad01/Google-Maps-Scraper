"""
Region / city data used to beat Google Maps' ~120-result-per-search limit.

Google stops loading a search feed after roughly 120 places. The only reliable
way past that is to run the same query across many smaller areas and merge the
results. This module loads a worldwide country -> cities list and turns a base
query + a chosen scope into the list of individual searches to run.

The city list is bundled at ``data/regions.json`` but the app will prefer an
editable ``regions.json`` placed next to the executable, so the list can be
extended without rebuilding the .exe.
"""

import os
import json

from scraper.resource import resource_path, app_base_dir

SIMPLE = "None (simple search)"
ALL = "All countries"

_cache = None


def _load():
    global _cache
    if _cache is not None:
        return _cache

    external = os.path.join(app_base_dir(), "regions.json")
    path = external if os.path.exists(external) else resource_path(
        os.path.join("data", "regions.json"))

    try:
        with open(path, encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}
    return _cache


def get_countries():
    """Sorted list of country names available for scoping."""
    return sorted(_load().keys())


def get_cities(country):
    """Sorted list of cities for a country (empty if unknown)."""
    return _load().get(country, [])


def scope_choices():
    """Values for the GUI dropdown: simple, all, then every country."""
    return [SIMPLE, ALL] + get_countries()


DEFAULT_DIRECTIONS = [
    # 16-wind compass rose (each = its own separate file)
    ("North", "North"),
    ("North-North-East", "North North East"),
    ("North-East", "North East"),
    ("East-North-East", "East North East"),
    ("East", "East"),
    ("East-South-East", "East South East"),
    ("South-East", "South East"),
    ("South-South-East", "South South East"),
    ("South", "South"),
    ("South-South-West", "South South West"),
    ("South-West", "South West"),
    ("West-South-West", "West South West"),
    ("West", "West"),
    ("West-North-West", "West North West"),
    ("North-West", "North West"),
    ("North-North-West", "North North West"),
    # extras
    ("Central", "Central"),
    ("Northern", "Northern"),
    ("Southern", "Southern"),
    ("Eastern", "Eastern"),
    ("Western", "Western"),
    ("Coastal", "Coastal"),
    ("Upper", "Upper"),
    ("Lower", "Lower"),
]


def load_directions():
    """Direction options for the GUI as a list of (label, word) tuples.

    Users can add their own by dropping a ``directions.json`` next to the .exe.
    That file is a JSON list; each item is either a plain string (used as both
    label and search word) or an object like {"label": "North-East", "word":
    "North East"}. If the file is missing or invalid, the built-in 8 are used.
    """
    external = os.path.join(app_base_dir(), "directions.json")
    if not os.path.exists(external):
        return list(DEFAULT_DIRECTIONS)

    try:
        with open(external, encoding="utf-8") as f:
            raw = json.load(f)
        result = []
        for item in raw:
            if isinstance(item, str):
                result.append((item, item))
            elif isinstance(item, dict) and item.get("word"):
                result.append((item.get("label", item["word"]), item["word"]))
        return result or list(DEFAULT_DIRECTIONS)
    except Exception:
        return list(DEFAULT_DIRECTIONS)


def build_search_list(base_query, scope):
    """Return a list of (label, full_query) tuples for the chosen scope.

    ``label`` is a short human name shown in the log; ``full_query`` is what
    actually gets searched on Google Maps.
    """
    base = base_query.strip()

    if not scope or scope == SIMPLE:
        return [(base, base)]

    data = _load()

    if scope == ALL:
        tasks = []
        for country, cities in data.items():
            for city in cities:
                tasks.append((f"{city}, {country}",
                              f"{base} in {city}, {country}"))
        return tasks

    return [(f"{city}, {scope}", f"{base} in {city}, {scope}")
            for city in data.get(scope, [])]
