"""
This module contain the code for frontend (themed, rounded UI).
"""

from scraper.communicator import Communicator
import os
import tkinter as tk
from tkinter import ttk, WORD
from scraper.scraper import Backend
from scraper.web_scraper import WebSearchBackend
from scraper.common import Common
from scraper import regions, history, geodata, leadfiles, jobstate
from scraper.resource import resource_path
from scraper import applog
from settings import OUTPUT_PATH
import threading
import time
import logging
from tkinter import filedialog


# ── Themes ─────────────────────────────────────────────────────────────────────
THEMES = {
    "dark": {
        "bg": "#0d1117", "surface": "#161b22", "card": "#1c2128",
        "border": "#30363d", "accent": "#58a6ff", "accent_soft": "#1f4068",
        "text": "#e6edf3", "dim": "#7d8590", "input": "#0d1117",
        "btn": "#238636", "btn_hover": "#2ea043", "btn_dis": "#14532d",
        "success": "#3fb950", "log_fg": "#adbac7", "warning": "#d29922",
    },
    "light": {
        "bg": "#e9f2fc", "surface": "#ffffff", "card": "#ffffff",
        "border": "#cfe0f2", "accent": "#1a73e8", "accent_soft": "#e3f0ff",
        "text": "#17202b", "dim": "#5b6b7c", "input": "#f3f8ff",
        "btn": "#1f9d55", "btn_hover": "#178a48", "btn_dis": "#a8ddbe",
        "success": "#1a7f37", "log_fg": "#1e2a3a", "warning": "#b26a00",
    },
}


def _round_points(x1, y1, x2, y2, r):
    """Point list for a rounded rectangle drawn as a smoothed polygon."""
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class RoundedCard(tk.Canvas):
    """A canvas that paints a rounded rectangle and hosts widgets on top."""

    def __init__(self, parent, card_bg, page_bg, radius=16, pad=14):
        super().__init__(parent, bd=0, highlightthickness=0, bg=page_bg)
        self._card_bg = card_bg
        self._radius = radius
        self._pad = pad
        self.body = tk.Frame(self, bg=card_bg)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self.body.bind("<Configure>", self._redraw)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _=None):
        w = self.winfo_width()
        if w <= 1:
            return
        bh = self.body.winfo_reqheight()
        self.itemconfig(self._win, width=w - 2 * self._pad)
        self.configure(height=bh + 2 * self._pad)
        self.delete("bg")
        pts = _round_points(1, 1, w - 2, bh + 2 * self._pad - 2, self._radius)
        self.create_polygon(pts, smooth=True, fill=self._card_bg,
                            outline="", tags="bg")
        self.tag_lower("bg")


class RoundButton(tk.Canvas):
    """A rounded, hover-aware button drawn on a canvas."""

    def __init__(self, parent, text, command, page_bg, fill, hover, fg,
                 disabled, radius=12, height=50):
        super().__init__(parent, bd=0, highlightthickness=0,
                         bg=page_bg, height=height)
        self._text = text
        self._command = command
        self._fill = fill
        self._hover = hover
        self._fg = fg
        self._disabled = disabled
        self._radius = radius
        self._enabled = True
        self._cur = fill
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._set_paint(self._hover))
        self.bind("<Leave>", lambda e: self._set_paint(self._fill))

    def _set_paint(self, color):
        if self._enabled:
            self._cur = color
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            return
        color = self._cur if self._enabled else self._disabled
        pts = _round_points(1, 1, w - 2, h - 2, self._radius)
        self.create_polygon(pts, smooth=True, fill=color, outline="")
        self.create_text(w // 2, h // 2, text=self._text, fill=self._fg,
                         font=("Segoe UI", 12, "bold"))

    def _click(self, _):
        if self._enabled and self._command:
            self._command()

    def set_state(self, enabled, text=None):
        self._enabled = enabled
        if text is not None:
            self._text = text
        self._cur = self._fill
        self._draw()


