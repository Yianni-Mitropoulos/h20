import os
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from menus import Menus
from file_panel import FilePanel
from text_panel import TextPanel
from terminal_panel import TerminalPanel
from splits import RatioSplitController


class Zeropad(Menus, FilePanel, TextPanel, TerminalPanel, tk.Tk):
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
        style.configure("Treeview", background=BG_PANEL, fieldbackground=BG_PANEL, foreground=FG_TEXT, borderwidth=0)
        style.map("Treeview", background=[("selected", "#1f2937")], foreground=[("selected", FG_TEXT)])
        try:
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
        self.cwd = Path.home()
        self.cwd_var = tk.StringVar(value=str(self.cwd))
        tk.Label(self.status, textvariable=self.cwd_var, anchor="w", bg=BG_STATUS, fg=FG_TEXT, padx=8)\
          .pack(side="left", fill="y")

        # -------- Main layout: Panedwindows --------
        self.hpaned = ttk.Panedwindow(self, orient="horizontal")
        self.hpaned.pack(side="top", fill="both", expand=True)

        self.vpaned = ttk.Panedwindow(self.hpaned, orient="vertical")

        # -------- State for toggles --------
        self.show_file_manager = tk.BooleanVar(value=True)
        self.show_text_editor  = tk.BooleanVar(value=True)
        self.show_terminal     = tk.BooleanVar(value=True)

        # -------- Create panels (from mixins) --------
        self.init_file_panel()     # defines self.fm, tree, metadata editor, etc.
        self.hpaned.add(self.vpaned)

        self.init_text_panel()     # defines self.editor
        self.init_terminal_panel() # defines self.terminal

        # Initial attach (all enabled by default)
        self.hpaned.insert(0, self.fm)
        self.vpaned.add(self.editor)
        self.vpaned.add(self.terminal)

        # -------- Ratio controllers --------
        self.hsplit = RatioSplitController(self.hpaned, "horizontal", initial_ratio=0.25)
        self.vsplit = RatioSplitController(self.vpaned, "vertical",   initial_ratio=0.62)

        # -------- Menus --------
        self.init_menus()

        # Prime initial sash positions and initial file panel load
        self.after_idle(self._init_sashes)
        self.after_idle(self.refresh_file_panel)

    # -------- Utilities shared by panels/menus --------
    @staticmethod
    def _contains(paned: ttk.Panedwindow, w: tk.Widget) -> bool:
        try:
            return str(w) in paned.panes()
        except Exception:
            return False

    def _init_sashes(self):
        self.hsplit.restore_ratio_async()
        self.vsplit.restore_ratio_async()

    # -------- Centralized CWD management (kept in main, as requested) --------
    def set_cwd(self, new_path: Path):
        """Set the app's logical CWD and notify panels."""
        try:
            p = Path(new_path).expanduser().resolve()
        except Exception:
            return
        if not p.exists() or not p.is_dir():
            return
        self.cwd = p
        self.cwd_var.set(str(self.cwd))
        self.refresh_file_panel()

    # ========================
    # Toggle handlers (centralized here)
    # ========================
    def toggle_file_manager(self):
        self.hsplit.remember_ratio()

        if self.show_file_manager.get():
            if not self._contains(self.hpaned, self.fm):
                # ensure FM is the left pane (index 0)
                self.hpaned.insert(0, self.fm)
        else:
            if self._contains(self.hpaned, self.fm):
                self.hpaned.forget(self.fm)

        self.hsplit.restore_ratio_async()

    def toggle_text_editor(self):
        self.vsplit.remember_ratio()

        want_editor = self.show_text_editor.get()
        has_editor  = self._contains(self.vpaned, self.editor)
        has_term    = self._contains(self.vpaned, self.terminal)

        if want_editor and not has_editor:
            # Keep editor on top (index 0)
            if has_term:
                self.vpaned.insert(0, self.editor)
            else:
                self.vpaned.add(self.editor)
        elif (not want_editor) and has_editor:
            self.vpaned.forget(self.editor)

        self.vsplit.restore_ratio_async()

    def toggle_terminal(self):
        self.vsplit.remember_ratio()

        want_term = self.show_terminal.get()
        has_term  = self._contains(self.vpaned, self.terminal)
        has_edit  = self._contains(self.vpaned, self.editor)

        if want_term and not has_term:
            if has_edit:
                # append after editor (bottom)
                self.vpaned.add(self.terminal)
            else:
                # if editor hidden, terminal can be first
                self.vpaned.insert(0, self.terminal)
        elif (not want_term) and has_term:
            self.vpaned.forget(self.terminal)

        self.vsplit.restore_ratio_async()


if __name__ == "__main__":
    app = Zeropad()
    app.mainloop()
