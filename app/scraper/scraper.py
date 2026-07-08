"""
This module contain the code for backend,
that will handle scraping process
"""

import os
import re
from time import sleep
from scraper.base import Base
from scraper.scroller import Scroller
from scraper.parser import Parser
from scraper.datasaver import DataSaver
from scraper import regions, history
from scraper.common import Common
import undetected_chromedriver as uc
from settings import DRIVER_EXECUTABLE_PATH


def _chrome_major_version():
    """Best-effort detection of the installed Chrome major version on Windows.

    undetected-chromedriver otherwise grabs the latest driver, which fails with
    'This version of ChromeDriver only supports Chrome version X' when the user's
    Chrome is a version behind. Passing version_main makes it fetch the match.
    Returns an int major version, or None if it can't be determined.
    """
    # 1) Registry (fast, no file access)
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                version, _ = winreg.QueryValueEx(key, "version")
                winreg.CloseKey(key)
                if version:
                    return int(version.split(".")[0])
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # 2) The Chrome install dir contains a subfolder named after the version
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application"),
    ]
    for appdir in candidates:
        try:
            for name in os.listdir(appdir):
                m = re.match(r"^(\d+)\.\d+\.\d+\.\d+$", name)
                if m:
                    return int(m.group(1))
        except Exception:
            continue

    return None
from scraper.communicator import Communicator


