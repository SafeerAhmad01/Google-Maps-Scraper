"""
Per-search output folders + compiling every file in a folder into one clean
MAIN leads file.

- Each search gets its own folder under OUTPUT_PATH (named after the query).
- All that search's files (Maps direction files + Web Search files) go there.
- compile_folder() merges them into a single MAIN file that keeps only rows with
  a real email or phone, strips rubbish emails (but keeps role addresses like
  info@ / sales@), dedupes, and puts the key lead columns first.
"""

import os
import re
import glob

import pandas as pd

from settings import OUTPUT_PATH

_INVALID = re.compile(r'[<>:"/\\|?*\n\r\t]+')

# "Rubbish" = clearly not a real business address. Role addresses (info@, sales@,
# contact@, office@ …) are intentionally NOT here — we want to contact those.
_RUBBISH = (
    "sentry", "wixpress", "example.com", "example.org", "example.net",
    "yourdomain", "domain.com", "domain.tld", "placeholder", "googleapis",
    "cloudflare", "w3.org", "schema.org", "wix.com", "sentry.io",
    "your-email", "youremail", "email@example", "name@domain", "user@example",
    "test@test", "@2x", "@3x", "sentry-next",
)
_ASSET = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z.]{2,}$")


def sanitize(name):
    name = _INVALID.sub(" ", str(name)).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "search"


def run_folder(base_query):
    """Create and return output/<sanitized query>/ for this search's files."""
    folder = os.path.join(OUTPUT_PATH, sanitize(base_query))
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        folder = OUTPUT_PATH
    return folder


def clean_email_string(value):
    """Keep all real emails, drop only rubbish/asset/placeholder ones."""
    if value is None or (isinstance(value, float)):
        return ""
    out = []
    for e in re.split(r"[;,]\s*", str(value)):
        e = e.strip().strip(".")
        low = e.lower()
        if not e or low == "nan":
            continue
        if low.endswith(_ASSET):
            continue
        if any(bad in low for bad in _RUBBISH):
            continue
        if not _EMAIL_RE.match(e):
            continue
        if e not in out:
            out.append(e)
    return ", ".join(out)


def _col(df, name):
    """A column as string Series (empty if the column is missing)."""
    if name in df.columns:
        return df[name].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index)


def compile_folder(run_dir, output_format, query):
    """Merge every data file in run_dir into one clean MAIN leads file.

    Returns (path, row_count) or None if there was nothing to compile."""
    files = [f for f in glob.glob(os.path.join(run_dir, "*"))
             if f.lower().endswith((".xlsx", ".csv", ".json"))
             and not os.path.basename(f).upper().startswith("MAIN")]

    frames = []
    for f in files:
        try:
            if f.lower().endswith(".xlsx"):
                frames.append(pd.read_excel(f))
            elif f.lower().endswith(".csv"):
                frames.append(pd.read_csv(f))
            else:
                frames.append(pd.read_json(f))
        except Exception:
            continue

    if not frames:
        return None

    big = pd.concat(frames, ignore_index=True, sort=False)

    # Unify Name (Web Search uses "Business Name", Maps uses "Name")
    name = _col(big, "Name")
    bname = _col(big, "Business Name")
    big["Name"] = [a or b for a, b in zip(name, bname)]

    # Unify + clean Email (Maps uses "email", Web uses "Email")
    combined = (_col(big, "email") + ", " + _col(big, "Email"))
    big["Email"] = combined.apply(clean_email_string)

    # Ensure a Phone column exists
    big["Phone"] = _col(big, "Phone")

    # Keep only contactable leads: has an email OR a phone
    has_email = big["Email"].str.strip() != ""
    has_phone = big["Phone"].str.strip().replace("nan", "") != ""
    leads = big[has_email | has_phone].copy()

    if leads.empty:
        return None

    # Dedupe by business identity, then by email
    ident = [c for c in ("Name", "Address") if c in leads.columns]
    if ident:
        leads = leads.drop_duplicates(subset=ident, keep="first")
    mask = leads["Email"].str.strip() != ""
    dup = leads.duplicated(subset=["Email"], keep="first")
    leads = leads[~(mask & dup)]

    # Put the important lead columns first
    front = [c for c in ("Name", "Email", "Phone", "Phone (Formatted)", "WhatsApp",
                         "Website", "Category", "City", "State", "Zip", "Country",
                         "Facebook", "Instagram", "LinkedIn", "Twitter/X",
                         "Contact Person", "Address")
             if c in leads.columns]
    rest = [c for c in leads.columns if c not in front]
    leads = leads[front + rest]

    ext = {"excel": ".xlsx", "csv": ".csv", "json": ".json"}.get(output_format, ".xlsx")
    path = os.path.join(run_dir, f"MAIN - {sanitize(query)} - LEADS{ext}")
    try:
        if output_format == "csv":
            leads.to_csv(path, index=False)
        elif output_format == "json":
            leads.to_json(path, indent=4, orient="records")
        else:
            leads.to_excel(path, index=False)
    except Exception:
        return None

    return path, len(leads)
