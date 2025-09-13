from tkinter import ttk

class RatioSplitController:
    """Keeps a Panedwindow's sash as a ratio and restores it after layout changes."""
    def __init__(self, paned: ttk.Panedwindow, orient: str, initial_ratio: float):
        self.paned = paned
        self.orient = orient  # "horizontal" or "vertical"
        self.last_ratio = max(0.05, min(0.95, initial_ratio))
        self.paned.bind("<ButtonRelease-1>", self._on_sash_release)
        self.paned.bind("<Configure>", self._on_configure)

    def _length(self) -> int:
        if self.orient == "horizontal":
            return max(self.paned.winfo_width(), 1)
        return max(self.paned.winfo_height(), 1)

    def remember_ratio(self):
        if len(self.paned.panes()) < 2:
            return
        try:
            pos = self.paned.sashpos(0)
            L = self._length()
            r = pos / L
            self.last_ratio = max(0.05, min(0.95, r))
        except Exception:
            pass

    def restore_ratio_async(self):
        if len(self.paned.panes()) < 2:
            return

        def do_restore():
            try:
                L = self._length()
                if L <= 2:
                    self.paned.after(16, do_restore)
                    return
                target = int(round(self.last_ratio * L))
                target = max(24, min(L - 24, target))
                self.paned.sashpos(0, target)
            except Exception:
                pass

        self.paned.after_idle(do_restore)

    # events
    def _on_sash_release(self, _e):
        self.remember_ratio()

    def _on_configure(self, _e):
        self.restore_ratio_async()
