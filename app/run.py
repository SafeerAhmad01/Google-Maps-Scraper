from scraper import applog
from scraper.frontend import Frontend


def main():
    applog.setup()   # capture logs/tracebacks to a file (works in the .exe too)

    app = Frontend()
    app.root.protocol("WM_DELETE_WINDOW", app.closingbrowser)
    app.root.mainloop()


if __name__ == "__main__":
    main()
