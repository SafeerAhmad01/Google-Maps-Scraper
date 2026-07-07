"""
These are settings of the scraper. To see thier details, please visit:
https://zubdata.com/docs/google-maps-scraper/getting-started/settings/
"""


OUTPUT_PATH = "output/"

# Set to None so undetected-chromedriver auto-downloads the driver that matches
# the Chrome installed on whatever machine runs the app. This is required for the
# packaged .exe to work on other computers. If you want to pin a local driver for
# development, set an absolute path here instead.
DRIVER_EXECUTABLE_PATH = None