class Frontend:
    def __init__(self):
        self.root = tk.Tk()
        try:
            self._app_icon = tk.PhotoImage(file=resource_path("images/LeadScrapper.png"))
            self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass

        self.root.geometry("920x940")
        self.root.minsize(860, 600)
        self.root.resizable(True, True)   # allow maximize / fullscreen
        self.root.title("LeadScrapper by Safeer Ahmad")

        # F11 toggles fullscreen, Esc exits it
        self._is_fullscreen = False
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.root.bind("<Escape>", lambda e: self._exit_fullscreen())

        self.theme = "light"
        self.C = THEMES[self.theme]

        # Persistent state (survives theme rebuilds automatically)
        self.current_tab = "maps"
        self._log_messages = []
        self._maps_busy = False
        self._web_busy = False
        self._status_on = False
        self._resume_completed = set()   # hoods already done, when resuming a job
        self._active_backend = None      # current Maps Backend (for "Compile Now")
        self._active_web_run = None      # current Web Search run_dir/fmt/query
        self._prog = None          # (current, total, message) — survives theme rebuild
        self._progress_start = None

        self.mapsQueryVar = tk.StringVar()
        self.outputFormatVar = tk.StringVar()
        self.regionScopeVar = tk.StringVar(value=regions.SIMPLE)
        self.healdessCheckBoxVar = tk.IntVar()
        self.selectAllVar = tk.IntVar()
        self.alsoWebVar = tk.IntVar()

        # Country -> State -> City state (persists across theme rebuilds)
        self.cityCountryVar = tk.StringVar()
        self.stateVar = tk.StringVar()
        self.selectAllLocVar = tk.IntVar()
        self.locSearchVar = tk.StringVar()
        self._geo_region_label = ""    # "State, Country" used to build city queries
        self._city_hoods = []          # city names currently loaded
        self._city_vars = {}           # name -> IntVar (persist)
        self._city_status = {}         # name -> status text
        self._city_done_text = ""
        # The picker is built once per tab that shows it (Maps + Web Search), so
        # each of these is a LIST with one entry per tab, kept in sync because
        # they all read/write the same _city_hoods/_city_vars/_city_status above.
        self._loc_rows = {}             # city -> list of status Labels (one per tab)
        self._loc_list_frames = []      # checklist container frame per tab
        self._loc_search_rows = []      # "search cities" row per tab
        self._loc_select_alls = []      # "Select All" checkbutton per tab
        self._city_done_lbls = []       # "city done" label per tab
        self.webQueryVar = tk.StringVar()
        self.webFormatVar = tk.StringVar()
        self.webMaxVar = tk.StringVar(value="50")

        self._direction_defs = regions.load_directions()
        self.directionVars = {word: tk.IntVar()
                              for (_label, word) in self._direction_defs}

        self._build_ui()
        self.__log("Welcome to LeadScrapper\nDeveloped by Safeer Ahmad — pick a "
                   "tab and start scraping.")
        self.init_communicator()

    # ── Theme plumbing ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self.root.configure(bg=self.C["bg"])
        self._setup_styles()
        self._build_header()
        self._build_tab_bar()
        self._build_scroll_area()   # scrollable middle (holds the tab content)
        self._build_content()       # packs tab frames into the scroll body
        self._build_log()           # pinned to the bottom
        self._build_progress()      # pinned just above the log

    def _toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.C = THEMES[self.theme]
        for w in self.root.winfo_children():
            w.destroy()
        self._build_ui()
        self._render_log()

    # ── ttk styles ─────────────────────────────────────────────────────────────
    def _setup_styles(self):
        C = self.C
        s = ttk.Style()
        s.theme_use("clam")

        s.configure("G.TCombobox",
                    fieldbackground=C["input"], background=C["input"],
                    foreground=C["text"], bordercolor=C["border"],
                    arrowcolor=C["dim"], selectbackground=C["input"],
                    selectforeground=C["text"], padding=[10, 8])
        s.map("G.TCombobox",
              fieldbackground=[("readonly", C["input"])],
              foreground=[("readonly", C["text"])],
              arrowcolor=[("active", C["accent"])])

        s.configure("Dark.Vertical.TScrollbar",
                    background=C["card"], troughcolor=C["surface"],
                    bordercolor=C["surface"], arrowcolor=C["border"],
                    relief="flat", width=6)
        s.map("Dark.Vertical.TScrollbar",
              background=[("active", C["border"]), ("!active", C["card"])])

        s.configure("H.Treeview", background=C["input"], fieldbackground=C["input"],
                    foreground=C["text"], rowheight=26, borderwidth=0)
        s.configure("H.Treeview.Heading", background=C["surface"],
                    foreground=C["dim"], relief="flat",
                    font=("Segoe UI", 9, "bold"))
        s.map("H.Treeview", background=[("selected", C["accent_soft"])])

    # ── Header ───────────────────────────────────────────────────────────────
    def _build_header(self):
        C = self.C
        hdr = tk.Frame(self.root, bg=C["surface"], height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        left = tk.Frame(hdr, bg=C["surface"])
        left.pack(side="left", padx=28, pady=12)
        tk.Label(left, text="◈  LeadScrapper",
                 font=("Segoe UI", 16, "bold"),
                 fg=C["text"], bg=C["surface"]).pack(side="left")

        badge = tk.Label(hdr, text="v2.1",
                         font=("Segoe UI", 8, "bold"),
                         fg=C["accent"], bg=C["accent_soft"], padx=6, pady=2)
        badge.pack(side="left", padx=(4, 0), pady=20)

        # Theme toggle
        toggle_text = "☀  Light" if self.theme == "dark" else "🌙  Dark"
        toggle = tk.Label(hdr, text=toggle_text,
                          font=("Segoe UI", 9, "bold"),
                          fg=C["accent"], bg=C["accent_soft"],
                          padx=12, pady=6, cursor="hand2")
        toggle.pack(side="right", padx=(0, 22), pady=16)
        toggle.bind("<Button-1>", lambda e: self._toggle_theme())

        tk.Label(hdr, text="by Safeer Ahmad",
                 font=("Segoe UI", 9),
                 fg=C["dim"], bg=C["surface"]).pack(side="right", padx=(0, 6))

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

    # ── Custom tab bar ─────────────────────────────────────────────────────────
    def _build_tab_bar(self):
        C = self.C
        self.tab_bar = tk.Frame(self.root, bg=C["surface"], height=48)
        self.tab_bar.pack(fill="x")
        self.tab_bar.pack_propagate(False)

        self._tabs = {}
        for name, text in (("maps",    "  🗺  Google Maps  "),
                           ("web",     "  🔍  Web Search  "),
                           ("history", "  🕘  History  ")):
            self._tab_btn(text, name)

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

    def _tab_btn(self, text, name):
        C = self.C
        active = (name == self.current_tab)
        wrap = tk.Frame(self.tab_bar, bg=C["surface"])
        wrap.pack(side="left")

        lbl = tk.Label(wrap, text=text, font=("Segoe UI", 10, "bold"),
                       fg=C["accent"] if active else C["dim"],
                       bg=C["surface"], cursor="hand2", padx=4, pady=13)
        lbl.pack()
        line = tk.Frame(wrap, bg=C["accent"] if active else C["surface"], height=2)
        line.pack(fill="x")

        lbl.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
        line.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
        self._tabs[name] = {"lbl": lbl, "line": line}

    def _switch_tab(self, name):
        if name == self.current_tab:
            return
        C = self.C
        self._frames[self.current_tab].pack_forget()
        self._tabs[self.current_tab]["lbl"].config(fg=C["dim"])
        self._tabs[self.current_tab]["line"].config(bg=C["surface"])

        self.current_tab = name
        self._tabs[name]["lbl"].config(fg=C["accent"])
        self._tabs[name]["line"].config(bg=C["accent"])
        self._frames[name].pack(fill="x", padx=32, pady=20)

        if name == "history":
            self._refresh_history()

    # ── Scrollable body ─────────────────────────────────────────────────────────
    def _build_scroll_area(self):
        C = self.C
        container = tk.Frame(self.root, bg=C["bg"])
        container.pack(side="top", fill="both", expand=True)

        canvas = tk.Canvas(container, bg=C["bg"], bd=0, highlightthickness=0)
        vbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview,
                             style="Dark.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._scroll_canvas = canvas
        self._scroll_inner = tk.Frame(canvas, bg=C["bg"])
        self._scroll_win = canvas.create_window((0, 0), window=self._scroll_inner,
                                                anchor="nw")
        self._scroll_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._scroll_win, width=e.width))
        # Mouse wheel scrolls this area only while the pointer is over it.
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", self._on_scroll_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _on_scroll_wheel(self, event):
        self._scroll_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # ── Content area ────────────────────────────────────────────────────────────
    def _build_content(self):
        self._content = tk.Frame(self._scroll_inner, bg=self.C["bg"])
        self._content.pack(fill="x")

        # Reset per-tab picker widget lists (theme rebuilds destroy the old
        # widgets, so stale references must not linger here).
        self._loc_list_frames = []
        self._loc_search_rows = []
        self._loc_select_alls = []
        self._city_done_lbls = []

        self._frames = {
            "maps":    tk.Frame(self._content, bg=self.C["bg"]),
            "web":     tk.Frame(self._content, bg=self.C["bg"]),
            "history": tk.Frame(self._content, bg=self.C["bg"]),
        }
        self._build_maps_content(self._frames["maps"])
        self._build_web_content(self._frames["web"])
        self._build_history_content(self._frames["history"])

        self._frames[self.current_tab].pack(fill="x", padx=32, pady=20)

    # ── Maps card ────────────────────────────────────────────────────────────
    def _build_maps_content(self, parent):
        C = self.C
        card = self._card(parent)

        self._section_label(card, "Search Query",
                            "Enter what you want to find on Google Maps")
        self.search_box = self._input(card, self.mapsQueryVar)
        self.search_box.bind("<Return>", lambda e: self._maps_submit())

        row = tk.Frame(card, bg=C["card"])
        row.pack(fill="x", padx=20, pady=(16, 0))

        left = tk.Frame(row, bg=C["card"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 16))
        self._section_label(left, "Output Format", "How to export your data")
        self.outputFormatButton = ttk.Combobox(
            left, values=["Excel", "Json", "Csv"], textvariable=self.outputFormatVar,
            state="readonly", font=("Segoe UI", 11), style="G.TCombobox")
        self.outputFormatButton.pack(fill="x")

        right = tk.Frame(row, bg=C["card"])
        right.pack(side="right")
        self._section_label(right, "Headless Mode", "No browser window")
        cb_row = tk.Frame(right, bg=C["card"])
        cb_row.pack(anchor="w", pady=(4, 0))
        tk.Checkbutton(cb_row, variable=self.healdessCheckBoxVar,
                       bg=C["card"], fg=C["text"], activebackground=C["card"],
                       activeforeground=C["accent"], selectcolor=C["border"],
                       relief="flat", highlightthickness=0).pack(side="left")
        tk.Label(cb_row, text="Enable", font=("Segoe UI", 10),
                 fg=C["dim"], bg=C["card"]).pack(side="left", padx=(4, 0))

        # ── Location: Country → State → City (offline dataset) ────────────────
        self._build_geo_section(card)

        # Also run Web Search alongside (extra files, merged into MAIN)
        tk.Frame(card, bg=C["card"], height=12).pack()
        web_row = tk.Frame(card, bg=C["card"])
        web_row.pack(anchor="w", padx=20)
        tk.Checkbutton(web_row, variable=self.alsoWebVar,
                       bg=C["card"], fg=C["text"], activebackground=C["card"],
                       activeforeground=C["accent"], selectcolor=C["border"],
                       relief="flat", highlightthickness=0).pack(side="left")
        tk.Label(web_row, text="Also run Web Search at the same time "
                               "(extra files, all merged into the MAIN file)",
                 font=("Segoe UI", 9), fg=C["dim"], bg=C["card"]).pack(side="left")

        tk.Frame(card, bg=C["card"], height=18).pack()
        self.maps_btn = self._btn(card, "▶   Start Scraping", self._maps_submit)
        if self._maps_busy:
            self.maps_btn.set_state(False, "⏳  Scraping in progress...")
        self.pause_btn = self._btn(
            card, "▶  Resume" if Common.is_paused() else "⏸  Pause",
            self._toggle_pause)
        self.pause_btn.set_state(self._maps_busy)
        self.maps_compile_btn = self._btn(
            card, "⚙  Compile MAIN Now (from progress so far)", self._compile_now)
        self.maps_compile_btn.set_state(self._active_backend is not None)
        tk.Frame(card, bg=C["card"], height=6).pack()

    # ── Web Search card ──────────────────────────────────────────────────────
    def _build_web_content(self, parent):
        C = self.C
        card = self._card(parent)

        self._section_label(card, "Search Query",
                            "e.g.   travel agents in birmingham")
        self.web_search_box = self._input(card, self.webQueryVar)
        self.web_search_box.bind("<Return>", lambda e: self._web_submit())

        row = tk.Frame(card, bg=C["card"])
        row.pack(fill="x", padx=20, pady=(16, 0))

        left = tk.Frame(row, bg=C["card"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 16))
        self._section_label(left, "Output Format", "How to export your data")
        self.web_format = ttk.Combobox(
            left, values=["Excel", "Json", "Csv"], textvariable=self.webFormatVar,
            state="readonly", font=("Segoe UI", 11), style="G.TCombobox")
        self.web_format.pack(fill="x")

        right = tk.Frame(row, bg=C["card"])
        right.pack(side="right")
        self._section_label(right, "Max Sites",
                            "Per search/city. Lower = faster batches.")
        web_max = ttk.Combobox(
            right, values=["20", "50", "100", "200", "Unlimited"],
            textvariable=self.webMaxVar, state="readonly",
            width=12, font=("Segoe UI", 11), style="G.TCombobox")
        web_max.pack(fill="x")

        # Same Country/State/City picker as the Maps tab — ticking a city here
        # also ticks it there (shared selection), so either tool can use it.
        self._build_geo_section(card)

        tk.Frame(card, bg=C["card"], height=18).pack()
        self.web_btn = self._btn(card, "▶   Start Web Search", self._web_submit)
        if self._web_busy:
            self.web_btn.set_state(False, "⏳  Searching the web...")
        self.web_pause_btn = self._btn(
            card, "▶  Resume" if Common.is_paused() else "⏸  Pause",
            self._toggle_pause)
        self.web_pause_btn.set_state(self._web_busy)
        self.web_compile_btn = self._btn(
            card, "⚙  Compile MAIN Now (from progress so far)", self._compile_now)
        self.web_compile_btn.set_state(self._active_web_run is not None)
        tk.Frame(card, bg=C["card"], height=6).pack()

    # ── History card ───────────────────────────────────────────────────────────
    def _build_history_content(self, parent):
        C = self.C
        card = self._card(parent)

        top = tk.Frame(card, bg=C["card"])
        top.pack(fill="x", padx=20)
        tk.Label(top, text="Search History", font=("Segoe UI", 11, "bold"),
                 fg=C["text"], bg=C["card"]).pack(side="left")
        self._refresh_button(top)
        cb = tk.Label(top, text="📁  Compile a folder…",
                     font=("Segoe UI", 9, "bold"), fg=C["accent"],
                     bg=C["accent_soft"], padx=12, pady=5, cursor="hand2")
        cb.pack(side="right", padx=(0, 8))
        cb.bind("<Button-1>", lambda e: self._compile_folder_dialog())
        tk.Label(card, text="Every Google Maps and Web Search run is logged here.",
                 font=("Segoe UI", 9), fg=C["dim"], bg=C["card"],
                 anchor="w").pack(fill="x", padx=20, pady=(2, 8))

        self._resume_banner_frame = tk.Frame(card, bg=C["accent_soft"])
        self._resume_banner_frame.pack(fill="x", padx=20, pady=(0, 10))
        self._refresh_resume_banner()

        wrap = tk.Frame(card, bg=C["card"])
        wrap.pack(fill="x", padx=20, pady=(0, 16))

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

    def _refresh_button(self, parent):
        C = self.C
        b = tk.Label(parent, text="⟳  Refresh", font=("Segoe UI", 9, "bold"),
                     fg=C["accent"], bg=C["accent_soft"], padx=12, pady=5,
                     cursor="hand2")
        b.pack(side="right")
        b.bind("<Button-1>", lambda e: self._refresh_history())

    def _refresh_history(self):
        self._refresh_resume_banner()
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

    # ── Resume an interrupted batch (Pause + close app, or a crash) ────────────
    def _refresh_resume_banner(self):
        if not hasattr(self, "_resume_banner_frame"):
            return
        for w in self._resume_banner_frame.winfo_children():
            w.destroy()
        C = self.C
        job = jobstate.load()
        if not job or self._maps_busy or self._web_busy:
            self._resume_banner_frame.pack_forget()
            return
        self._resume_banner_frame.pack(fill="x", padx=20, pady=(0, 10))

        done_n = len(job.get("completed", []))
        total_n = len(job.get("locations", [])) or 1
        kind = "Google Maps" if job.get("mode", "maps") == "maps" else "Web Search"
        tk.Label(self._resume_banner_frame,
                 text=f"⏸  Unfinished {kind} job: \"{job['query']}\" in "
                      f"{job['city_name']} — {done_n}/{total_n} locations done.",
                 font=("Segoe UI", 9, "bold"), fg=C["text"], bg=C["accent_soft"],
                 anchor="w", wraplength=560, justify="left").pack(
            side="left", padx=12, pady=8, fill="x", expand=True)
        resume_lbl = tk.Label(self._resume_banner_frame, text="▶  Resume",
                              font=("Segoe UI", 9, "bold"), fg="white",
                              bg=C["accent"], padx=12, pady=5, cursor="hand2")
        resume_lbl.pack(side="right", padx=(8, 12), pady=8)
        resume_lbl.bind("<Button-1>", lambda e: self._resume_job())
        discard_lbl = tk.Label(self._resume_banner_frame, text="✕  Discard",
                               font=("Segoe UI", 9), fg=C["dim"], bg=C["accent_soft"],
                               padx=6, pady=5, cursor="hand2")
        discard_lbl.pack(side="right", pady=8)
        discard_lbl.bind("<Button-1>", lambda e: self._discard_resume_job())

    def _discard_resume_job(self):
        jobstate.clear()
        self._refresh_resume_banner()

    def _resume_job(self):
        if self._maps_busy or self._web_busy:
            self.__log("A job is already running — let it finish (or Pause it) first.")
            return
        job = jobstate.load()
        if not job:
            self.__log("Nothing to resume.")
            return

        Common.resume()
        completed = set(job.get("completed", []))
        locations = list(job.get("locations", []))

        # Reflect it in the checklist so the Maps/Web tab shows real progress.
        self._city_hoods = locations
        self._city_vars = {h: tk.IntVar(value=1) for h in locations}
        self._city_status = {h: ("✓ done (resumed)" if h in completed else "queued")
                             for h in locations}
        self._geo_region_label = job["city_name"]
        self._render_locations()

        if job.get("mode", "maps") == "web":
            self.__log(f"Resuming Web Search: \"{job['query']}\" in "
                       f"{job['city_name']} — {len(completed)}/{len(locations)} "
                       f"already done.")
            self._web_busy = True
            if hasattr(self, "web_btn"):
                self.web_btn.set_state(False, "⏳  Searching the web...")
            if hasattr(self, "web_pause_btn"):
                self.web_pause_btn.set_state(True, "⏸  Pause")
            self._status_on = True
            if hasattr(self, "status_dot"):
                self.status_dot.config(fg=self.C["success"])
            self._switch_tab("web")
            threading.Thread(
                target=self._run_web_locations,
                args=(job["query"], job["output_format"], locations,
                     job["city_name"], job.get("max_results") or 50),
                kwargs={"resume_completed": completed},
                daemon=True).start()
        else:
            self.__log(f"Resuming: \"{job['query']}\" in {job['city_name']} — "
                       f"{len(completed)}/{len(locations)} already done.")
            self.searchQuery       = job["query"]
            self.outputFormatValue = job["output_format"]
            self.headlessMode      = job.get("headless") or 0
            self.runWeb            = bool(job.get("run_web"))
            self.selectedLocations = locations
            self.cityName          = job["city_name"]
            self._resume_completed = completed

            self._maps_busy = True
            if hasattr(self, "maps_btn"):
                self.maps_btn.set_state(False, "⏳  Scraping in progress...")
            if hasattr(self, "pause_btn"):
                self.pause_btn.set_state(True, "⏸  Pause")
            self._status_on = True
            if hasattr(self, "status_dot"):
                self.status_dot.config(fg=self.C["success"])
            self._switch_tab("maps")
            self._maps_thread = threading.Thread(target=self._run_maps, daemon=True)
            self._maps_thread.start()

    # ── Activity log ──────────────────────────────────────────────────────────
    def _build_log(self):
        C = self.C
        bottom = tk.Frame(self.root, bg=C["bg"])
        bottom.pack(side="bottom", fill="x")
        tk.Frame(bottom, bg=C["border"], height=1).pack(fill="x")

        log_outer = tk.Frame(bottom, bg=C["bg"])
        log_outer.pack(fill="x", padx=32, pady=(10, 14))

        hdr = tk.Frame(log_outer, bg=C["bg"])
        hdr.pack(fill="x", pady=(0, 8))
        tk.Label(hdr, text="Activity Log", font=("Segoe UI", 10, "bold"),
                 fg=C["dim"], bg=C["bg"]).pack(side="left")
        self.status_dot = tk.Label(
            hdr, text="●", font=("Segoe UI", 9),
            fg=C["success"] if self._status_on else C["border"], bg=C["bg"])
        self.status_dot.pack(side="left", padx=(6, 0))

        view_logs = tk.Label(
            hdr, text="🗒  View Logs", font=("Segoe UI", 9, "bold"),
            fg=C["accent"], bg=C["accent_soft"], padx=10, pady=3, cursor="hand2")
        view_logs.pack(side="right")
        view_logs.bind("<Button-1>", lambda e: self._open_logs_window())

        card = RoundedCard(log_outer, C["card"], C["bg"], radius=14, pad=6)
        card.pack(fill="both", expand=True)
        inner = card.body

        self.show_text = tk.Text(
            inner, font=("Consolas", 10), bg=C["card"], fg=C["log_fg"],
            insertbackground=C["text"], relief="flat", bd=0,
            state="disabled", wrap=WORD, padx=14, pady=10,
            spacing1=2, spacing3=2, cursor="arrow", height=7)
        self.show_text.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(inner, orient="vertical", command=self.show_text.yview,
                           style="Dark.Vertical.TScrollbar")
        sb.pack(side="right", fill="y", pady=4)
        self.show_text.configure(yscrollcommand=sb.set)
        self.show_text.bind("<MouseWheel>",
            lambda e: self.show_text.yview_scroll(-1 * (e.delta // 120), "units"))

        self.show_text.tag_configure("arrow", foreground=C["accent"],
                                      font=("Segoe UI", 10, "bold"))
        self.show_text.tag_configure("msg", foreground=C["log_fg"])

        self._render_log()

    def _render_log(self):
        if not hasattr(self, "show_text"):
            return
        self.show_text.config(state="normal")
        self.show_text.delete("1.0", tk.END)
        for text in self._log_messages:
            self.show_text.insert(tk.END, "›  ", "arrow")
            self.show_text.insert(tk.END, text + "\n\n", "msg")
        self.show_text.see(tk.END)
        self.show_text.config(state="disabled")

    # ── Progress bar + ETA ──────────────────────────────────────────────────────
    def _build_progress(self):
        C = self.C
        frame = tk.Frame(self.root, bg=C["bg"])
        frame.pack(side="bottom", fill="x", padx=32, pady=(6, 0))

        self.progress_label = tk.Label(
            frame, text="Idle", font=("Segoe UI", 9), fg=C["dim"],
            bg=C["bg"], anchor="w")
        self.progress_label.pack(fill="x", pady=(0, 4))

        s = ttk.Style()
        s.configure("G.Horizontal.TProgressbar",
                    troughcolor=C["surface"], bordercolor=C["surface"],
                    background=C["accent"], lightcolor=C["accent"],
                    darkcolor=C["accent"], thickness=10)
        self.progressbar = ttk.Progressbar(
            frame, style="G.Horizontal.TProgressbar",
            mode="determinate", maximum=100, value=0)
        self.progressbar.pack(fill="x")

        if self._prog:  # re-apply after a theme rebuild
            self._apply_progress(*self._prog)

    def update_progress(self, current, total, message=""):
        # Called from worker threads → marshal onto the Tk main loop.
        try:
            self.root.after(0, self._apply_progress, current, total, message)
        except Exception:
            pass

    def _apply_progress(self, current, total, message=""):
        if total <= 0:
            total = 1
        if current <= 0:
            self._progress_start = time.time()
        self._prog = (current, total, message)

        if not hasattr(self, "progressbar"):
            return

        self.progressbar.configure(maximum=total, value=min(current, total))
        pct = int(current / total * 100)

        eta = ""
        if current > 0 and current < total and self._progress_start:
            elapsed = time.time() - self._progress_start
            remaining = (elapsed / current) * (total - current)
            eta = f"   •   ~{self._fmt_eta(remaining)} left"

        head = message or "Working"
        self.progress_label.config(
            text=f"{head}   •   {current}/{total}  ({pct}%){eta}")

    @staticmethod
    def _fmt_eta(seconds):
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}s"
        m, s = divmod(seconds, 60)
        if m < 60:
            return f"{m}m {s}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

    # ── Reusable widget builders ──────────────────────────────────────────────
    def _card(self, parent):
        card = RoundedCard(parent, self.C["card"], self.C["bg"], radius=18, pad=10)
        card.pack(fill="x")
        tk.Frame(card.body, bg=self.C["card"], height=14).pack()
        return card.body

    def _section_label(self, parent, title, sub):
        C = self.C
        tk.Label(parent, text=title, font=("Segoe UI", 11, "bold"),
                 fg=C["text"], bg=parent["bg"], anchor="w",
                 justify="left", wraplength=780).pack(fill="x", padx=20)
        tk.Label(parent, text=sub, font=("Segoe UI", 9),
                 fg=C["dim"], bg=parent["bg"], anchor="w",
                 justify="left", wraplength=780).pack(fill="x", padx=20, pady=(2, 8))

    def _input(self, parent, textvar):
        C = self.C
        wrap = RoundedCard(parent, C["input"], C["card"], radius=12, pad=3)
        wrap.pack(fill="x", padx=20)
        e = tk.Entry(wrap.body, textvariable=textvar, font=("Segoe UI", 13),
                     bg=C["input"], fg=C["text"], insertbackground=C["accent"],
                     relief="flat", bd=0)
        e.pack(fill="x", ipady=9, padx=12)
        return e

    def _btn(self, parent, text, cmd):
        C = self.C
        btn = RoundButton(parent, text, cmd, C["card"], C["btn"], C["btn_hover"],
                          "white", C["btn_dis"], radius=12, height=50)
        btn.pack(fill="x", padx=20, pady=(0, 16))
        return btn

    # ── Communicator ──────────────────────────────────────────────────────────
    def init_communicator(self):
        Communicator.set_frontend_object(self)

    def __log(self, text):
        self._log_messages.append(text)
        try:
            logging.getLogger("activity").info(text.replace("\n", " | "))
        except Exception:
            pass
        # Messages arrive from worker threads; marshal the widget update onto the
        # Tk main loop so the on-screen log repaints reliably (and live).
        try:
            self.root.after(0, self._append_log_widget, text)
        except Exception:
            pass

    def _append_log_widget(self, text):
        if not hasattr(self, "show_text"):
            return
        self.show_text.config(state="normal")
        self.show_text.insert(tk.END, "›  ", "arrow")
        self.show_text.insert(tk.END, text + "\n\n", "msg")
        self.show_text.see(tk.END)
        self.show_text.config(state="disabled")

    def messageshowing(self, message):
        self.__log(message)

    # ── Maps logic ────────────────────────────────────────────────────────────
    def _maps_submit(self):
        self.searchQuery       = self.mapsQueryVar.get().strip()
        self.outputFormatValue = self.outputFormatVar.get()

        if not self.searchQuery:
            self.__log("Please enter a search query.")
            return
        if not self.outputFormatValue:
            self.__log("Please select an output format.")
            return

        if not self._web_busy:
            Common.resume()   # clear any stale pause flag from a previous run
        self._resume_completed = set()
        self._maps_busy = True
        self.maps_btn.set_state(False, "⏳  Scraping in progress...")
        if hasattr(self, "pause_btn"):
            self.pause_btn.set_state(True, "⏸  Pause")
        self._status_on = True
        self.status_dot.config(fg=self.C["success"])

        self.searchQuery        = self.searchQuery.lower()
        self.outputFormatValue  = self.outputFormatValue.lower()
        self.headlessMode       = self.healdessCheckBoxVar.get()
        self.runWeb             = bool(self.alsoWebVar.get())
        self.selectedLocations  = [h for h in self._city_hoods
                                   if self._city_vars.get(h) and self._city_vars[h].get()]
        self.cityName           = self._geo_region_label

        if self.selectedLocations:
            self.__log(f"Location mode: {len(self.selectedLocations)} cities in "
                       f"{self.cityName} → {len(self.selectedLocations)} files, "
                       f"all merged into MAIN.")
        else:
            self.__log("No cities selected — running a single search of your query.")

        self._maps_thread = threading.Thread(target=self._run_maps, daemon=True)
        self._maps_thread.start()

    def _run_maps(self):
        backend = Backend(self.searchQuery, self.outputFormatValue,
                          healdessmode=self.headlessMode,
                          region_scope=None,
                          directions=[],
                          run_web=self.runWeb,
                          locations=self.selectedLocations,
                          city_name=self.cityName,
                          resume_completed=self._resume_completed)
        self._active_backend = backend
        self._sync_compile_buttons()
        backend.mainscraping()

    # ── Pause / Resume (shared by Maps + Web Search — only one loop is ever
    #    actually blocked on it at a time) ───────────────────────────────────────
    def _toggle_pause(self):
        if not (self._maps_busy or self._web_busy):
            return
        if Common.is_paused():
            Common.resume()
            self.__log("Resumed.")
        else:
            Common.pause()
            self.__log("Paused — progress so far is saved. Click Resume to "
                       "continue, or close the app now and pick this job back "
                       "up later from the History tab.")
        self._sync_pause_buttons()

    def _sync_pause_buttons(self):
        text = "▶  Resume" if Common.is_paused() else "⏸  Pause"
        busy = self._maps_busy or self._web_busy
        for name in ("pause_btn", "web_pause_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.set_state(busy, text)

    def end_processing(self):
        self._maps_busy = False
        self._status_on = False
        self._active_backend = None
        if not self._web_busy:
            Common.resume()   # don't leave the next run stuck paused
        self._sync_pause_buttons()
        self._sync_compile_buttons()
        if hasattr(self, "maps_btn"):
            self.maps_btn.set_state(True, "▶   Start Scraping")
        if hasattr(self, "status_dot"):
            self.status_dot.config(fg=self.C["border"])
        self._refresh_history()

    def _sync_compile_buttons(self):
        if hasattr(self, "maps_compile_btn"):
            self.maps_compile_btn.set_state(self._active_backend is not None)
        if hasattr(self, "web_compile_btn"):
            self.web_compile_btn.set_state(self._active_web_run is not None)

    def _compile_now(self):
        """Compile whatever's been scraped so far (for the CURRENTLY running
        job) into a MAIN leads file, without stopping/pausing the batch —
        useful mid-way through a big run (e.g. 312/3849 towns done)."""
        run_dir = fmt = query = None
        if self._active_backend is not None:
            b = self._active_backend
            run_dir, fmt, query = b.run_dir, b.outputformat, b.base_query
        elif self._active_web_run is not None:
            r = self._active_web_run
            run_dir, fmt, query = r["run_dir"], r["fmt"], r["query"]
        else:
            self.__log("No job is running right now — use \"📁 Compile a "
                       "folder…\" in the History tab to compile an older one.")
            return

        self.__log(f"Compiling progress so far ({os.path.basename(run_dir)}) "
                   f"into a MAIN leads file...")

        def work():
            try:
                result = leadfiles.compile_folder(run_dir, fmt, query)
                if result:
                    path, n = result
                    self.__log(f"★ MAIN file updated: {os.path.basename(path)} "
                               f"— {n} clean leads so far.")
                    history.add_entry(
                        query=query, source="MAIN compile (manual)",
                        scope="Compiled mid-run", records=n,
                        output_file=path, status="Success")
                else:
                    self.__log("No leads with an email/phone found yet to compile.")
            except Exception as e:
                self.__log(f"Could not compile: {e}")
            self.root.after(0, self._refresh_history)

        threading.Thread(target=work, daemon=True).start()

    def _compile_folder_dialog(self):
        """Pick ANY search's output folder and compile it into a MAIN leads
        file — for a batch that finished (or was closed) before it got the
        chance to auto-compile, or just to re-compile after adding files."""
        folder = filedialog.askdirectory(
            initialdir=OUTPUT_PATH if os.path.exists(OUTPUT_PATH) else ".",
            title="Pick a search's output folder to compile")
        if not folder:
            return
        fmt = (getattr(self, "outputFormatVar", None) and
              self.outputFormatVar.get() or "excel").lower()
        query = os.path.basename(folder.rstrip("/\\")) or "leads"

        self.__log(f"Compiling \"{query}\" → MAIN leads file...")

        def work():
            try:
                result = leadfiles.compile_folder(folder, fmt, query)
                if result:
                    path, n = result
                    self.__log(f"★ MAIN file ready: {os.path.basename(path)} "
                               f"— {n} clean leads.")
                    history.add_entry(
                        query=query, source="MAIN compile (manual)",
                        scope="Compiled from History tab", records=n,
                        output_file=path, status="Success")
                else:
                    self.__log(f"No leads with an email/phone found in \"{query}\".")
            except Exception as e:
                self.__log(f"Could not compile: {e}")
            self.root.after(0, self._refresh_history)

        threading.Thread(target=work, daemon=True).start()

    # ── Web logic ─────────────────────────────────────────────────────────────
    def _parse_web_max(self):
        raw = self.webMaxVar.get().strip()
        if not raw or raw.lower() == "unlimited":
            return 999999
        try:
            return max(1, int(raw))
        except ValueError:
            return 50

    def _web_submit(self):
        query = self.webQueryVar.get().strip()
        fmt   = self.webFormatVar.get()

        if not query:
            self.__log("Please enter a search query.")
            return
        if not fmt:
            self.__log("Please select an output format.")
            return

        selected_cities = [h for h in self._city_hoods
                          if self._city_vars.get(h) and self._city_vars[h].get()]
        region_label = self._geo_region_label
        max_results = self._parse_web_max()

        if not self._maps_busy:
            Common.resume()   # clear any stale pause flag from a previous run
        self._web_busy = True
        self.web_btn.set_state(False, "⏳  Searching the web...")
        if hasattr(self, "web_pause_btn"):
            self.web_pause_btn.set_state(True, "⏸  Pause")
        self._status_on = True
        self.status_dot.config(fg=self.C["success"])

        if selected_cities:
            self.__log(f"Location mode: {len(selected_cities)} cities in "
                       f"{region_label} → {len(selected_cities)} web-search files, "
                       f"all merged into MAIN. (Max {max_results} sites/city, "
                       f"duplicate domains skipped across cities.)")
            threading.Thread(
                target=self._run_web_locations,
                args=(query, fmt, selected_cities, region_label, max_results),
                kwargs={"resume_completed": set()},
                daemon=True).start()
        else:
            def run():
                WebSearchBackend(
                    query=query.lower(), output_format=fmt.lower(),
                    max_results=max_results, on_done=self._end_web,
                ).run()

            threading.Thread(target=run, daemon=True).start()

    def _run_web_locations(self, query, fmt, cities, region_label, max_results,
                           resume_completed=None):
        """Run one Web Search per selected city, tick each done, then compile
        a clean MAIN leads file for the whole batch (mirrors Maps city mode).

        A shared `global_seen_domains` set is passed to every city's search so
        a business already scraped for one city (e.g. a chain) isn't re-scraped
        for the next — saves time across a big batch."""
        run_dir = leadfiles.run_folder(f"{query} {region_label}".strip())
        total = len(cities)
        resume_completed = set(resume_completed or [])
        completed = list(resume_completed)
        global_seen_domains = set()
        self._active_web_run = {"run_dir": run_dir, "fmt": fmt.lower(), "query": query}
        self.root.after(0, self._sync_compile_buttons)
        self.update_progress(len(completed), total,
                             f"{region_label}: {len(completed)}/{total} cities")

        for index, city in enumerate(cities, start=1):
            if Common.close_thread_is_set():
                break
            Common.wait_if_paused()
            if Common.close_thread_is_set():
                break

            if city in resume_completed:
                self.mark_location_status(city, "✓ done (resumed)")
                self.update_progress(index, total, f"{region_label}: {index}/{total} done")
                continue

            first_part = region_label.split(",")[0].strip().lower()
            if city.strip().lower() == first_part:
                city_query = f"{query} in {region_label}".strip()
            else:
                city_query = f"{query} in {city}, {region_label}".strip()

            self.mark_location_status(city, "searching...")
            self.update_progress(index - 1, total,
                                 f"Web search {index}/{total}: {city}")
            self.__log(f"[{index}/{total}]  {city}  →  {city_query}")

            # WebSearchBackend.run() is synchronous — it saves and returns.
            backend = WebSearchBackend(
                query=city_query.lower(), output_format=fmt.lower(),
                max_results=max_results, on_done=lambda: None, output_dir=run_dir,
                global_seen_domains=global_seen_domains)
            try:
                backend.run()
            except Exception as ex:
                self.__log(f"Web search error for '{city}': {str(ex)[:120]}")

            record_count = len(backend.results)
            self.mark_location_status(city, f"✓ done ({record_count})")
            self.update_progress(index, total, f"{region_label}: {index}/{total} done")

            completed.append(city)
            jobstate.save(query, region_label, fmt.lower(), None, False,
                         cities, completed, mode="web", max_results=max_results)

        if len(completed) >= total:
            jobstate.clear()

        self.mark_city_done(region_label)

        self.__log("Compiling all files into one clean MAIN leads file...")
        try:
            result = leadfiles.compile_folder(run_dir, fmt.lower(), query)
            if result:
                path, n = result
                self.__log(f"★ MAIN file ready: {os.path.basename(path)}  —  "
                           f"{n} clean leads (email/phone only).")
                history.add_entry(
                    query=query, source="MAIN compile (Web Search)",
                    scope=region_label, records=n, output_file=path,
                    status="Success")
            else:
                self.__log("No leads with an email/phone found to compile into MAIN.")
        except Exception as e:
            self.__log(f"Could not compile MAIN file: {e}")

        self._end_web()

    def _end_web(self):
        self._web_busy = False
        self._status_on = False
        self._active_web_run = None
        if not self._maps_busy:
            Common.resume()   # don't leave the next run stuck paused
        self._sync_pause_buttons()
        self._sync_compile_buttons()
        if hasattr(self, "web_btn"):
            self.web_btn.set_state(True, "▶   Start Web Search")
        if hasattr(self, "status_dot"):
            self.status_dot.config(fg=self.C["border"])
        self._refresh_history()

    # ── Direction helper ────────────────────────────────────────────────────────
    def _toggle_all_directions(self):
        value = self.selectAllVar.get()
        for var in self.directionVars.values():
            var.set(value)

    # ── Location: Country → State → City (offline dataset) ────────────────────────
    def _autocomplete(self, parent, textvar, source_fn, on_select, width=22):
        """A type-to-filter box: an Entry with a Listbox that drops down as you
        type. The Listbox never steals focus, so typing keeps working; click an
        item (or Enter) to pick it."""
        C = self.C
        box = tk.Frame(parent, bg=C["border"])
        inner = tk.Frame(box, bg=C["input"])
        inner.pack(padx=1, pady=1)
        entry = tk.Entry(inner, textvariable=textvar, font=("Segoe UI", 10),
                         bg=C["input"], fg=C["text"], insertbackground=C["accent"],
                         relief="flat", width=width)
        entry.pack(side="left", fill="x", ipady=5, padx=(8, 0))

        # Dropdown-arrow button — click it to see the FULL list without typing.
        arrow = tk.Label(inner, text="▾", font=("Segoe UI", 10), fg=C["dim"],
                         bg=C["input"], cursor="hand2", padx=6)
        arrow.pack(side="left")

        lb = tk.Listbox(self._geo_card, font=("Segoe UI", 10), height=8,
                        bg=C["surface"], fg=C["text"],
                        selectbackground=C["accent_soft"], selectforeground=C["text"],
                        relief="solid", bd=1, highlightthickness=0,
                        activestyle="none", exportselection=False)

        def hide():
            lb.place_forget()

        def show(items):
            lb.delete(0, tk.END)
            for it in items[:60]:
                lb.insert(tk.END, it)
            if items:
                lb.place(in_=entry, x=0, rely=1.0, y=2, relwidth=1.0)
                lb.lift()
            else:
                hide()

        def show_all(_=None):
            entry.focus_set()
            show(list(source_fn() or []))

        def on_key(e):
            if e.keysym in ("Return", "Tab", "Escape"):
                hide()
                return
            if e.keysym == "Down" and lb.winfo_ismapped():
                lb.focus_set()
                if not lb.curselection():
                    lb.selection_set(0)
                    lb.activate(0)
                return
            typed = textvar.get().strip().lower()
            src = source_fn() or []
            matches = [x for x in src if typed in x.lower()] if typed else list(src)
            show(matches)

        def pick(_=None):
            sel = lb.curselection()
            if sel:
                textvar.set(lb.get(sel[0]))
            hide()
            entry.focus_set()
            entry.icursor(tk.END)
            if on_select:
                on_select()

        entry.bind("<KeyRelease>", on_key)
        entry.bind("<FocusOut>", lambda e: box.after(250, hide))
        arrow.bind("<Button-1>", show_all)
        lb.bind("<ButtonRelease-1>", pick)
        lb.bind("<Return>", pick)
        return box

    def _state_source(self):
        states = geodata.get_states(self.cityCountryVar.get().strip())
        return (["★ All cities in country"] + states) if states else states

    def _build_geo_section(self, card):
        """Builds the Country/State/City picker. Safe to call once per tab that
        wants it (Maps + Web Search) — all instances share the same underlying
        selection (self._city_hoods / _city_vars / _city_status), so ticking a
        city on one tab is reflected on the other too."""
        C = self.C
        self._geo_card = card
        tk.Frame(card, bg=C["card"], height=6).pack()
        self._section_label(
            card, "📍  Location  (Country ▸ State ▸ City)",
            "Pick a country, then a state — its cities appear as checkboxes below. "
            "Tick the cities you want (or Select All). Each city becomes its own "
            "file, all merged into MAIN. Leave blank to just search your query once.")

        rowf = tk.Frame(card, bg=C["card"])
        rowf.pack(fill="x", padx=20)
        self._autocomplete(rowf, self.cityCountryVar, geodata.get_countries,
                           self._on_country_pick, 22).pack(side="left")
        tk.Label(rowf, text="  ▸  ", font=("Segoe UI", 11, "bold"),
                 fg=C["dim"], bg=C["card"]).pack(side="left")
        self._autocomplete(rowf, self.stateVar, self._state_source,
                           self._on_state_pick, 22).pack(side="left")

        done_lbl = tk.Label(
            card, text=self._city_done_text, font=("Segoe UI", 9, "bold"),
            fg=C["success"], bg=C["card"], anchor="w")
        done_lbl.pack(fill="x", padx=20, pady=(6, 0))
        self._city_done_lbls.append(done_lbl)

        # City checklist: search + select all + list
        search_row = tk.Frame(card, bg=C["card"])
        tk.Label(search_row, text="Search cities:",
                 font=("Segoe UI", 9), fg=C["dim"], bg=C["card"]).pack(side="left")
        loc_search = tk.Entry(search_row, textvariable=self.locSearchVar,
                              font=("Segoe UI", 10), bg=C["input"], fg=C["text"],
                              insertbackground=C["accent"], relief="flat", width=24)
        loc_search.pack(side="left", padx=(8, 0), ipady=3)
        loc_search.bind("<KeyRelease>", lambda e: self._render_locations())
        self._loc_search_rows.append(search_row)

        select_all = tk.Checkbutton(
            card, text="Select All Cities", variable=self.selectAllLocVar,
            command=self._toggle_all_locations, font=("Segoe UI", 9, "bold"),
            fg=C["accent"], bg=C["card"], activebackground=C["card"],
            activeforeground=C["accent"], selectcolor=C["border"], relief="flat",
            highlightthickness=0, anchor="w")
        self._loc_select_alls.append(select_all)

        list_frame = tk.Frame(card, bg=C["card"])
        list_frame.pack(fill="x", padx=20, pady=(2, 0))
        self._loc_list_frames.append(list_frame)
        self._render_locations()

    def _on_country_pick(self):
        self.stateVar.set("")
        self._geo_region_label = ""
        self._city_hoods = []
        self._city_vars = {}
        self._city_status = {}
        self._city_done_text = ""
        for lbl in self._city_done_lbls:
            lbl.config(text="")
        self._render_locations()

    def _on_state_pick(self):
        country = self.cityCountryVar.get().strip()
        state = self.stateVar.get().strip()
        if not country or not state:
            return
        if state.startswith("★"):
            cities = geodata.all_cities(country)
            self._geo_region_label = country
        else:
            cities = geodata.get_cities(country, state)
            self._geo_region_label = f"{state}, {country}"
        self._city_hoods = cities
        self._city_vars = {c: tk.IntVar(value=1) for c in cities}
        self._city_status = {c: "queued" for c in cities}
        self._city_done_text = ""
        self.locSearchVar.set("")
        for lbl in self._city_done_lbls:
            lbl.config(text="")
        self._render_locations()
        self.__log(f"{len(cities)} cities loaded for {self._geo_region_label}. "
                   f"Tick the ones you want (or Select All), then Start Scraping.")

    def _render_locations(self):
        """Rebuilds the city checklist in EVERY tab that has the picker
        (Maps + Web Search), since they all share the same selection."""
        if not self._loc_list_frames:
            return
        self._loc_rows = {}   # city -> list of status Labels, one per tab
        C = self.C

        query = self.locSearchVar.get().strip().lower()
        visible = [h for h in self._city_hoods if query in h.lower()]
        CAP = 400
        shown = visible[:CAP]
        note = (f"{len(visible)} of {len(self._city_hoods)} cities"
                + (f" — showing first {CAP}, use search to find others"
                   if len(visible) > CAP else "")
                + "  (checked ones will be scraped):")

        for idx, list_frame in enumerate(self._loc_list_frames):
            for w in list_frame.winfo_children():
                w.destroy()

            search_row = self._loc_search_rows[idx]
            select_all = self._loc_select_alls[idx]

            if not self._city_hoods:
                search_row.pack_forget()
                select_all.pack_forget()
                continue

            search_row.pack(anchor="w", padx=20, pady=(8, 2), before=list_frame)
            select_all.pack(anchor="w", padx=20, pady=(2, 2), before=list_frame)

            tk.Label(list_frame, text=note, font=("Segoe UI", 8),
                     fg=C["dim"], bg=C["card"], anchor="w").pack(fill="x")

            # Grid of columns to use the full width (not one item per row)
            gridf = tk.Frame(list_frame, bg=C["card"])
            gridf.pack(fill="x")
            cols = 3
            for c in range(cols):
                gridf.columnconfigure(c, weight=1, uniform="loc")

            for i, h in enumerate(shown):
                var = self._city_vars.get(h)
                if var is None:
                    var = tk.IntVar(value=1)
                    self._city_vars[h] = var
                cell = tk.Frame(gridf, bg=C["card"])
                r, c = divmod(i, cols)
                cell.grid(row=r, column=c, sticky="w", padx=(0, 14), pady=1)
                tk.Checkbutton(cell, text=h, variable=var, font=("Segoe UI", 9),
                               fg=C["text"], bg=C["card"], activebackground=C["card"],
                               activeforeground=C["accent"], selectcolor=C["border"],
                               relief="flat", highlightthickness=0,
                               anchor="w").pack(side="left")
                status = self._city_status.get(h, "queued")
                st = tk.Label(cell, text=status, font=("Segoe UI", 8), fg=C["dim"],
                              bg=C["card"])
                st.pack(side="left", padx=(4, 0))
                self._loc_rows.setdefault(h, []).append(st)

    def _toggle_all_locations(self):
        value = self.selectAllLocVar.get()
        for var in self._city_vars.values():
            var.set(value)

    # Called from the backend (worker thread) to tick rows done
    def mark_location_status(self, name, status):
        self.root.after(0, self._set_loc_status, name, status)

    def _set_loc_status(self, name, status):
        self._city_status[name] = status
        labels = self._loc_rows.get(name) or []
        if not labels:
            return
        if status.startswith("✓"):
            color = self.C["success"]
        elif "scraping" in status:
            color = self.C["accent"]
        elif status.startswith("✗"):
            color = self.C.get("warning", self.C["dim"])
        else:
            color = self.C["dim"]
        for lbl in labels:
            lbl.config(text=status, fg=color)

    def mark_city_done(self, name):
        self.root.after(0, self._set_city_done, name)

    def _set_city_done(self, name):
        self._city_done_text = f"✓  {name} — all cities done"
        for lbl in self._city_done_lbls:
            lbl.config(text=self._city_done_text, fg=self.C["success"])

    # ── Logs viewer ─────────────────────────────────────────────────────────────
    def _open_logs_window(self):
        C = self.C
        win = tk.Toplevel(self.root)
        win.title("Logs — LeadScrapper")
        win.geometry("860x580")
        win.configure(bg=C["bg"])
        try:
            if hasattr(self, "_app_icon"):
                win.iconphoto(True, self._app_icon)
        except Exception:
            pass

        top = tk.Frame(win, bg=C["bg"])
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(top, text="Application Logs", font=("Segoe UI", 12, "bold"),
                 fg=C["text"], bg=C["bg"]).pack(side="left")
        tk.Label(top, text=applog.log_path(), font=("Segoe UI", 8),
                 fg=C["dim"], bg=C["bg"]).pack(side="left", padx=(10, 0))

        body = tk.Frame(win, bg=C["card"])
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        txt = tk.Text(body, font=("Consolas", 9), bg=C["card"], fg=C["log_fg"],
                      wrap="none", relief="flat", bd=0, padx=10, pady=8)
        yb = ttk.Scrollbar(body, orient="vertical", command=txt.yview,
                           style="Dark.Vertical.TScrollbar")
        txt.configure(yscrollcommand=yb.set)
        yb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        def refresh():
            txt.config(state="normal")
            txt.delete("1.0", tk.END)
            txt.insert(tk.END, applog.read_log())
            txt.see(tk.END)
            txt.config(state="disabled")

        def open_file():
            try:
                import os
                os.startfile(applog.log_path())   # Windows
            except Exception:
                pass

        rb = tk.Label(top, text="⟳  Refresh", font=("Segoe UI", 9, "bold"),
                      fg=C["accent"], bg=C["accent_soft"], padx=10, pady=3,
                      cursor="hand2")
        rb.pack(side="right", padx=(8, 0))
        rb.bind("<Button-1>", lambda e: refresh())
        ob = tk.Label(top, text="📂  Open file", font=("Segoe UI", 9, "bold"),
                      fg=C["accent"], bg=C["accent_soft"], padx=10, pady=3,
                      cursor="hand2")
        ob.pack(side="right", padx=(8, 0))
        ob.bind("<Button-1>", lambda e: open_file())

        refresh()

    # ── Fullscreen ──────────────────────────────────────────────────────────────
    def _toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        self.root.attributes("-fullscreen", self._is_fullscreen)

    def _exit_fullscreen(self):
        if self._is_fullscreen:
            self._is_fullscreen = False
            self.root.attributes("-fullscreen", False)

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
