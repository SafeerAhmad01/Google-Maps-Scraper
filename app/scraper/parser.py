from bs4 import BeautifulSoup
from scraper.error_codes import ERROR_CODES
from scraper.communicator import Communicator
from scraper.datasaver import DataSaver
from scraper.base import Base
from scraper.common import Common
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import requests
import re
import socket

try:
    import dns.resolver as _dns_resolver
except Exception:
    _dns_resolver = None


# ── Contact-enrichment configuration ────────────────────────────────────────────
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Homepage first; extra pages only tried if no email was found yet.
_CONTACT_PATHS = ["", "/contact", "/contact-us", "/about-us"]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"[\+]?[\d][\d\s().\-]{7,16}[\d]")

_FILE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")

_SOCIALS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
}


class Parser(Base):

    def __init__(self, driver) -> None:
        self.driver = driver
        self.finalData = []
        self._mx_cache = {}   # domain -> bool, so we only DNS-check each domain once
        self.comparing_tool_tips = {
            "location": "Copy address",
            "phone": "Copy phone number",
            "website": "Open website",
            "booking": "Open booking link",
        }

    def init_data_saver(self):
        self.data_saver = DataSaver()

    def parse(self):
        """Our function to parse the html"""

        """This block will get element details sheet of a business. 
        Details sheet means that business details card when you click on a business in 
        serach results in google maps"""

        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[role='main']"))
            )
        except:
            pass

        infoSheet = self.driver.execute_script(
            """return document.querySelector("[role='main']")"""
        )

        if infoSheet is None:
            return

        try:
            # Initialize data points
            (
                rating,
                totalReviews,
                address,
                websiteUrl,
                email,
                phone,
                hours,
                category,
                gmapsUrl,
                bookingLink,
                businessStatus,
            ) = (None, None, None, None, None, None, None, None, None, None, None)

            html = infoSheet.get_attribute("outerHTML")
            soup = BeautifulSoup(html, "html.parser")

            # Extract rating
            try:
                rating = soup.find("span", class_="ceNzKf").get("aria-label")
                rating = rating.replace("stars", "").strip()
            except:
                rating = None

            # Extract total reviews
            try:
                totalReviews = list(soup.find("div", class_="F7nice").children)
                totalReviews = totalReviews[1].get_text(strip=True)
            except:
                totalReviews = None

            # Extract name
            try:
                name = soup.select_one(".tAiQdd h1.DUwDvf").text.strip()
            except:
                name = None

            # Extract address, website, phone, and appointment link
            allInfoBars = soup.find_all("button", class_="CsEnBe")
            for infoBar in allInfoBars:
                data_tooltip = infoBar.get("data-tooltip")
                text = infoBar.find("div", class_="rogA2c").text.strip()

                if data_tooltip == self.comparing_tool_tips["location"]:
                    address = text

                elif data_tooltip == self.comparing_tool_tips["phone"]:
                    phone = text.strip()

            # Extract website URL
            try:
                websiteTag = soup.find(
                    "a", {"aria-label": lambda x: x and "Website:" in x}
                )
                if websiteTag:
                    websiteUrl = websiteTag.get("href")

            except:
                websiteUrl = None
            # Enrich contact data from the business website (emails, phones,
            # WhatsApp, social profiles, contact person)
            website_info = {}
            try:
                if websiteUrl:
                    website_info = self.enrich_from_website(websiteUrl)
            except Exception:
                website_info = {}
            email = ", ".join(website_info.get("emails", [])) or None

            # Extract booking link
            try:
                bookingTag = soup.find(
                    "a", {"aria-label": lambda x: x and "Open booking link" in x}
                )
                if bookingTag:
                    bookingLink = bookingTag.get("href")
            except:
                bookingLink = None

            # Extract hours of operation
            try:
                hours = soup.find("div", class_="t39EBf").get_text(strip=True)
            except:
                hours = None

            # Extract category
            try:
                category = soup.find("button", class_="DkEaL").text.strip()
            except:
                category = None

            # Extract Google Maps URL
            try:
                gmapsUrl = self.driver.current_url
            except:
                gmapsUrl = None

            # Extract business status
            try:
                businessStatus = (
                    soup.find("span", class_="ZDu9vd")
                    .findChildren("span", recursive=False)[0]
                    .get_text(strip=True)
                )
            except:
                businessStatus = None

            # Extra formatting / quality fields (nothing is removed — only added)
            addr_parts = self._parse_address(address)
            phone_clean = self._clean_phone(phone)
            email_verified = self._verify_emails(website_info.get("emails", []))

            # Recent review snippets (1–2) for personalizing outreach
            try:
                review_tags = soup.select("span.wiI7pd")
                snippets = [t.get_text(strip=True) for t in review_tags
                            if t.get_text(strip=True)][:2]
                recent_reviews = "  ||  ".join(snippets)
            except Exception:
                recent_reviews = ""

            # ── Green extras (pulled from data already on the page) ──────────────
            # Latitude / Longitude + Plus Code
            latitude = longitude = plusCode = None
            try:
                geo = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", gmapsUrl or "")
                if not geo:
                    geo = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
                                    gmapsUrl or "")
                if geo:
                    latitude, longitude = geo.group(1), geo.group(2)
            except Exception:
                pass
            try:
                pc = soup.find("button", {"data-tooltip": "Copy plus code"})
                if pc:
                    plusCode = pc.find("div", class_="rogA2c").get_text(strip=True)
            except Exception:
                plusCode = None

            # Price level ($, $$, $$$)
            priceLevel = None
            try:
                pl = soup.find("span", attrs={"aria-label":
                               lambda x: x and "Price" in x})
                if pl:
                    priceLevel = pl.get("aria-label", "").strip()
                if not priceLevel:
                    m = re.search(r"([$€£¥]{1,4})",
                                  soup.get_text(" ", strip=True))
                    if m:
                        priceLevel = m.group(1)
            except Exception:
                priceLevel = None

            # Service options / attributes (e.g. Online appointments, On-site)
            serviceOptions = None
            try:
                opts = []
                for el in soup.select('[aria-label*="Service options"] , '
                                      '.LTs0Rc'):
                    t = el.get("aria-label", "") or el.get_text(" ", strip=True)
                    t = t.replace("Service options", "").strip(" :;·")
                    if t and t not in opts:
                        opts.append(t)
                serviceOptions = ", ".join(opts[:8]) or None
            except Exception:
                serviceOptions = None

            # Photos count (best-effort from the header photo button label)
            photosCount = None
            try:
                pb = soup.find("button", {"aria-label":
                               lambda x: x and "photo" in x.lower()})
                if pb:
                    mm = re.search(r"([\d,]+)", pb.get("aria-label", ""))
                    if mm:
                        photosCount = mm.group(1)
            except Exception:
                photosCount = None

            # Claimed / Verified status
            claimed = None
            try:
                page_text = soup.get_text(" ", strip=True)
                if "Claim this business" in page_text:
                    claimed = "No"
                elif soup.find("a", attrs={"aria-label":
                               lambda x: x and "Verified" in x}) or \
                        "Verified listing" in page_text:
                    claimed = "Verified"
                else:
                    claimed = "Claimed"
            except Exception:
                claimed = None

            data = {
                "Category": category,
                "Name": name,
                "Phone": phone,
                "Phone (Formatted)": phone_clean or None,
                "Google Maps URL": gmapsUrl,
                "Website": websiteUrl,
                "email": email,
                "Email Verified?": email_verified or None,
                "Website Phones": ", ".join(website_info.get("phones", [])) or None,
                "WhatsApp": ", ".join(website_info.get("whatsapp", [])) or None,
                "Facebook": website_info.get("facebook") or None,
                "Instagram": website_info.get("instagram") or None,
                "LinkedIn": website_info.get("linkedin") or None,
                "Twitter/X": website_info.get("twitter") or None,
                "Contact Person": website_info.get("contact_person") or None,
                "Business Status": businessStatus,
                "Address": address,
                "City": addr_parts["city"] or None,
                "State": addr_parts["state"] or None,
                "Zip": addr_parts["zip"] or None,
                "Country": addr_parts["country"] or None,
                "Latitude": latitude,
                "Longitude": longitude,
                "Plus Code": plusCode,
                "Price Level": priceLevel,
                "Service Options": serviceOptions,
                "Photos Count": photosCount,
                "Claimed Status": claimed,
                "Total Reviews": totalReviews,
                "Recent Reviews": recent_reviews or None,
                "Booking Links": bookingLink,
                "Rating": rating,
                "Hours": hours,
                "Has Website": "Yes" if websiteUrl else "No",
                "Has Email": "Yes" if email else "No",
                "Has Phone": "Yes" if (phone or phone_clean) else "No",
            }

            self.finalData.append(data)

        except Exception as e:
            Communicator.show_error_message(
                f"Error occurred while parsing a location. Error is: {str(e)}",
                ERROR_CODES["ERR_WHILE_PARSING_DETAILS"],
            )

    # ── Website contact enrichment ──────────────────────────────────────────────
    @staticmethod
    def _deobfuscate(text):
        """Turn 'name [at] domain [dot] com' style emails into real ones."""
        t = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", text, flags=re.I)
        t = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", t, flags=re.I)
        return t

    @staticmethod
    def _clean_emails(raw):
        # Keep ALL real emails. We only drop things that aren't emails at all
        # (image/asset filenames like logo@2x.png) and exact duplicates.
        out = []
        for e in raw:
            e = e.strip().strip(".")
            low = e.lower()
            if low.endswith(_FILE_EXT):
                continue
            if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z.]{2,}$", e):
                continue
            if e not in out:
                out.append(e)
        return out

    def _find_contact_person(self, soup):
        names = []
        for sel in ['[class*="team"]', '[class*="staff"]', '[class*="member"]',
                    '[class*="person"]', '[class*="people"]']:
            for el in soup.select(sel)[:12]:
                for tag in el.find_all(["h2", "h3", "h4", "strong"]):
                    t = tag.get_text(strip=True)
                    if (2 <= len(t.split()) <= 3 and len(t) < 40
                            and re.match(r"^[A-Z][a-zA-Z.\-]+\s+[A-Z]", t)
                            and t not in names):
                        names.append(t)
        return ", ".join(names[:3])

    def enrich_from_website(self, url):
        """Visit a business website and pull as much contact data as possible:
        all emails (incl. mailto: + de-obfuscated), phone numbers (tel:),
        WhatsApp links, social profiles, and a likely contact person.

        Fast-fail: if the homepage doesn't respond, we give up on that site so a
        dead website can't stall the whole scrape."""
        result = {"emails": [], "phones": [], "whatsapp": [], "facebook": "",
                  "instagram": "", "linkedin": "", "twitter": "", "contact_person": ""}
        headers = {"User-Agent": _UA}
        base = url.rstrip("/")
        emails, phones, whats = set(), set(), set()
        home_soup = None

        for i, path in enumerate(_CONTACT_PATHS):
            if Common.close_thread_is_set():
                break
            # Only dig into extra pages if we still haven't found an email.
            if i > 0 and emails:
                break

            target = url if path == "" else base + path
            try:
                resp = requests.get(target, headers=headers, timeout=6, verify=False)
            except Exception:
                if i == 0:
                    break  # homepage dead → stop, don't waste time on more paths
                continue

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            if home_soup is None:
                home_soup = soup

            # Emails: mailto links + raw text + de-obfuscated text
            for a in soup.select('a[href^="mailto:"]'):
                addr = a.get("href", "")[7:].split("?")[0].strip()
                if addr:
                    emails.add(addr)
            emails.update(_EMAIL_RE.findall(html))
            emails.update(_EMAIL_RE.findall(self._deobfuscate(html)))

            # Phones (tel:), WhatsApp, and social links
            for a in soup.find_all("a", href=True):
                href = a["href"]
                low = href.lower()
                if low.startswith("tel:"):
                    phones.add(href[4:].strip())
                if "wa.me" in low or "api.whatsapp.com" in low or "whatsapp.com/send" in low:
                    whats.add(href.split("?")[0])
                for dom, key in _SOCIALS.items():
                    if dom in low and href.startswith("http") and not result[key]:
                        result[key] = href.split("?")[0]

        result["emails"] = self._clean_emails(emails)
        result["phones"] = sorted({re.sub(r"\s+", " ", p).strip()
                                   for p in phones if len(re.sub(r"\D", "", p)) >= 7})
        result["whatsapp"] = sorted(whats)
        if home_soup is not None:
            try:
                result["contact_person"] = self._find_contact_person(home_soup)
            except Exception:
                result["contact_person"] = ""
        return result

    # ── Formatting / quality helpers ────────────────────────────────────────────
    @staticmethod
    def _parse_address(address):
        """Best-effort split of a Google Maps address into City/State/Zip/Country.

        Addresses are free-form and international, so this is heuristic — it fills
        in what it can and leaves the rest blank. The original Address is kept."""
        res = {"city": "", "state": "", "zip": "", "country": ""}
        if not address:
            return res

        parts = [p.strip() for p in address.split(",") if p.strip()]

        # ZIP / postal code (US 5(-4) first, then a generic alnum postcode)
        zm = re.search(r"\b(\d{5}(?:-\d{4})?)\b", address)
        if zm:
            res["zip"] = zm.group(1)

        # US-style state abbreviation sitting right before a ZIP ("NY 10001")
        sm = re.search(r"\b([A-Z]{2})\s+\d{5}", address)
        if sm:
            res["state"] = sm.group(1)

        # Country = last comma-part if it matches a known country name
        if parts:
            last = parts[-1]
            if re.match(r"^[A-Za-z .'\-]+$", last):
                try:
                    from scraper import regions
                    known = {c.lower() for c in regions.get_countries()}
                except Exception:
                    known = set()
                known |= {"usa", "us", "united states", "uk", "u.s.a.", "u.k."}
                if last.lower() in known:
                    res["country"] = last

        # City = the part just before the segment holding the state/zip
        idx = None
        for i, p in enumerate(parts):
            if (res["zip"] and res["zip"] in p) or \
               (res["state"] and re.search(r"\b" + res["state"] + r"\b", p)):
                idx = i
                break
        if idx is not None and idx - 1 >= 0:
            res["city"] = parts[idx - 1]
        elif res["country"] and len(parts) >= 2:
            res["city"] = parts[-2]
        elif len(parts) >= 2:
            res["city"] = parts[-1]

        return res

    @staticmethod
    def _clean_phone(phone):
        """Normalize a phone number to a tidy form (US → '+1 800-294-6643')."""
        if not phone:
            return ""
        raw = re.sub(r"[^\d+]", "", phone)
        m = re.match(r"^\+?1?(\d{10})$", raw)  # US / Canada
        if m:
            d = m.group(1)
            return f"+1 {d[0:3]}-{d[3:6]}-{d[6:]}"
        return re.sub(r"\s+", " ", phone).strip()

    def _domain_accepts_mail(self, domain):
        """True if the domain has an MX record (or at least resolves)."""
        if not domain:
            return False
        if domain in self._mx_cache:
            return self._mx_cache[domain]

        ok = False
        if _dns_resolver is not None:
            try:
                answers = _dns_resolver.resolve(domain, "MX", lifetime=4)
                ok = len(answers) > 0
            except Exception:
                ok = False
        if not ok:
            try:
                socket.gethostbyname(domain)   # domain at least exists
                ok = True
            except Exception:
                ok = False

        self._mx_cache[domain] = ok
        return ok

    def _verify_emails(self, emails):
        """Yes if any email's domain accepts mail, No if none, '' if no emails.
        Does NOT drop any emails — this is just a quality flag."""
        if not emails:
            return ""
        for e in emails:
            domain = e.split("@")[-1].lower().strip()
            if self._domain_accepts_mail(domain):
                return "Yes"
        return "No"

    # find email
    def find_mail(self, url):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            }
            source_code = requests.get(url, headers=headers, timeout=(10))
            curr = source_code.url

            original_curr = curr.rstrip("/")
            plain_text = source_code.text
            match = re.findall(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", plain_text
            )

            if not match:
                urls = [original_curr + "/contact/", original_curr + "/Contact/"]
                for cu in urls:
                    curr = cu
                    source_code = requests.get(cu, headers=headers, timeout=(10))
                    plain_text = source_code.text
                    match = re.findall(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", plain_text
                    )

                    if match:
                        break

            if not match:
                match = re.findall(
                    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", original_curr
                )

            if not match:

                if self.driver is None:
                    Communicator.show_message("Error: WebDriver failed to initialize.")
                    return ""

                self.driver.get(original_curr)
                plain_text = self.driver.page_source
                match = re.findall(
                    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", plain_text
                )

                if not match:
                    urls = [original_curr + "/contact/", original_curr + "/Contact/"]
                    for cu in urls:
                        self.driver.get(cu)
                        plain_text = self.driver.page_source
                        match = re.findall(
                            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                            plain_text,
                        )

                        if match:
                            break

                # self.driver.quit()

            match = [
                email
                for email in set(match)
                if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$", email)
            ]
            email = ", ".join(match)
            return email

        except Exception as e:
            Communicator.show_message(f"Error in find_mail: {e}")
        return ""

    def parse_links(self, allResultsLinks):
        """Parse each result link into self.finalData without saving.

        finalData accumulates across calls so a single Parser instance can
        gather results from several region searches before the caller dedupes
        and saves them once."""
        Communicator.show_message(
            "Scrolling is done. Now going to scrape each location"
        )
        try:
            for resultLink in allResultsLinks:
                if Common.close_thread_is_set():
                    self.driver.quit()
                    return self.finalData

                self.openingurl(url=resultLink)
                self.parse()
        except Exception as e:
            Communicator.show_message(
                f"Error occurred while parsing the locations. Error: {str(e)}"
            )
        return self.finalData

    def main(self, allResultsLinks):
        Communicator.show_message(
            "Scrolling is done. Now going to scrape each location"
        )
        try:
            for resultLink in allResultsLinks:
                if Common.close_thread_is_set():
                    self.driver.quit()
                    return

                self.openingurl(url=resultLink)
                self.parse()

        except Exception as e:
            Communicator.show_message(
                f"Error occurred while parsing the locations. Error: {str(e)}"
            )

        finally:
            self.init_data_saver()
            self.data_saver.save(datalist=self.finalData)
