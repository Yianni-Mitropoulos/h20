import tkinter as tk
from tkinter import ttk

class FilePanel:
    def init_file_panel(self):
        # Create the left file panel (red)
        self.fm = tk.Frame(self.hpaned, bg="#ef4444")  # red

    # Toggle handler
    def toggle_file_manager(self):
        self.hsplit.remember_ratio()

        if self.show_file_manager.get():
            if not self._contains(self.hpaned, self.fm):
                # ensure File Manager stays on the left (index 0)
                self.hpaned.insert(0, self.fm)
        else:
            if self._contains(self.hpaned, self.fm):
                self.hpaned.forget(self.fm)

        self.hsplit.restore_ratio_async()
