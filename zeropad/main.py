import tkinter as tk
from tkinter import ttk
from pathlib import Path

from menus import Menus
from file_panel import FilePanel
from text_panel import TextPanel
from terminal_panel import TerminalPanel
from splits import RatioSplitController


class Zeropad(tk.Tk, Menus, FilePanel, TextPanel, TerminalPanel):
    def __init__(self):
        super().__init__()
        self.title("Zeropad")
        self.minsize(900, 600)

        # -------- Dark theme (global) --------
        BG         = "#0b1220"  # window background
        BG_PANEL   = "#111827"  # panedwindow/frames background
        BG_STATUS  = "#0f172a"  # status bar
        FG_TEXT    = "#e5e7eb"

        self._palette = dict(BG=BG, BG_PANEL=BG_PANEL, BG_STATUS=BG_STATUS, FG_TEXT=FG_TEXT)
        self.configure(bg=BG)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG_PANEL, foreground=FG_TEXT)
        style.configure("TFrame", background=BG_PANEL)
        style.configure("TPanedwindow", background=BG_PANEL, borderwidth=0)
        try:
            # wider, flat-looking sashes (ttk is limited; this works on clam)
            self.tk.call("ttk::style", "configure", "TPanedwindow", "-sashrelief", "flat")
            self.tk.call("ttk::style", "configure", "TPanedwindow", "-sashwidth", 8)
        except tk.TclError:
            pass

        # Native Tk menus via option DB (dark)
        self.option_add("*Menu*background", BG_PANEL)
        self.option_add("*Menu*foreground", FG_TEXT)
        self.option_add("*Menu*activeBackground", "#1f2937")
        self.option_add("*Menu*activeForeground", FG_TEXT)
        self.option_add("*tearOff", False)

        # -------- Bottom fixed CWD status bar (non-toggleable) --------
        self.status = tk.Frame(self, height=28, bg=BG_STATUS, highlightthickness=0, bd=0)
        self.status.pack(side="bottom", fill="x")
        self.status.pack_propagate(False)
        self.cwd_var = tk.StringVar(value=str(Path.home()))
        tk.Label(self.status, textvariable=self.cwd_var, anchor="w", bg=BG_STATUS, fg=FG_TEXT, padx=8)\
          .pack(side="left", fill="y")

        # -------- Main layout: Panedwindows --------
        # Root horizontal split (left: File Panel, right: vertical split container)
        self.hpaned = ttk.Panedwindow(self, orient="horizontal")
        self.hpaned.pack(side="top", fill="both", expand=True)

        # Right vertical split (top: Text Panel, bottom: Terminal Panel)
        self.vpaned = ttk.Panedwindow(self.hpaned, orient="vertical")

        # -------- State for toggles --------
        self.show_file_manager = tk.BooleanVar(value=True)
        self.show_text_editor  = tk.BooleanVar(value=True)
        self.show_terminal     = tk.BooleanVar(value=True)

        # -------- Create panels (from mixins) --------
        self.init_file_panel()     # defines self.fm (red frame)
        # Attach right container once; children added by their mixins
        self.hpaned.add(self.vpaned)

        self.init_text_panel()     # defines self.editor (green frame)
        self.init_terminal_panel() # defines self.terminal (blue frame)

        # Initial attach (all enabled by default)
        self.hpaned.insert(0, self.fm)
        self.vpaned.add(self.editor)
        self.vpaned.add(self.terminal)

        # -------- Ratio controllers (remember/restore sash positions) --------
        self.hsplit = RatioSplitController(self.hpaned, "horizontal", initial_ratio=0.25)
        self.vsplit = RatioSplitController(self.vpaned, "vertical",   initial_ratio=0.62)

        # -------- Menus (from mixin) --------
        self.init_menus()

        # Prime initial sash positions
        self.after_idle(self._init_sashes)

    # -------- Utilities shared by mixins --------
    @staticmethod
    def _contains(paned: ttk.Panedwindow, w: tk.Widget) -> bool:
        try:
            return str(w) in paned.panes()
        except Exception:
            return False

    def _init_sashes(self):
        self.hsplit.restore_ratio_async()
        self.vsplit.restore_ratio_async()


if __name__ == "__main__":
    app = Zeropad()
    app.mainloop()