class Backend(Base):


    def __init__(self, searchquery, outputformat,  healdessmode, region_scope=None,
                 directions=None):
        """
        params:

        search query: it is the value that user will enter in search query entry
        outputformat: output format of file , selected by user
        outputpath: directory path where file will be stored after scraping
        headlessmode: it's value can be 0 and 1, 0 means unchecked box and 1 means checked
        region_scope: None/"None (simple search)" for a single search, a country
            name to search every city in that country, or "All countries" to
            search worldwide. Used to get past Google Maps' ~120-result limit.
        directions: optional list of direction words (e.g. ["North", "South West"]).
            When provided, each direction is run as its own search and saved to its
            own separate file, and region_scope is ignored.

        """


        self.searchquery = searchquery  # search query that user will enter
        self.base_query = searchquery   # kept intact; searchquery may change per direction
        self.region_scope = region_scope
        self.directions = directions or []

        # Region-scope searches (only used when no directions are selected).
        self.search_tasks = ([] if self.directions
                             else regions.build_search_list(searchquery, region_scope))

        # it is a function used as api for transfering message form this backend to frontend

        self.headlessMode = healdessmode

        self.init_driver()
        self.scroller = Scroller(driver=self.driver)
        self.init_communicator()

    def init_communicator(self):
        Communicator.set_backend_object(self)


    def init_driver(self, quiet=False):
        options = uc.ChromeOptions()
        if self.headlessMode == 1:
                options.headless = True

        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)

        if not quiet:
            Communicator.show_message("Wait checking for driver...\nIf you don't have webdriver in your machine it will install it")

        major = _chrome_major_version()
        if major and not quiet:
            Communicator.show_message(
                f"Detected Chrome version {major}. Getting the matching driver...")

        kwargs = {"options": options}
        if major:
            kwargs["version_main"] = major
        if DRIVER_EXECUTABLE_PATH:
            kwargs["driver_executable_path"] = DRIVER_EXECUTABLE_PATH

        try:
            self.driver = uc.Chrome(**kwargs)
        except Exception as first_error:
            # Retry once letting undetected-chromedriver pick the driver itself.
            Communicator.show_message(
                f"First driver attempt failed ({first_error}). Retrying...")
            try:
                self.driver = uc.Chrome(options=options)
            except Exception as second_error:
                Communicator.show_message(
                    "Could not start Chrome. Make sure Google Chrome is installed "
                    "and up to date, then try again. "
                    f"Details: {second_error}")
                raise

        self.driver.set_page_load_timeout(30)
        self.driver.set_script_timeout(30)
        if not quiet:
            Communicator.show_message("Opening browser...")
        self.driver.maximize_window()
        self.driver.implicitly_wait(self.timeout)

    def _restart_driver(self):
        """Close the current Chrome and open a brand-new session.

        Google throttles a session after several rapid searches (results stop
        loading past ~20 and scripts start timing out). A fresh browser per file
        avoids that degraded/blocked state."""
        try:
            if getattr(self, "driver", None):
                self.driver.quit()
        except Exception:
            pass
        Communicator.show_message("Opening a fresh Chrome session...")
        self.init_driver(quiet=True)
        self.scroller = Scroller(driver=self.driver)



    @staticmethod
    def _dedupe(rows):
        """Remove duplicate businesses (same name + address) collected across
        the different region searches."""
        seen = set()
        unique = []
        for row in rows:
            name = (row.get("Name") or "").strip().lower()
            address = (row.get("Address") or "").strip().lower()
            if not name and not address:
                unique.append(row)  # no identity to compare on, keep it
                continue
            key = (name, address)
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    def _scrape_query(self, query, parser):
        """Open a single Google Maps search and parse its results into parser.

        Google Maps can return up to ~120 results. If a search comes back with
        very few (< 50), the feed most likely got stuck, so we retry it once.
        Anything >= 50 (or a second attempt) is accepted as-is."""
        querywithplus = "+".join(query.split())
        link_of_page = f"https://www.google.com/maps/search/{querywithplus}/"

        self.openingurl(url=link_of_page)
        Communicator.show_message("Working start...")
        sleep(1)

        links = self.scroller.scroll() or []

        if len(links) < 50 and not Common.close_thread_is_set():
            Communicator.show_message(
                f"Only {len(links)} results (under 50) — retrying this search once...")
            self.openingurl(url=link_of_page)
            sleep(2)
            retry_links = self.scroller.scroll() or []
            if len(retry_links) > len(links):
                links = retry_links
            Communicator.show_message(
                f"After retry: {len(links)} results. Proceeding.")

        if links:
            parser.parse_links(links)

    def mainscraping(self):
        try:
            if self.directions:
                self._run_direction_mode()
            else:
                self._run_scope_mode()

        except Exception as e:
            """
            Handling all errors.If any error occurs like user has closed the self.driver and if 'no such window' error occurs
            """
            Communicator.show_message(f"Error occurred while scraping. Error: {str(e)}")

        finally:
            try:
                Communicator.show_message("Closing the driver")
                self.driver.close()
                self.driver.quit()
            except:  # if browser is always closed due to error
                pass

            Communicator.end_processing()
            Communicator.show_message("Now you can start another session")

    def _run_scope_mode(self):
        """None / country / All-countries: merge everything into a single file."""
        output_file = None
        record_count = 0
        status = "Success"

        try:
            parser = Parser(self.driver)  # one parser accumulates all results
            total = len(self.search_tasks)
            Communicator.set_progress(0, total, "Starting search...")

            for index, (label, query) in enumerate(self.search_tasks, start=1):
                if Common.close_thread_is_set():
                    break

                if total > 1:
                    Communicator.show_message(
                        f"[Area {index}/{total}] Searching: {label}")
                Communicator.set_progress(index - 1, total,
                                          f"Searching {label}")

                self._scrape_query(query, parser)
                Communicator.set_progress(index, total, f"Searched {label}")

            # Merge + de-duplicate everything, then save a single file.
            data = self._dedupe(parser.finalData)
            record_count = len(data)
            Communicator.show_message(
                f"Creating 1 file with {record_count} merged records...")
            output_file = DataSaver().save(datalist=data)
            if output_file:
                Communicator.show_message(
                    f"✔ File created: {os.path.basename(output_file)}")
            else:
                status = "No data"
            Communicator.set_progress(total, total, "Done")

        except Exception as e:
            status = "Error"
            Communicator.show_message(f"Error occurred while scraping. Error: {str(e)}")

        history.add_entry(
            query=self.searchquery,
            source="Google Maps",
            scope=self.region_scope,
            records=record_count,
            output_file=output_file,
            status=status,
        )

    def _run_direction_mode(self):
        """Run each selected direction as its own search and save a SEPARATE file."""
        total = len(self.directions)
        Communicator.set_progress(0, total,
                                  f"Making {total} files (one per direction)...")

        for index, word in enumerate(self.directions, start=1):
            if Common.close_thread_is_set():
                break

            # Fresh Chrome session for every file (except the first, which the
            # constructor already opened) so Google doesn't throttle us.
            if index > 1:
                self._restart_driver()
                sleep(2)

            direction_query = f"{self.base_query} {word}".strip()
            # DataSaver + history use self.searchquery for the file name, so point it
            # at this direction to get one distinct file per direction.
            self.searchquery = direction_query

            Communicator.set_progress(
                index - 1, total,
                f"Making file {index}/{total}:  {direction_query} - GMS output")
            Communicator.show_message(
                f"[File {index}/{total}]  Now creating:  {direction_query} - GMS output")

            output_file = None
            record_count = 0
            status = "Success"

            try:
                parser = Parser(self.driver)  # fresh parser => separate results/file
                self._scrape_query(direction_query, parser)

                data = self._dedupe(parser.finalData)
                record_count = len(data)
                output_file = DataSaver().save(datalist=data)
                if output_file:
                    Communicator.show_message(
                        f"✔ File {index}/{total} created: {os.path.basename(output_file)}")
                else:
                    status = "No data"

            except Exception as e:
                status = "Error"
                Communicator.show_message(
                    f"Error while scraping direction '{word}': {str(e)}")

            Communicator.set_progress(index, total,
                                      f"Finished {index}/{total} files")

            history.add_entry(
                query=direction_query,
                source="Google Maps",
                scope=f"Direction: {word}",
                records=record_count,
                output_file=output_file,
                status=status,
            )



