import tkinter as tk
from tkinter import ttk

class TerminalPanel:
    def init_terminal_panel(self):
        # Create the bottom terminal (blue) inside the existing right vpaned
        self.terminal = tk.Frame(self.vpaned, bg="#3b82f6")  # blue

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
