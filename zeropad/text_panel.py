import tkinter as tk
from tkinter import ttk

class TextPanel:
    def init_text_panel(self):
        # Create the top editor (green) inside the existing right vpaned
        self.editor = tk.Frame(self.vpaned, bg="#22c55e")  # green