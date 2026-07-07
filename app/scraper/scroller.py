import time
from scraper.communicator import Communicator
from scraper.common import Common
from bs4 import BeautifulSoup
from selenium.common.exceptions import JavascriptException
from scraper.parser import Parser

class Scroller:

    def __init__(self, driver) -> None:
        self.driver = driver
    
    def __init_parser(self):
        self.parser = Parser(self.driver)


    def start_parsing(self):
        self.__init_parser() # init parser object on fly

        self.parser.main(self.__allResultsLinks)
        

    
    def scroll(self):
        """Scroll the results feed and return the list of result links.

        Returns an empty list when there are no results. Parsing/saving is done
        by the caller so results from several searches can be merged."""

        self.__allResultsLinks = []

        scrollAbleElement = self.driver.execute_script(
                """return document.querySelector("[role='feed']")"""
            )
        if scrollAbleElement is None:
            Communicator.show_message(message="We are sorry but, No results found for your search query on googel maps....")
            return []

        else:
            Communicator.show_message(message="Starting scrolling")

            last_height = 0
            stagnant = 0
            # How many no-growth cycles (~2s each) before we assume the feed is
            # stuck/finished. Without this the loop can hang forever when Google
            # Maps stops loading (the endless spinner).
            MAX_STALL = 8

            while True:
                if Common.close_thread_is_set():
                    self.driver.quit()
                    return self.__allResultsLinks

                """again finding element to avoid StaleElementReferenceException"""
                scrollAbleElement = self.driver.execute_script(
                """return document.querySelector("[role='feed']")"""
            )
                if scrollAbleElement is None:
                    break

                self.driver.execute_script(
                    "arguments[0].scrollTo(0, arguments[0].scrollHeight);",
                    scrollAbleElement,
                )
                time.sleep(2)

                # get new scroll height and compare with last scroll height.
                new_height = self.driver.execute_script(
                    "return arguments[0].scrollHeight", scrollAbleElement
                )

                # Always refresh the links we currently know about, so whenever we
                # break we still have the latest set.
                soup = BeautifulSoup(
                    scrollAbleElement.get_attribute('outerHTML'), 'html.parser')
                self.__allResultsLinks = [a.get('href') for a in
                                          soup.find_all('a', class_='hfpxzc')]

                if new_height == last_height:
                    """checking if we have reached end of the list"""
                    endAlertElement = self.driver.execute_script(
                        'return document.querySelector(".PbZDve ");')

                    if endAlertElement is not None:
                        Communicator.show_message(
                            f"Scrolling done! Total locations found: {len(self.__allResultsLinks)}")
                        break

                    # Not at the end yet — nudge Google Maps to load more.
                    stagnant += 1
                    try:
                        self.driver.execute_script(
                            "array=document.getElementsByClassName('hfpxzc');"
                            "if(array.length){array[array.length-1].click();}"
                        )
                    except JavascriptException:
                        pass

                    if stagnant >= MAX_STALL:
                        Communicator.show_message(
                            f"Feed stopped loading (stuck). Proceeding with "
                            f"{len(self.__allResultsLinks)} results found so far.")
                        break
                else:
                    last_height = new_height
                    stagnant = 0
                    Communicator.show_message(
                        f"Total locations scrolled: {len(self.__allResultsLinks)}")

            return self.__allResultsLinks


                    