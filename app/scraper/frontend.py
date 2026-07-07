"""
This module contain the code for frontend
"""

from scraper.communicator import Communicator
import tkinter as tk
from tkinter import ttk, WORD
from scraper.scraper import Backend
from scraper.web_scraper import WebSearchBackend
from scraper.common import Common
from scraper import regions, history
from scraper.resource import resource_path
import threading

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = "#0d1117"
GLASS     = "#161b22"
GLASS2    = "#1c2128"
BORDER    = "#21262d"
BORDER2   = "#30363d"
ACCENT    = "#58a6ff"
ACCENT2   = "#1f4068"
TEXT      = "#e6edf3"
TEXT_DIM  = "#6e7681"
BTN_GRN   = "#238636"
BTN_HOV   = "#2ea043"
BTN_DIS   = "#14532d"
INPUT_BG  = "#0d1117"
SUCCESS   = "#3fb950"
WARNING   = "#d29922"


class Frontend:
    def __init__(self):
        self.root = tk.Tk()
        try:
            icon = tk.PhotoImage(file=resource_path("images/GMS.png"))
            self.root.iconphoto(True, icon)
        except Exception:
            pass

        self.root.geometry("900x780")
        self.root.resizable(False, False)
        self.root.title("Scraper Suite — SafeerAhmad")
        self.root.configure(bg=BG)

        self._setup_styles()
        self._build_header()
        self._build_tab_bar()
        self._build_content()
        self._build_log()

        self.__log("Welcome to Scraper Suite\nDeveloped by SafeerAhmad — pick a tab and start scraping.")
        self.init_communicator()

    # ── ttk styles ────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure("G.TCombobox",
                    fieldbackground=INPUT_BG, background=INPUT_BG,
                    foreground=TEXT, bordercolor=BORDER2,
                    arrowcolor=TEXT_DIM, selectbackground=INPUT_BG,
                    selectforeground=TEXT, padding=[10, 8])
        s.map("G.TCombobox",
              fieldbackground=[("readonly", INPUT_BG)],
              foreground=[("readonly", TEXT)],
              arrowcolor=[("active", ACCENT)])

        s.configure("Dark.Vertical.TScrollbar",
                    background=GLASS2, troughcolor=GLASS,
                    bordercolor=GLASS, arrowcolor=BORDER2,
                    relief="flat", width=6)
        s.map("Dark.Vertical.TScrollbar",
              background=[("active", BORDER2), ("!active", GLASS2)])

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = tk.Frame(self.root, bg=GLASS, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        left = tk.Frame(hdr, bg=GLASS)
        left.pack(side="left", padx=28, pady=12)

        tk.Label(left, text="◈  Scraper Suite",
                 font=("Segoe UI", 16, "bold"),
                 fg=TEXT, bg=GLASS).pack(side="left")

        badge = tk.Label(hdr, text="v2.0",
                          font=("Segoe UI", 8, "bold"),
                          fg=ACCENT, bg=ACCENT2,
                          padx=6, pady=2)
        badge.pack(side="left", padx=(4, 0), pady=18)

        tk.Label(hdr, text="by SafeerAhmad",
                 font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=GLASS).pack(side="right", padx=28)

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

    # ── Custom tab bar ────────────────────────────────────────────────────────
    def _build_tab_bar(self):
        self.tab_bar = tk.Frame(self.root, bg=GLASS, height=48)
        self.tab_bar.pack(fill="x")
        self.tab_bar.pack_propagate(False)

        self.current_tab = "maps"
        self._tabs = {}
        for name, text in (("maps",    "  🗺  Google Maps  "),
                           ("web",     "  🔍  Web Search  "),
                           ("history", "  🕘  History  ")):
            self._tab_btn(text, name)

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

    def _tab_btn(self, text, name):
        active = (name == self.current_tab)
        wrap = tk.Frame(self.tab_bar, bg=GLASS)
        wrap.pack(side="left")

        lbl = tk.Label(wrap, text=text,
                       font=("Segoe UI", 10, "bold"),
                       fg=ACCENT if active else TEXT_DIM,
                       bg=GLASS, cursor="hand2",
                       padx=4, pady=13)
        lbl.pack()

        line = tk.Frame(wrap, bg=ACCENT if active else GLASS, height=2)
        line.pack(fill="x")

        lbl.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
        line.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
        self._tabs[name] = {"lbl": lbl, "line": line}

    def _switch_tab(self, name):
        if name == self.current_tab:
            return

        # Deactivate the current tab
        self._frames[self.current_tab].pack_forget()
        self._tabs[self.current_tab]["lbl"].config(fg=TEXT_DIM)
        self._tabs[self.current_tab]["line"].config(bg=GLASS)

        # Activate the new tab
        self.current_tab = name
        self._tabs[name]["lbl"].config(fg=ACCENT)
        self._tabs[name]["line"].config(bg=ACCENT)
        self._frames[name].pack(fill="x", padx=32, pady=24)

        if name == "history":
            self._refresh_history()

    # ── Content area (tab frames) ─────────────────────────────────────────────
    def _build_content(self):
        self._content = tk.Frame(self.root, bg=BG)
        self._content.pack(fill="x")

        self._frames = {
            "maps":    tk.Frame(self._content, bg=BG),
            "web":     tk.Frame(self._content, bg=BG),
            "history": tk.Frame(self._content, bg=BG),
        }

        self._build_maps_content(self._frames["maps"])
        self._build_web_content(self._frames["web"])
        self._build_history_content(self._frames["history"])

        # Show maps by default
        self._frames["maps"].pack(fill="x", padx=32, pady=24)

    # ── Maps card ─────────────────────────────────────────────────────────────
    def _build_maps_content(self, parent):
        card = self._card(parent)

        self._section_label(card, "Search Query",
                            "Enter what you want to find on Google Maps")
        self.search_box = self._input(card)
        self.search_box.bind("<Return>", lambda e: self._maps_submit())

        row = tk.Frame(card, bg=GLASS2)
        row.pack(fill="x", padx=24, pady=(20, 0))

        # Format
        left = tk.Frame(row, bg=GLASS2)
        left.pack(side="left", fill="x", expand=True, padx=(0, 16))
        self._section_label(left, "Output Format", "How to export your data")
        self.outputFormatButton = ttk.Combobox(
            left, values=["Excel", "Json", "Csv"],
            state="readonly", font=("Segoe UI", 11), style="G.TCombobox")
        self.outputFormatButton.pack(fill="x")

        # Headless
        right = tk.Frame(row, bg=GLASS2)
        right.pack(side="right")
        self._section_label(right, "Headless Mode", "No browser window")
        self.healdessCheckBoxVar = tk.IntVar()
        cb_row = tk.Frame(right, bg=GLASS2)
        cb_row.pack(anchor="w", pady=(4, 0))
        tk.Checkbutton(cb_row, variable=self.healdessCheckBoxVar,
                       bg=GLASS2, fg=TEXT,
                       activebackground=GLASS2, activeforeground=ACCENT,
                       selectcolor=BORDER, relief="flat",
                       highlightthickness=0).pack(side="left")
        tk.Label(cb_row, text="Enable", font=("Segoe UI", 10),
                 fg=TEXT_DIM, bg=GLASS2).pack(side="left", padx=(4, 0))

        # Region scope — beat Google Maps' ~120-result limit
        tk.Frame(card, bg=GLASS2, height=18).pack()
        self._section_label(
            card, "Region Scope",
            "None = one search (max ~120). Pick a country or 'All countries' to "
            "auto-search every city and merge results (much slower). Tip: with a "
            "scope, type only the business type, e.g. 'travel agents'.")
        self.regionScopeButton = ttk.Combobox(
            card, values=regions.scope_choices(),
            state="readonly", font=("Segoe UI", 11), style="G.TCombobox")
        self.regionScopeButton.set(regions.SIMPLE)
        self.regionScopeButton.pack(fill="x", padx=24)

        tk.Frame(card, bg=GLASS2, height=22).pack()
        self.maps_btn = self._btn(card, "▶   Start Scraping", self._maps_submit)
        tk.Frame(card, bg=GLASS2, height=4).pack()

    # ── Web Search card ───────────────────────────────────────────────────────
    def _build_web_content(self, parent):
        card = self._card(parent)

        self._section_label(card, "Search Query",
                            "e.g.   travel agents in birmingham")
        self.web_search_box = self._input(card)
        self.web_search_box.bind("<Return>", lambda e: self._web_submit())

        row = tk.Frame(card, bg=GLASS2)
        row.pack(fill="x", padx=24, pady=(20, 0))

        left = tk.Frame(row, bg=GLASS2)
        left.pack(side="left", fill="x", expand=True, padx=(0, 16))
        self._section_label(left, "Output Format", "How to export your data")
        self.web_format = ttk.Combobox(
            left, values=["Excel", "Json", "Csv"],
            state="readonly", font=("Segoe UI", 11), style="G.TCombobox")
        self.web_format.pack(fill="x")

        right = tk.Frame(row, bg=GLASS2)
        right.pack(side="right")
        self._section_label(right, "Results", "No limit — scrapes everything")
        tk.Label(right, text="∞  Unlimited",
                 font=("Segoe UI", 13, "bold"),
                 fg=ACCENT, bg=GLASS2).pack(anchor="w", pady=(4, 0))

        tk.Frame(card, bg=GLASS2, height=22).pack()
        self.web_btn = self._btn(card, "▶   Start Web Search", self._web_submit)
        tk.Frame(card, bg=GLASS2, height=4).pack()

    # ── History card ──────────────────────────────────────────────────────────
    def _build_history_content(self, parent):
        card = self._card(parent)

        top = tk.Frame(card, bg=GLASS2)
        top.pack(fill="x", padx=24)
        tk.Label(top, text="Search History",
                 font=("Segoe UI", 11, "bold"),
                 fg=TEXT, bg=GLASS2).pack(side="left")
        refresh = tk.Button(top, text="⟳  Refresh", command=self._refresh_history,
                            font=("Segoe UI", 9, "bold"), fg="white", bg=ACCENT2,
                            activebackground=ACCENT, activeforeground="white",
                            relief="flat", bd=0, padx=12, pady=5, cursor="hand2")
        refresh.pack(side="right")
        tk.Label(card, text="Every Google Maps and Web Search run is logged here.",
                 font=("Segoe UI", 9), fg=TEXT_DIM, bg=GLASS2,
                 anchor="w").pack(fill="x", padx=24, pady=(2, 8))

        s = ttk.Style()
        s.configure("H.Treeview", background=INPUT_BG, fieldbackground=INPUT_BG,
                    foreground=TEXT, rowheight=26, borderwidth=0)
        s.configure("H.Treeview.Heading", background=GLASS, foreground=TEXT_DIM,
                    relief="flat", font=("Segoe UI", 9, "bold"))
        s.map("H.Treeview", background=[("selected", ACCENT2)])

        wrap = tk.Frame(card, bg=GLASS2)
        wrap.pack(fill="x", padx=24, pady=(0, 20))

        cols = ("time", "source", "query", "scope", "records", "file", "status")
        headings = {"time": "Time", "source": "Source", "query": "Query",
                    "scope": "Scope", "records": "Records", "file": "File",
                    "status": "Status"}
        widths = {"time": 105, "source": 85, "query": 140, "scope": 120,
                  "records": 65, "file": 150, "status": 75}

        self.history_tree = ttk.Treeview(
            wrap, columns=cols, show="headings", height=11, style="H.Treeview")
        for c in cols:
            self.history_tree.heading(c, text=headings[c])
            self.history_tree.column(c, width=widths[c], anchor="w",
                                     stretch=(c == "query"))
        self.history_tree.pack(side="left", fill="x", expand=True)

        sb = ttk.Scrollbar(wrap, orient="vertical",
                           command=self.history_tree.yview,
                           style="Dark.Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        self.history_tree.configure(yscrollcommand=sb.set)

        self._refresh_history()

    def _refresh_history(self):
        if not hasattr(self, "history_tree"):
            return
        try:
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            for e in history.load():
                self.history_tree.insert("", "end", values=(
                    e.get("time", "-"), e.get("source", "-"), e.get("query", "-"),
                    e.get("scope", "-"), e.get("records", 0), e.get("file", "-"),
                    e.get("status", "-")))
        except Exception:
            pass

    # ── Activity log ──────────────────────────────────────────────────────────
    def _build_log(self):
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        log_outer = tk.Frame(self.root, bg=BG)
        log_outer.pack(fill="both", expand=True, padx=32, pady=(16, 20))

        # Log header
        hdr = tk.Frame(log_outer, bg=BG)
        hdr.pack(fill="x", pady=(0, 8))

        tk.Label(hdr, text="Activity Log",
                 font=("Segoe UI", 10, "bold"),
                 fg=TEXT_DIM, bg=BG).pack(side="left")

        self.status_dot = tk.Label(hdr, text="●",
                                    font=("Segoe UI", 9),
                                    fg=BORDER2, bg=BG)
        self.status_dot.pack(side="left", padx=(6, 0))

        # Log body
        log_card = tk.Frame(log_outer, bg=BORDER2, bd=0)
        log_card.pack(fill="both", expand=True)

        inner = tk.Frame(log_card, bg=GLASS, bd=0)
        inner.pack(padx=1, pady=1, fill="both", expand=True)

        self.show_text = tk.Text(
            inner,
            font=("Consolas", 10),
            bg=GLASS, fg="#adbac7",
            insertbackground=TEXT,
            relief="flat", bd=0,
            state="disabled", wrap=WORD,
            padx=16, pady=12,
            spacing1=2, spacing3=2,
            cursor="arrow",
        )
        self.show_text.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(inner, orient="vertical",
                            command=self.show_text.yview,
                            style="Dark.Vertical.TScrollbar")
        sb.pack(side="right", fill="y", pady=4)
        self.show_text.configure(yscrollcommand=sb.set)

        self.show_text.bind("<MouseWheel>",
            lambda e: self.show_text.yview_scroll(-1 * (e.delta // 120), "units"))

        self.show_text.tag_configure("arrow", foreground=ACCENT,
                                      font=("Segoe UI", 10, "bold"))
        self.show_text.tag_configure("msg",   foreground="#adbac7")
        self.show_text.tag_configure("dim",   foreground=TEXT_DIM,
                                      font=("Consolas", 9))

        # Bottom accent line
        tk.Frame(log_outer, bg=ACCENT, height=2).pack(fill="x")

    # ── Reusable widget builders ──────────────────────────────────────────────
    def _card(self, parent):
        outer = tk.Frame(parent, bg=BORDER2, bd=0)
        outer.pack(fill="x")
        inner = tk.Frame(outer, bg=GLASS2, bd=0)
        inner.pack(padx=1, pady=1, fill="x")
        tk.Frame(inner, bg=GLASS2, height=22).pack()
        return inner

    def _section_label(self, parent, title, sub):
        tk.Label(parent, text=title,
                 font=("Segoe UI", 11, "bold"),
                 fg=TEXT, bg=parent["bg"],
                 anchor="w").pack(fill="x", padx=24)
        tk.Label(parent, text=sub,
                 font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=parent["bg"],
                 anchor="w").pack(fill="x", padx=24, pady=(2, 8))

    def _input(self, parent):
        outer = tk.Frame(parent, bg=BORDER2, bd=0)
        outer.pack(fill="x", padx=24)

        inner = tk.Frame(outer, bg=INPUT_BG)
        inner.pack(padx=1, pady=1, fill="x")

        e = tk.Entry(inner, font=("Segoe UI", 13),
                     bg=INPUT_BG, fg=TEXT,
                     insertbackground=ACCENT,
                     relief="flat", bd=0)
        e.pack(fill="x", ipady=10, padx=12)

        # Blue underline on focus
        line = tk.Frame(outer, bg=BORDER2, height=2)
        line.pack(fill="x")

        def on_focus_in(e):
            line.config(bg=ACCENT)
        def on_focus_out(e):
            line.config(bg=BORDER2)

        e.bind("<FocusIn>",  on_focus_in)
        e.bind("<FocusOut>", on_focus_out)
        return e

    def _btn(self, parent, text, cmd):
        wrap = tk.Frame(parent, bg=GLASS2)
        wrap.pack(fill="x", padx=24, pady=(0, 20))

        btn = tk.Button(wrap, text=text,
                        font=("Segoe UI", 12, "bold"),
                        fg="white", bg=BTN_GRN,
                        activebackground=BTN_HOV,
                        activeforeground="white",
                        relief="flat", bd=0,
                        pady=13, cursor="hand2",
                        command=cmd)
        btn.pack(fill="x")
        btn.bind("<Enter>", lambda e, b=btn: b.config(bg=BTN_HOV) if str(b["state"]) != "disabled" else None)
        btn.bind("<Leave>", lambda e, b=btn: b.config(bg=BTN_GRN) if str(b["state"]) != "disabled" else None)
        return btn

    # ── Communicator ──────────────────────────────────────────────────────────
    def init_communicator(self):
        Communicator.set_frontend_object(self)

    def __log(self, text):
        self.show_text.config(state="normal")
        self.show_text.insert(tk.END, "›  ", "arrow")
        self.show_text.insert(tk.END, text + "\n\n", "msg")
        self.show_text.see(tk.END)
        self.show_text.config(state="disabled")

    def messageshowing(self, message):
        self.__log(message)

    # ── Maps logic ────────────────────────────────────────────────────────────
    def _maps_submit(self):
        self.searchQuery       = self.search_box.get().strip()
        self.outputFormatValue = self.outputFormatButton.get()

        if not self.searchQuery:
            self.__log("Please enter a search query.")
            return
        if not self.outputFormatValue:
            self.__log("Please select an output format.")
            return

        self.maps_btn.config(state="disabled", bg=BTN_DIS,
                              text="⏳  Scraping in progress...")
        self.status_dot.config(fg=SUCCESS)

        self.searchQuery       = self.searchQuery.lower()
        self.outputFormatValue = self.outputFormatValue.lower()
        self.headlessMode      = self.healdessCheckBoxVar.get()
        self.regionScope       = self.regionScopeButton.get() or regions.SIMPLE

        if self.regionScope == regions.ALL:
            self.__log("Heads up: 'All countries' runs tens of thousands of "
                       "searches and can take a very long time. You can stop by "
                       "closing the window.")

        self._maps_thread = threading.Thread(target=self._run_maps, daemon=True)
        self._maps_thread.start()

    def _run_maps(self):
        backend = Backend(self.searchQuery, self.outputFormatValue,
                          healdessmode=self.headlessMode,
                          region_scope=self.regionScope)
        backend.mainscraping()

    def end_processing(self):
        self.maps_btn.config(state="normal", bg=BTN_GRN,
                              text="▶   Start Scraping")
        self.status_dot.config(fg=BORDER2)
        self._refresh_history()

    # ── Web logic ─────────────────────────────────────────────────────────────
    def _web_submit(self):
        query = self.web_search_box.get().strip()
        fmt   = self.web_format.get()

        if not query:
            self.__log("Please enter a search query.")
            return
        if not fmt:
            self.__log("Please select an output format.")
            return

        max_r = 999999  # no limit

        self.web_btn.config(state="disabled", bg=BTN_DIS,
                             text="⏳  Searching the web...")
        self.status_dot.config(fg=SUCCESS)

        def run():
            WebSearchBackend(
                query=query.lower(),
                output_format=fmt.lower(),
                max_results=max_r,
                on_done=self._end_web,
            ).run()

        threading.Thread(target=run, daemon=True).start()

    def _end_web(self):
        self.web_btn.config(state="normal", bg=BTN_GRN,
                             text="▶   Start Web Search")
        self.status_dot.config(fg=BORDER2)
        self._refresh_history()

    # ── Close ─────────────────────────────────────────────────────────────────
    def closingbrowser(self):
        try:
            Common.set_close_thread()
            self.root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    app = Frontend()
    app.root.protocol("WM_DELETE_WINDOW", app.closingbrowser)
    app.root.mainloop()
