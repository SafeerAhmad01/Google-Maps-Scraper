"""
This module contain the code for saving the scraped data
"""


import pandas as pd
from scraper.communicator import Communicator
from settings import OUTPUT_PATH
import os
from scraper.error_codes import ERROR_CODES

class DataSaver:
    def __init__(self) -> None:
        self.outputFormat = Communicator.get_output_format()

    def save(self, datalist, output_dir=None):
        """
        This function will save the data that has been scrapped.
        This can be call if any error occurs while scraping , or if scraping is done successfully.
        In both cases we have to save the scraped data.

        output_dir: folder to save into (defaults to OUTPUT_PATH). Used so all
        files from one search land in that search's own folder.
        """

        base_dir = output_dir or OUTPUT_PATH

        if len(datalist) > 0:
            Communicator.show_message("Saving the scraped data")

            dataFrame = pd.DataFrame(datalist)
            totalRecords = dataFrame.shape[0]

            searchQuery = Communicator.get_search_query()
            filename = f"{searchQuery} - GMS output"

            if self.outputFormat == "excel":
                extension = ".xlsx"
            elif self.outputFormat == "csv":
                extension = ".csv"
            elif self.outputFormat == "json":
                extension = ".json"

             # Create the output directory if it does not exist
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)
            joinedPath = os.path.join(base_dir, filename + extension)

            if os.path.exists(joinedPath):
                index = 1
                while True:
                    filename = f"{searchQuery} - GMS output ({index})"

                    joinedPath = os.path.join(base_dir, filename + extension)

                    if os.path.exists(joinedPath):
                        index += 1

                    else:
                        break
            if self.outputFormat == "excel":
                dataFrame.to_excel(joinedPath, index=False)
            elif self.outputFormat == "csv":
                dataFrame.to_csv(joinedPath, index=False)

            elif self.outputFormat == "json":
                dataFrame.to_json(joinedPath, indent=4, orient="records")

            Communicator.show_message(f"Done! Scraped data saved successfully. Total records: {totalRecords}. LeadScrapper by Safeer Ahmad.")

            return joinedPath

        else:
            Communicator.show_error_message("Oops! Could not scrape the data because you did not scrape any record.",{ERROR_CODES['NO_RECORD_TO_SAVE']})
            return None


