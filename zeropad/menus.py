import tkinter as tk
from tkinter import messagebox

class Menus:
    def init_menus(self):
        palette = getattr(self, "_palette", {})
        BG_PANEL = palette.get("BG_PANEL", "#111827")
        FG_TEXT  = palette.get("FG_TEXT",  "#e5e7eb")

        menubar = tk.Menu(self, bg=BG_PANEL, fg=FG_TEXT,
                          activebackground="#1f2937", activeforeground=FG_TEXT, bd=0, tearoff=False)
        self.config(menu=menubar)

        # ----- File menu -----
        filem = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT,
                        activebackground="#1f2937", activeforeground=FG_TEXT)

        filem.add_command(label="New",          accelerator="Ctrl+N",
                          command=lambda: self._call_if("file_new"))
        filem.add_command(label="Open…",        accelerator="Ctrl+O",
                          command=lambda: self._call_if("file_open_dialog"))
        filem.add_separator()
        filem.add_command(label="Save",         accelerator="Ctrl+S",
                          command=lambda: self._call_if("file_save"))
        filem.add_command(label="Save As…",     accelerator="Ctrl+Shift+S",
                          command=lambda: self._call_if("file_save_as"))
        filem.add_command(label="Revert",       accelerator="Ctrl+R",
                          command=lambda: self._call_if("file_revert"))
        filem.add_separator()
        filem.add_command(label="Close Tab",    accelerator="Ctrl+W",
                          command=lambda: self._call_if("file_close_active_tab"))
        filem.add_separator()
        filem.add_command(label="Exit",         accelerator="Ctrl+Q",
                          command=self._menu_exit)
        menubar.add_cascade(label="File", menu=filem)

        # ----- Edit / Settings placeholders -----
        menubar.add_cascade(label="Edit",
                            menu=tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT,
                                         activebackground="#1f2937", activeforeground=FG_TEXT))
        menubar.add_cascade(label="Settings",
                            menu=tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT,
                                         activebackground="#1f2937", activeforeground=FG_TEXT))

        # ----- Toggle menu -----
        toggle = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT,
                         activebackground="#1f2937", activeforeground=FG_TEXT)
        menubar.add_cascade(label="Toggle", menu=toggle)
        toggle.add_checkbutton(label="File Manager", variable=self.show_file_manager, command=self.toggle_file_manager)
        toggle.add_checkbutton(label="Text Editor",  variable=self.show_text_editor,  command=self.toggle_text_editor)
        toggle.add_checkbutton(label="Terminal",     variable=self.show_terminal,     command=self.toggle_terminal)

        # ----- Keyboard shortcuts (global) -----
        self.bind_all("<Control-n>",       lambda e: self._call_if("file_new"))
        self.bind_all("<Control-o>",       lambda e: self._call_if("file_open_dialog"))
        self.bind_all("<Control-s>",       lambda e: self._call_if("file_save"))
        self.bind_all("<Control-S>",       lambda e: self._call_if("file_save_as"))   # some X servers send this
        self.bind_all("<Control-Shift-s>", lambda e: self._call_if("file_save_as"))
        self.bind_all("<Control-r>",       lambda e: self._call_if("file_revert"))
        self.bind_all("<Control-w>",       lambda e: self._call_if("file_close_active_tab"))
        self.bind_all("<Control-q>",       lambda e: self._menu_exit())
        self.bind_all("<Control-a>",       lambda e: self._call_if("file_select_all"))

    # Utility: safely call a method if present
    def _call_if(self, name):
        fn = getattr(self, name, None)
        if callable(fn):
            return fn()
        messagebox.showwarning("Not available", f"Action '{name}' is not wired up yet.")

    def _menu_exit(self):
        fn = getattr(self, "exit_app", None)
        if callable(fn):
            fn()
        else:
            self.destroy()
