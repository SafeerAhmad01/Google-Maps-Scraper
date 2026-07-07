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


def scope_choices():
    """Values for the GUI dropdown: simple, all, then every country."""
    return [SIMPLE, ALL] + get_countries()


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
