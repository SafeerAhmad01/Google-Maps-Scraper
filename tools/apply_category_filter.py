"""
Applies the same category-relevance filter the live scraper uses (see
scraper.py's _RELEVANT_CATEGORY_KEYWORDS) to an ALREADY-COMPILED MAIN leads
file — for data scraped before that filter existed, where irrelevant rows
(gift shops, tire shops, churches, ...) never got dropped.

Overwrites the MAIN file in place and regenerates the SALES TEAM file next to
it from the same folder, via leadfiles.compile_folder's existing logic.

Usage (from the project root, using this project's venv):
    venv\\Scripts\\python.exe tools\\apply_category_filter.py "path\\to\\run_dir"
"""

import os
import sys
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")
sys.path.insert(0, _APP)

import pandas as pd  # noqa: E402
import requests  # noqa: E402
from scraper.scraper import _RELEVANT_CATEGORY_KEYWORDS  # noqa: E402
from scraper import leadfiles  # noqa: E402


def website_looks_relevant(url):
    if not url or (isinstance(url, float)):
        return True
    try:
        resp = requests.get(url, timeout=6, verify=False,
                           headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text[:20000].lower()
    except Exception:
        return True
    return any(kw in text for kw in _RELEVANT_CATEGORY_KEYWORDS)


def is_relevant_row(category, website):
    cat = str(category).strip().lower()
    if cat and cat != "nan":
        return any(kw in cat for kw in _RELEVANT_CATEGORY_KEYWORDS)
    return website_looks_relevant(website)


def clean_file(path):
    df = pd.read_excel(path)
    if "Category" not in df.columns:
        print(f"No Category column in {path} — nothing to filter.")
        return len(df), len(df)

    before = len(df)
    mask = df.apply(
        lambda row: is_relevant_row(row.get("Category"), row.get("Website")),
        axis=1)
    dropped = df[~mask]
    kept = df[mask].reset_index(drop=True)

    if not dropped.empty:
        print("Dropped rows (category didn't match):")
        print(dropped[["Name", "Category"]].to_string(index=False))

    kept.to_excel(path, index=False)
    return before, len(kept)


def main():
    ap = argparse.ArgumentParser(description="Apply the category filter to an existing MAIN file")
    ap.add_argument("run_dir", help="folder containing MAIN - ... - LEADS.xlsx")
    args = ap.parse_args()

    main_files = [f for f in os.listdir(args.run_dir)
                 if f.upper().startswith("MAIN") and f.lower().endswith(".xlsx")]
    if not main_files:
        print("No MAIN file found in that folder.")
        return

    for fname in main_files:
        path = os.path.join(args.run_dir, fname)
        before, after = clean_file(path)
        print(f"\n{fname}: {before} -> {after} rows (removed {before - after})")

    # Regenerate the SALES TEAM file from the now-cleaned MAIN data.
    query = main_files[0].replace("MAIN - ", "").replace(" - LEADS.xlsx", "")
    result = leadfiles._save_sales_team_file(
        pd.read_excel(os.path.join(args.run_dir, main_files[0])),
        args.run_dir, "excel", query, ".xlsx")
    if result[0]:
        print(f"\nSALES TEAM file updated: {result[0]} — {result[1]} rows")


if __name__ == "__main__":
    main()
