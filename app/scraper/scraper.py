"""
This module contain the code for backend,
that will handle scraping process
"""

from time import sleep
from scraper.base import Base
from scraper.scroller import Scroller
from scraper.parser import Parser
from scraper.datasaver import DataSaver
from scraper import regions, history
from scraper.common import Common
import undetected_chromedriver as uc
from settings import DRIVER_EXECUTABLE_PATH
from scraper.communicator import Communicator


class Backend(Base):


    def __init__(self, searchquery, outputformat,  healdessmode, region_scope=None):
        """
        params:

        search query: it is the value that user will enter in search query entry
        outputformat: output format of file , selected by user
        outputpath: directory path where file will be stored after scraping
        headlessmode: it's value can be 0 and 1, 0 means unchecked box and 1 means checked
        region_scope: None/"None (simple search)" for a single search, a country
            name to search every city in that country, or "All countries" to
            search worldwide. Used to get past Google Maps' ~120-result limit.

        """


        self.searchquery = searchquery  # search query that user will enter
        self.region_scope = region_scope

        # Every individual Google Maps search we will run for this session.
        self.search_tasks = regions.build_search_list(searchquery, region_scope)

        # it is a function used as api for transfering message form this backend to frontend

        self.headlessMode = healdessmode

        self.init_driver()
        self.scroller = Scroller(driver=self.driver)
        self.init_communicator()

    def init_communicator(self):
        Communicator.set_backend_object(self)


    def init_driver(self):
        options = uc.ChromeOptions()
        if self.headlessMode == 1:
                options.headless = True

        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)

        Communicator.show_message("Wait checking for driver...\nIf you don't have webdriver in your machine it will install it")

        try:
            if DRIVER_EXECUTABLE_PATH is not None:
                self.driver = uc.Chrome(
                    driver_executable_path=DRIVER_EXECUTABLE_PATH, options=options)

            else:
                self.driver = uc.Chrome(options=options)

        except NameError:
            self.driver = uc.Chrome(options=options)
        
        
        

        self.driver.set_page_load_timeout(30)
        Communicator.show_message("Opening browser...")
        self.driver.maximize_window()
        self.driver.implicitly_wait(self.timeout)



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

    def mainscraping(self):

        output_file = None
        record_count = 0
        status = "Success"

        try:
            parser = Parser(self.driver)  # one parser accumulates all results
            total = len(self.search_tasks)

            for index, (label, query) in enumerate(self.search_tasks, start=1):
                if Common.close_thread_is_set():
                    break

                if total > 1:
                    Communicator.show_message(
                        f"[Region {index}/{total}] Searching: {label}")

                querywithplus = "+".join(query.split())
                link_of_page = f"https://www.google.com/maps/search/{querywithplus}/"

                self.openingurl(url=link_of_page)
                Communicator.show_message("Working start...")
                sleep(1)

                links = self.scroller.scroll() or []
                if links:
                    parser.parse_links(links)

            # Merge + de-duplicate everything, then save a single file.
            data = self._dedupe(parser.finalData)
            record_count = len(data)
            saver = DataSaver()
            output_file = saver.save(datalist=data)
            if not output_file:
                status = "No data"

        except Exception as e:
            """
            Handling all errors.If any error occurs like user has closed the self.driver and if 'no such window' error occurs
            """
            status = "Error"
            Communicator.show_message(f"Error occurred while scraping. Error: {str(e)}")


        finally:
            try:
                Communicator.show_message("Closing the driver")
                self.driver.close()
                self.driver.quit()
            except:  # if browser is always closed due to error
                pass

            history.add_entry(
                query=self.searchquery,
                source="Google Maps",
                scope=self.region_scope,
                records=record_count,
                output_file=output_file,
                status=status,
            )

            Communicator.end_processing()
            Communicator.show_message("Now you can start another session")



