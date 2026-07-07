import re
import os
import time
import requests
import pandas as pd
import urllib3
import warnings
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from scraper.communicator import Communicator
from scraper.common import Common
from scraper import history
from settings import OUTPUT_PATH

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore")

BLOCKED = {
    'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com',
    'youtube.com', 'wikipedia.org', 'reddit.com', 'pinterest.com',
    'trustpilot.com', 'glassdoor.com', 'indeed.com', 'amazon.',
    'ebay.', 'google.com', 'google.co.uk', 'bing.com', 'yahoo.com',
}

SESS = requests.Session()
SESS.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Safari/537.36",
})


class WebSearchBackend:

    def __init__(self, query, output_format, max_results, on_done):
        self.query         = query
        self.output_format = output_format
        self.max_results   = max_results
        self.on_done       = on_done
        self.results       = []

    # ── Filter ────────────────────────────────────────────────────────────────
    def _ok(self, url):
        try:
            d = urlparse(url).netloc.lower()
            return url.startswith('http') and not any(b in d for b in BLOCKED)
        except Exception:
            return False

    # ── Search ────────────────────────────────────────────────────────────────
    def _search(self):
        seen = set()
        urls = []

        def add(url):
            u = url.split('?')[0].rstrip('/')
            if u and u not in seen and self._ok(u):
                seen.add(u)
                urls.append(u)

        # --- Google ---
        try:
            from googlesearch import search as gsearch
            Communicator.show_message("Searching Google...")
            for url in gsearch(self.query, num_results=100, lang="en", sleep_interval=2):
                add(url)
            Communicator.show_message(f"Google: {len(urls)} results")
        except Exception as e:
            Communicator.show_message(f"Google unavailable ({e}), using DuckDuckGo only...")

        # --- DuckDuckGo (multiple passes) ---
        variations = [
            self.query,
            self.query + " contact",
            self.query + " email",
            self.query + " phone number",
            self.query + " official website",
            self.query + " services",
            self.query + " about us",
            self.query + " staff team",
            self.query + " reviews",
            self.query + " booking",
            self.query + " appointment",
            '"' + self.query + '"',
            self.query + " 2024",
            self.query + " 2025",
            self.query + " near me",
            self.query + " local",
            self.query + " best",
            self.query + " top",
            self.query + " list",
            self.query + " directory",
        ]

        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            Communicator.show_message(f"Running {len(variations)} DuckDuckGo passes...")
            with DDGS() as ddgs:
                for i, q in enumerate(variations):
                    if Common.close_thread_is_set():
                        break
                    try:
                        hits = list(ddgs.text(q, max_results=500))
                        time.sleep(1.5)
                        before = len(urls)
                        for h in hits:
                            add(h.get('href', ''))
                        Communicator.show_message(
                            f"Pass {i+1}/{len(variations)}: +{len(urls)-before} new  (total: {len(urls)})")
                    except Exception as e:
                        Communicator.show_message(f"Pass {i+1} error: {e}")
        except Exception as e:
            Communicator.show_message(f"DDG error: {e}")

        Communicator.show_message(f"\nFound {len(urls)} unique websites. Scraping all of them...\n")
        return urls

    # ── Extractors ────────────────────────────────────────────────────────────
    def _get_emails(self, text):
        SKIP = {'noreply', 'no-reply', 'example', 'domain', 'test@',
                'sentry', 'youremail', 'placeholder', 'user@', 'name@'}
        raw = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
        return list({e for e in raw
                     if re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}$", e)
                     and not any(s in e.lower() for s in SKIP)})

    def _get_phones(self, text):
        raw = re.findall(r'[\+]?[\d][\d\s\.\-\(\)]{7,18}[\d]', text)
        return list({re.sub(r'\s+', ' ', p).strip() for p in raw
                     if len(re.sub(r'\D', '', p)) >= 7})

    def _get_name(self, soup):
        for prop in ['og:site_name', 'og:title']:
            m = soup.find('meta', property=prop)
            if m and m.get('content', '').strip():
                return m['content'].strip()
        if soup.title:
            t = soup.title.text
            for sep in ['|', '–', '—', '-', '•', ':']:
                t = t.split(sep)[0]
            return t.strip()
        h1 = soup.find('h1')
        return h1.get_text(strip=True) if h1 else None

    def _get_description(self, soup):
        for prop in ['og:description', 'description']:
            tag = (soup.find('meta', property=prop) or
                   soup.find('meta', attrs={'name': prop}))
            if tag and tag.get('content', '').strip():
                return tag['content'].strip()[:400]
        for p in soup.find_all('p'):
            t = p.get_text(strip=True)
            if len(t) > 80:
                return t[:400]
        return None

    def _get_departments(self, soup):
        skip = {'home', 'about', 'contact', 'login', 'sign in', 'blog',
                'news', 'careers', 'privacy', 'terms', 'sitemap', 'faq',
                'search', 'back', 'next', 'previous', 'more', 'menu'}
        depts = []
        for nav in soup.find_all(['nav', 'header']):
            for a in nav.find_all('a'):
                t = a.get_text(strip=True)
                if 2 < len(t) < 40 and t.lower() not in skip and t not in depts:
                    depts.append(t)
        return ', '.join(depts[:10]) if depts else None

    def _get_staff(self, base_url, soup):
        names = []

        def pull(s):
            for sel in ['[class*="team"]', '[class*="staff"]',
                        '[class*="member"]', '[class*="people"]', '[class*="person"]']:
                for el in s.select(sel)[:15]:
                    for tag in el.find_all(['h2', 'h3', 'h4', 'strong']):
                        t = tag.get_text(strip=True)
                        if 2 <= len(t.split()) <= 4 and len(t) < 50 and t not in names:
                            names.append(t)

        pull(soup)
        if not names:
            for path in ['/team', '/our-team', '/staff', '/about-us',
                         '/people', '/meet-the-team', '/about']:
                try:
                    r = SESS.get(base_url.rstrip('/') + path, timeout=8, verify=False)
                    if r.status_code == 200:
                        pull(BeautifulSoup(r.text, 'html.parser'))
                        if names:
                            break
                except Exception:
                    continue

        return ', '.join(names[:6]) if names else None

    def _contact_owner(self, text, target):
        idx = text.find(target)
        if idx == -1:
            return None
        snippet = text[max(0, idx - 300): idx + 300]
        roles = re.findall(
            r'\b(?:Manager|Director|Head|CEO|MD|Agent|Consultant|Executive|'
            r'Coordinator|Advisor|Sales|Support|Admin|HR|Finance|'
            r'Operations|Customer Service|Marketing|Bookings?|'
            r'Reservations?|Enquir(?:y|ies)|General|Reception)\b',
            snippet, re.IGNORECASE)
        names = re.findall(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', snippet)
        parts = []
        if names:
            parts.append(names[0])
        if roles:
            parts.append(roles[0].title())
        return ' — '.join(parts) if parts else None

    # ── Scrape one website ────────────────────────────────────────────────────
    def _scrape(self, url):
        try:
            resp = SESS.get(url, timeout=12, verify=False)
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = resp.text

            name  = self._get_name(soup)
            desc  = self._get_description(soup)
            depts = self._get_departments(soup)
            staff = self._get_staff(url, soup)

            emails = self._get_emails(text)
            if not emails:
                for path in ['/contact', '/contact-us', '/get-in-touch', '/contact/']:
                    try:
                        r2 = SESS.get(url.rstrip('/') + path, timeout=8, verify=False)
                        emails = self._get_emails(r2.text)
                        if emails:
                            text = r2.text
                            break
                    except Exception:
                        continue

            phones = self._get_phones(text)

            return {
                'Business Name':    name,
                'Description':      desc,
                'Services / Depts': depts,
                'Staff':            staff,
                'Website':          url,
                'Email':            ', '.join(emails) if emails else None,
                'Email Belongs To': self._contact_owner(text, emails[0]) if emails else None,
                'Phone':            ', '.join(phones[:3]) if phones else None,
                'Phone Dept/Role':  self._contact_owner(text, phones[0]) if phones else None,
            }
        except Exception:
            return None

    # ── Main ─────────────────────────────────────────────────────────────────
    def run(self):
        try:
            urls  = self._search()
            total = len(urls)
            for i, url in enumerate(urls):
                if Common.close_thread_is_set():
                    break
                Communicator.show_message(f"[{i+1}/{total}]  {url}")
                data = self._scrape(url)
                if data:
                    self.results.append(data)
            self._save()
        finally:
            self.on_done()
            Communicator.show_message("Done — ready for another session.")

    # ── Save ─────────────────────────────────────────────────────────────────
    def _save(self):
        if not self.results:
            Communicator.show_message("No data found to save.")
            history.add_entry(
                query=self.query, source="Web Search", scope=None,
                records=0, output_file=None, status="No data")
            return

        df  = pd.DataFrame(self.results)
        ext = {'excel': '.xlsx', 'csv': '.csv', 'json': '.json'}.get(
            self.output_format, '.xlsx')
        filename = f"{self.query} - WebSearch output"

        if not os.path.exists(OUTPUT_PATH):
            os.makedirs(OUTPUT_PATH)

        path = os.path.join(OUTPUT_PATH, filename + ext)
        if os.path.exists(path):
            idx = 1
            while os.path.exists(os.path.join(OUTPUT_PATH, f"{filename} ({idx}){ext}")):
                idx += 1
            path = os.path.join(OUTPUT_PATH, f"{filename} ({idx}){ext}")

        if self.output_format == 'excel':
            df.to_excel(path, index=False)
        elif self.output_format == 'csv':
            df.to_csv(path, index=False)
        else:
            df.to_json(path, indent=4, orient='records')

        history.add_entry(
            query=self.query, source="Web Search", scope=None,
            records=len(self.results), output_file=path, status="Success")

        Communicator.show_message(
            f"Saved!  {len(self.results)} records  →  {path}\n"
            f"LeadScrapper by Safeer Ahmad — 100% free, no API keys."
        )
