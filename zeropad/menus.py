import tkinter as tk

class Menus:
    def init_menus(self):
        palette = getattr(self, "_palette", {})
        BG_PANEL = palette.get("BG_PANEL", "#111827")
        FG_TEXT  = palette.get("FG_TEXT",  "#e5e7eb")

        menubar = tk.Menu(self, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937", activeforeground=FG_TEXT, bd=0)
        self.config(menu=menubar)

        menubar.add_cascade(label="File",     menu=tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937"))
        menubar.add_cascade(label="Edit",     menu=tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937"))
        menubar.add_cascade(label="Settings", menu=tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937"))

        toggle = tk.Menu(menubar, tearoff=False, bg=BG_PANEL, fg=FG_TEXT, activebackground="#1f2937")
        menubar.add_cascade(label="Toggle", menu=toggle)
        toggle.add_checkbutton(label="File Manager", variable=self.show_file_manager, command=self.toggle_file_manager)
        toggle.add_checkbutton(label="Text Editor",   variable=self.show_text_editor,  command=self.toggle_text_editor)
        toggle.add_checkbutton(label="Terminal",      variable=self.show_terminal,     command=self.toggle_terminal)
