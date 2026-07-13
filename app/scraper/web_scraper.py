import re
import os
import time
import requests
import pandas as pd
import urllib3
import warnings
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
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
    # Big directories/OTAs/gov portals that turn up for almost any "X in
    # <town>" search but are never themselves the local business — keeping
    # them out saves a request and stops them polluting results with generic
    # head-office contact details that have nothing to do with the town.
    'tripadvisor.', 'booking.com', 'agoda.com', 'kayak.', 'skyscanner.',
    'momondo.', 'hotelscombined.', 'hotelplanner.com', 'expedia.',
    'airbnb.', 'rome2rio.com', 'trivago.', 'zenhotels.com', 'kiwi.com',
    'edreams.', 'opodo.', 'stressfreecarrental.com', 'carrentals.',
    'gov.uk', 'vfsglobal.com', 'tlscontact.com', 'travel.state.gov',
    'thomsonlocal.com', 'worldpopulationreview.com', 'cntraveller.com',
    'ezilon.com', 'eventbrite.', 'tiktok.com', 'timeanddate.com',
    'worldtimeserver.com', 'vk.com', 'kinogo', 'wikitravel.org',
}

SESS = requests.Session()
SESS.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Safari/537.36",
})


class WebSearchBackend:

    def __init__(self, query, output_format, max_results, on_done, output_dir=None,
                 global_seen_domains=None):
        self.query         = query
        self.output_format = output_format
        self.max_results   = max_results
        self.on_done       = on_done
        self.output_dir    = output_dir or OUTPUT_PATH
        self.results       = []
        # Domains already scraped in this BATCH (e.g. a previous city in the
        # same Location-mode run). Shared across instances so a chain business
        # found in Houston isn't re-scraped again for Dallas. None = no sharing.
        self.global_seen_domains = global_seen_domains

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
        cap = self.max_results if self.max_results and self.max_results > 0 else None

        def full(_):
            return cap is not None and len(urls) >= cap

        def add(url):
            u = url.split('?')[0].rstrip('/')
            if not u or u in seen or not self._ok(u):
                return
            try:
                domain = urlparse(u).netloc.lower()
            except Exception:
                domain = None
            if (domain and self.global_seen_domains is not None
                    and domain in self.global_seen_domains):
                return  # already scraped this domain earlier in this batch
            seen.add(u)
            urls.append(u)

        # --- Google ---
        try:
            from googlesearch import search as gsearch
            Communicator.show_message("Searching Google...")
            for url in gsearch(self.query, num_results=100, lang="en", sleep_interval=2):
                if full(urls):
                    break
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
            self.query + " head office",
            self.query + " customer service",
            self.query + " services",
            self.query + " about us",
            self.query + " staff team",
            self.query + " reviews",
            self.query + " booking",
            self.query + " appointment",
            self.query + " get a quote",
            '"' + self.query + '"',
            self.query + " near me",
            self.query + " local",
            self.query + " best",
            self.query + " top",
            self.query + " list",
            self.query + " directory",
        ]

        if not full(urls):
            try:
                try:
                    from ddgs import DDGS
                except ImportError:
                    from duckduckgo_search import DDGS

                Communicator.show_message(f"Running {len(variations)} DuckDuckGo passes...")
                with DDGS() as ddgs:
                    for i, q in enumerate(variations):
                        if Common.close_thread_is_set() or full(urls):
                            break
                        try:
                            hits = list(ddgs.text(q, max_results=500))
                            time.sleep(1.5)
                            before = len(urls)
                            for h in hits:
                                if full(urls):
                                    break
                                add(h.get('href', ''))
                            Communicator.show_message(
                                f"Pass {i+1}/{len(variations)}: +{len(urls)-before} new  (total: {len(urls)})")
                        except Exception as e:
                            Communicator.show_message(f"Pass {i+1} error: {e}")
            except Exception as e:
                Communicator.show_message(f"DDG error: {e}")

        if cap:
            urls = urls[:cap]
        Communicator.show_message(f"\nFound {len(urls)} unique websites. Scraping all of them...\n")
        return urls

    # ── Extractors ────────────────────────────────────────────────────────────
    # Elements whose text/attribute content is markup, not something a visitor
    # reads — leaving these in is what let SVG icon path data, base64, and CSS
    # sprite filenames get picked up as fake phone numbers/emails.
    _NON_VISIBLE_TAGS = ('script', 'style', 'svg', 'noscript', 'path', 'img',
                         'picture', 'source', 'template')

    @classmethod
    def _visible_text(cls, soup):
        for tag in soup(cls._NON_VISIBLE_TAGS):
            tag.decompose()
        return soup.get_text(separator=' ')

    def _get_emails(self, text):
        SKIP = {'noreply', 'no-reply', 'example', 'domain', 'test@',
                'sentry', 'youremail', 'placeholder', 'user@', 'name@'}
        ASSET_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico',
                    '.css', '.js', '.json', '.woff', '.woff2')
        raw = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
        return list({e for e in raw
                     if re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}$", e)
                     and not any(s in e.lower() for s in SKIP)
                     and not e.lower().endswith(ASSET_EXT)})

    def _get_phones(self, text):
        raw = re.findall(r'[\+]?[\d][\d\s\.\-\(\)]{7,18}[\d]', text)
        out = set()
        for p in raw:
            p = p.strip()
            digits = re.sub(r'\D', '', p)
            if not (7 <= len(digits) <= 15):
                continue
            # A real phone number, as printed on a page, almost always has a
            # space/dash/dot/parenthesis in it (or a leading +). A bare,
            # unformatted run of 8-19 digits out of context is far more often
            # a timestamp, partner ID, or coordinate than a phone number.
            if p.replace('+', '').isdigit() and not p.startswith('+'):
                continue
            if re.match(r'^(19|20)\d{2}[\-./]\d{2}[\-./]\d{2}$', p):
                continue  # ISO-ish date, not a phone
            out.add(re.sub(r'\s+', ' ', p))
        return list(out)

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

    # Guessed paths tried only if no promising link was found in the nav/footer.
    _FALLBACK_PATHS = (
        '/contact', '/contact/', '/contact-us', '/contact-us/', '/contactus',
        '/contact-us.html', '/contact.html', '/contact.php', '/contactpage',
        '/get-in-touch', '/get-in-touch/', '/getintouch', '/reach-us',
        '/talk-to-us', '/connect', '/enquiry', '/enquiries', '/enquire',
        '/make-an-enquiry', '/request-a-quote', '/quote', '/get-a-quote',
        '/book-now', '/booking', '/reservations', '/appointment',
        '/customer-service', '/support', '/help', '/help-centre',
        '/about', '/about/', '/about-us', '/about-us/', '/aboutus',
        '/who-we-are', '/our-story', '/company', '/company-info',
        '/team', '/our-team', '/meet-the-team', '/meet-our-team', '/staff',
        '/people', '/our-people', '/leadership', '/management',
        '/branches', '/locations', '/find-us', '/our-locations', '/offices',
        '/franchise', '/agents', '/our-agents',
    )
    # Link text/href hints that mark a page as worth checking for contact info.
    _CONTACT_HINTS = (
        'contact', 'about', 'team', 'staff', 'people', 'leadership',
        'management', 'enquir', 'inquir', 'get-in-touch', 'getintouch',
        'reach-us', 'reach us', 'talk-to-us', 'connect', 'support', 'help',
        'reservations', 'booking', 'book now', 'appointment', 'quote',
        'branch', 'location', 'find us', 'find-us', 'office', 'who we are',
        'our story', 'meet the team', 'meet our team', 'company', 'franchise',
        'agents', 'customer service', 'complaints', 'feedback',
    )

    def _candidate_pages(self, base_url, soup):
        """Same-site links whose href/text look like a contact/about/team page
        — checked before falling back to guessed paths, since a real link the
        site itself points to is far more likely to be right."""
        domain = urlparse(base_url).netloc.lower()
        seen, out = set(), []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                continue
            try:
                full = urljoin(base_url, href).split('#')[0].rstrip('/')
                if urlparse(full).netloc.lower() != domain:
                    continue
            except Exception:
                continue
            if not full or full == base_url.rstrip('/') or full in seen:
                continue
            hay = (href + ' ' + a.get_text(strip=True)).lower()
            if any(h in hay for h in self._CONTACT_HINTS):
                seen.add(full)
                out.append(full)
        return out[:5]

    # ── Scrape one website ────────────────────────────────────────────────────
    def _scrape(self, url):
        try:
            resp = SESS.get(url, timeout=12, verify=False)
            soup = BeautifulSoup(resp.text, 'html.parser')

            name  = self._get_name(soup)
            desc  = self._get_description(soup)
            depts = self._get_departments(soup)
            staff = self._get_staff(url, soup)
            more_pages = self._candidate_pages(url, soup)

            text   = self._visible_text(soup)
            emails = self._get_emails(text)

            # Keep looking — real links found on the page first, then guessed
            # common paths — until an email turns up. Capped so one dead site
            # (no contact info anywhere) can't stall the whole batch.
            MAX_EXTRA_PAGES = 10
            tried = {url.rstrip('/')}
            candidates = (list(more_pages)
                         + [url.rstrip('/') + p for p in self._FALLBACK_PATHS])
            checked = 0
            for page in candidates:
                if emails or checked >= MAX_EXTRA_PAGES or page in tried:
                    continue
                checked += 1
                tried.add(page)
                try:
                    r2 = SESS.get(page, timeout=8, verify=False)
                    s2 = BeautifulSoup(r2.text, 'html.parser')
                    t2 = self._visible_text(s2)
                    found = self._get_emails(t2)
                    if found:
                        emails, text = found, t2
                except Exception:
                    continue

            phones = self._get_phones(text)

            if not name or (not emails and not phones):
                return None

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
                if self.global_seen_domains is not None:
                    try:
                        self.global_seen_domains.add(urlparse(url).netloc.lower())
                    except Exception:
                        pass
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

        out_dir = self.output_dir
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        path = os.path.join(out_dir, filename + ext)
        if os.path.exists(path):
            idx = 1
            while os.path.exists(os.path.join(out_dir, f"{filename} ({idx}){ext}")):
                idx += 1
            path = os.path.join(out_dir, f"{filename} ({idx}){ext}")

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
