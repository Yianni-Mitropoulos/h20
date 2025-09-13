import tkinter as tk
from tkinter import ttk

class TerminalPanel:
    def init_terminal_panel(self):
        # Create the bottom terminal (blue) inside the existing right vpaned
        self.terminal = tk.Frame(self.vpaned, bg="#3b82f6")  # blue