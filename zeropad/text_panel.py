import tkinter as tk
from tkinter import ttk

class TextPanel:
    def init_text_panel(self):
        # Create the top editor (green) inside the existing right vpaned
        self.editor = tk.Frame(self.vpaned, bg="#22c55e")  # green

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
