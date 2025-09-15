# menus.py
import tkinter as tk
import subprocess
from tkinter import filedialog, messagebox
from pathlib import Path
from editor_io import choose_open_selected  # returns "system" | "zeropad" | None

# integrated “Open Selected” chooser (system vs Zeropad + encoding)

class Menus:
    def init_menus(self):
        palette = getattr(self, "_palette", {})
        BG_PANEL = palette.get("BG_PANEL", "#111827")
        FG_TEXT  = palette.get("FG_TEXT",  "#e5e7eb")

        menubar = tk.Menu(self, bg=BG_PANEL, fg=FG_TEXT,
                          activebackground="#1f2937", activeforeground=FG_TEXT, bd=0, tearoff=False)
        self.config(menu=menubar)

        # ==== FILE =========================================================
        filem = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937")
        menubar.add_cascade(label="File", menu=filem)

        # 1) Text-panel group (hotkeys per spec)
        filem.add_command(label="New",    accelerator="Ctrl+N",       command=self.file_new)
        filem.add_command(label="Save",   accelerator="Ctrl+S",       command=self.file_save)
        filem.add_command(label="Revert", accelerator="Ctrl+Shift+W", command=self.file_revert)
        filem.add_command(label="Close",  accelerator="Ctrl+W",       command=self.file_close_active_tab)

        filem.add_separator()

        # 2) General group
        filem.add_command(label="Open Selected",      accelerator="Ctrl+O",          command=self._menu_open_selected)
        filem.add_command(label="Save Over Selected", accelerator="Ctrl+Shift+S",    command=self.save_over_selected)

        filem.add_separator()

        # 3) CWD helpers
        filem.add_command(label="Copy CWD",   accelerator="Ctrl+L",       command=self._menu_copy_cwd)
        filem.add_command(label="Change CWD", accelerator="Ctrl+Shift+L", command=self._menu_change_cwd)

        filem.add_separator()

        # 4) Exit — mouse only (no accelerator)
        filem.add_command(label="Exit", command=self._menu_exit)

        # ==== EDIT =========================================================
        editm = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937")
        menubar.add_cascade(label="Edit", menu=editm)
        # keep these minimal; Text widget already handles most editing keys
        editm.add_command(label="Select All", accelerator="Ctrl+A", command=self.file_select_all)

        # ==== SETTINGS =====================================================
        settings = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937")
        menubar.add_cascade(label="Settings", menu=settings)
        # put future prefs here

        # ==== TOGGLE (views) ==============================================
        toggle = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937")
        menubar.add_cascade(label="Toggle", menu=toggle)
        toggle.add_checkbutton(label="File Manager", variable=self.show_file_manager, command=self.toggle_file_manager)
        toggle.add_checkbutton(label="Text Editor",   variable=self.show_text_editor,  command=self.toggle_text_editor)
        toggle.add_checkbutton(label="Terminal",      variable=self.show_terminal,     command=self.toggle_terminal)

        # ---- global hotkeys (no fallbacks) ----
        # Text-panel group
        self.bind_all("<Control-n>",        lambda e: (self.file_new(), "break"), add="+")
        self.bind_all("<Control-s>",        lambda e: (self.file_save(), "break"), add="+")
        self.bind_all("<Control-Shift-W>",  lambda e: (self.file_revert(), "break"), add="+")
        self.bind_all("<Control-w>",        lambda e: (self.file_close_active_tab(), "break"), add="+")
        # General group
        self.bind_all("<Control-o>",        lambda e: (self._menu_open_selected(), "break"), add="+")
        self.bind_all("<Control-Shift-S>",  lambda e: (self.save_over_selected(), "break"), add="+")
        # CWD helpers
        self.bind_all("<Control-l>",        lambda e: (self._menu_copy_cwd(), "break"), add="+")
        self.bind_all("<Control-Shift-L>",  lambda e: (self._menu_change_cwd(), "break"), add="+")

    # ======================================================================
    # File menu commands
    # ======================================================================

    def _menu_copy_cwd(self):
        cwd = getattr(self, "cwd", None)
        if not cwd:
            messagebox.showinfo("Copy CWD", "No current working directory.")
            return
        self.clipboard_clear()
        self.clipboard_append(str(cwd))
        self.update_idletasks()
        messagebox.showinfo("Copy CWD", f"Copied to clipboard:\n{cwd}")

    def _menu_change_cwd(self):
        cwd = getattr(self, "cwd", Path.home())
        dirname = filedialog.askdirectory(initialdir=str(cwd), title="Change CWD")
        if not dirname:
            return
        p = Path(dirname)
        if not p.exists() or not p.is_dir():
            messagebox.showerror("Change CWD", "Please select a directory.")
            return
        self.set_cwd(p)

    def _menu_exit(self):
        # Mouse-only per spec — no accelerator binding
        if hasattr(self, "exit_app"):
            self.exit_app()
        else:
            self.destroy()

    def _open_with_system(self, path: Path):
        """Open a file or folder with the OS default handler (cross-platform)."""
        try:
            import sys, os, subprocess
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Open with System Default", f"Could not open:\n{e}")

    def _menu_open_selected(self):
        """Open the currently selected item from the File panel.

        Behavior:
        - Prompt: System default vs Open in Zeropad (same as double-click).
        - If 'system': open via OS default (cross-platform).
        - If 'zeropad': delegate to TextPanel.open_with_zeropad(path).
        """
        # Ask the File panel for the selected path
        if not hasattr(self, "get_selected_path") or not callable(self.get_selected_path):
            messagebox.showerror("Open Selected", "File panel is not available.")
            return

        p = self.get_selected_path()
        if not p:
            messagebox.showinfo("Open Selected", "No file is selected.")
            return
        p = Path(p)

        # Directories: navigate instead of opening
        try:
            if p.is_dir():
                if hasattr(self, "set_cwd"):
                    self.set_cwd(p)
                else:
                    messagebox.showinfo("Open Selected", "Selected item is a folder.")
                return
        except Exception:
            pass

        # Choice dialog (Cancel / System / Zeropad)
        choice = choose_open_selected(self, p)
        if not choice:
            return

        if choice == "system":
            self._open_with_system(p)
            return

        if choice == "zeropad":
            # Let the TextPanel drive encoding selection + open.
            if hasattr(self, "open_with_zeropad") and callable(self.open_with_zeropad):
                # Defer slightly so focus/grab transitions feel clean.
                self.after_idle(lambda: self.open_with_zeropad(p))
            else:
                messagebox.showerror("Open in Zeropad", "Text editor is not available.")
            return