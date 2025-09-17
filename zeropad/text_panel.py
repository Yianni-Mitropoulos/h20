# text_panel.py
from __future__ import annotations
import time
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Set

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

from basic_string_safety_utils import suspicious_line, exists_outside_printable_ascii_plane
from editor_io import *

# =========================
# Palette / Theme Constants
# =========================
DARK_BG      = "#0b1220"
DARK_PANEL   = "#111827"
DARK_PANEL_2 = "#0f172a"
FG_TEXT      = "#e5e7eb"
FG_DIM       = "#9ca3af"
FG_WARN      = "#ef4444"
FG_OK        = "#34d399"

SAFE_FACE_BAD = "😡"
SAFE_FACE_MED = "😐"
SAFE_FACE_OK  = "🙂"

# Repaint throttles
REPAINT_FAST_MS = 60
REPAINT_SLOW_MS = 140
REPAINT_HUGE_MS = 260

# Injectivity recompute minima (heavier O(n) work)
INJ_MIN_INTERVAL_SMALL = 0.30   # seconds (small/medium files)
INJ_MIN_INTERVAL_MED   = 0.80
INJ_MIN_INTERVAL_LARGE = 1.60


class TextPanel:
    """
    Dark-themed, tabbed text editor panel with:
    • Fixed “+” tab (index 0) to create new tabs.
    • Line-number and safety gutters (flags suspicious characters per line).
    • Status bar with path[*], cursor position, total lines, encoding.
    • File actions: new/open/save/save-as/revert/close/select-all, plus
        “open selected” and “save over selected”.
    """

    # Public API expected on the app/toplevel:
    #   file_new, file_open_dialog, file_save, file_save_as, file_revert,
    #   file_close_active_tab, file_select_all

    def init_text_panel(self):
        """Build the right-side Text panel."""
        # Outer frame added by main to vpaned
        self.editor = tk.Frame(self.vpaned, bg=DARK_PANEL)
        self.editor.grid_propagate(False)

        # Styles
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=DARK_PANEL, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=DARK_PANEL,
            foreground=FG_TEXT,
            padding=(12, 6),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", DARK_PANEL_2), ("active", "#162033")],
            foreground=[("disabled", FG_DIM)],
        )
        style.layout(
            "TNotebook.Tab",
            [
                (
                    "Notebook.tab",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Notebook.padding",
                                {
                                    "side": "top",
                                    "sticky": "nswe",
                                    "children": [("Notebook.label", {"sticky": ""})],
                                },
                            )
                        ],
                    },
                )
            ],
        )

        # Notebook
        self._nb = ttk.Notebook(self.editor)
        self._nb.grid(row=0, column=0, sticky="nsew")
        self.editor.grid_rowconfigure(0, weight=1)
        self.editor.grid_columnconfigure(0, weight=1)

        # Bottom status bar
        self._status = tk.Frame(self.editor, bg=DARK_PANEL_2, height=26)
        self._status.grid(row=1, column=0, sticky="ew")
        self._status.grid_propagate(False)

        # Status: left path[*]
        self._status_path_var = tk.StringVar(value="")
        self._status_path = tk.Label(
            self._status,
            textvariable=self._status_path_var,
            bg=DARK_PANEL_2,
            fg=FG_TEXT,
            anchor="w",
            padx=8,
        )
        self._status_path.pack(side="left", fill="x", expand=True)

        # Status: right info (line/col | total lines | encoding)
        self._status_info = tk.Label(
            self._status, text="", bg=DARK_PANEL_2, fg=FG_DIM, padx=8
        )
        self._status_info.pack(side="right")

        # Tabs model: tid -> dict
        self._tabs: Dict[int, Dict] = {}

        # Fixed "+" tab at index 0
        self._plus_tab = tk.Frame(self._nb, bg=DARK_PANEL)
        self._nb.add(self._plus_tab, text="  +  ")
        self._nb.enable_traversal()
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")

        # High-priority close/new binding on tab press
        self._install_nb_close_binding()

        # Create initial empty tab
        self._create_empty_tab_and_select()

        # Convenience: expose open_with_zeropad for FilePanel
        self.open_with_zeropad = self.open_with_zeropad

    # =====================================================================
    # Public actions (Menus call these)
    # =====================================================================

    def file_new(self):
        self._create_empty_tab_and_select()

    def file_open_dialog(self):
        fname = filedialog.askopenfilename(parent=self)
        if not fname:
            return
        self.open_with_zeropad(Path(fname))

    def file_save(self):
        tab = self._current_tab()
        if not tab:
            return
        if not tab["path"]:
            return self.file_save_as()
        self._save_tab_to_path(tab, tab["path"])

    def file_save_as(self):
        tab = self._current_tab()
        if not tab:
            return
        p = tab["path"]
        enc = tab["encoding"] or "utf-8"
        bom = bool(tab["add_bom"])
        result = prompt_save_as_with_encoding(self, p, enc, bom)
        if not result:
            return
        new_path, new_enc, _errors, new_bom = result
        tab["encoding"], tab["add_bom"] = new_enc, bool(new_bom)
        self._save_tab_to_path(tab, Path(new_path))

    def file_revert(self):
        tab = self._current_tab()
        if not tab or not tab["path"]:
            return
        self._revert_from_disk(tab)

    def file_close_active_tab(self):
        self._close_current_tab()

    def file_select_all(self):
        tab = self._current_tab()
        if not tab:
            return "break"
        txt: tk.Text = tab["text"]
        txt.tag_add("sel", "1.0", "end-1c")
        txt.mark_set("insert", "1.0")
        return "break"

    # =====================================================================
    # Tabs & layout
    # =====================================================================

    def _create_empty_tab_and_select(self):
        frame = tk.Frame(self._nb, bg=DARK_PANEL)
        tid = self._mk_tab_ui(frame, title="Untitled")
        self._add_tab_to_nb(frame, "Untitled")
        self._nb.select(frame)
        return tid

    def _on_tab_changed(self, _evt):
        # Auto-create a new tab if the '+' tab is selected
        if self._nb.select() == str(self._plus_tab):
            self._create_empty_tab_and_select()
        # Repaint gutters promptly
        tab = self._current_tab()
        if tab:
            self._schedule_draw_gutters(id(tab["frame"]), fast=True)

    def _close_current_tab(self):
        cur = self._nb.select()
        if not cur or cur == str(self._plus_tab):
            return
        self._close_tab_by_widget(cur)

    def _close_tab_by_widget(self, tab_widget: str):
        # Resolve tab dict
        tab = None
        for tid, t in self._tabs.items():
            if str(t["frame"]) == tab_widget:
                tab = t
                break
        if not tab:
            return

        # Ensure the clicked tab is active (menus expect that)
        try:
            self._nb.select(tab_widget)
        except Exception:
            pass

        # Confirm save if dirty
        if tab["dirty"]:
            ans = messagebox.askyesnocancel("Unsaved changes", "Save before closing?")
            if ans is None:
                return  # Cancel
            if ans:
                # Run the standard Save flow
                if tab["path"]:
                    self._save_tab_to_path(tab, tab["path"])
                else:
                    self.file_save_as()
                # If still dirty (user cancelled or save failed), abort close
                if tab["dirty"]:
                    return

        # Close
        self._nb.forget(tab_widget)
        self._tabs.pop(id(tab["frame"]), None)

    # =====================================================================
    # Status / gutters / activity
    # =====================================================================

    def _draw_gutters(self, tid: int):
        tab = self._tabs.get(tid)
        if not tab:
            return
        ln: tk.Canvas = tab["ln"]
        face: tk.Canvas = tab["face"]
        txt: tk.Text = tab["text"]

        ln.delete("all")
        face.delete("all")

        # Visible line range
        first_idx = txt.index("@0,0")
        last_idx = txt.index(f"@0,{txt.winfo_height()}")
        first_line = int(first_idx.split(".")[0])
        last_line = max(first_line, int(last_idx.split(".")[0]))

        # Font to pass to suspicious_line (Tk font object)
        try:
            tk_font = tkfont.Font(font=txt["font"])
        except Exception:
            tk_font = tkfont.nametofont("TkFixedFont")

        for line_no in range(first_line, last_line + 1):
            dline = txt.dlineinfo(f"{line_no}.0")
            if not dline:
                continue
            y = dline[1]

            # Line number (right aligned)
            ln.create_text(44, y, anchor="ne", fill=FG_DIM, text=str(line_no))

            # Safety face
            text_line = txt.get(f"{line_no}.0", f"{line_no}.end")
            face_char = self._line_face_for(text_line, tk_font)

            if face_char != SAFE_FACE_OK:
                fill = FG_WARN if face_char == SAFE_FACE_BAD else FG_DIM
                face.create_text(9, y, anchor="n", fill=fill, text=face_char, tags=("face", f"line-{line_no}"))

        # Click handling
        def click_cb(ev):
            self._on_face_click(tid, ev)
        face.tag_bind("face", "<Button-1>", click_cb)

    def _on_text_activity(self, tid: int):
        tab = self._tabs.get(tid)
        if not tab:
            return
        self._update_status_for_tab(tab)
        self._schedule_draw_gutters(tid, fast=True)

    def _on_text_yscroll(self, tid: int, first: str, last: str):
        tab = self._tabs.get(tid)
        if not tab:
            return
        try:
            tab["scroll"].set(first, last)
            f = float(first)
            for cv in (tab["ln"], tab["face"]):
                cv.yview_moveto(f)
        except Exception:
            pass
        self._schedule_draw_gutters(tid, fast=True)

    def _schedule_draw_gutters(self, tid: int, fast: bool = False):
        tab = self._tabs.get(tid)
        if not tab:
            return
        txt: tk.Text = tab["text"]

        # Estimate size to scale repaint frequency
        size_chars = len(txt.get("1.0", "end-1c"))
        if size_chars > 1_000_000:
            delay = REPAINT_HUGE_MS
        elif size_chars > 200_000:
            delay = REPAINT_SLOW_MS
        else:
            delay = REPAINT_FAST_MS
        if fast:
            delay = max(20, delay // 2)

        if tab["repaint_due"]:
            self.after_cancel(tab["repaint_due"])
        tab["repaint_due"] = self.after(delay, lambda t=tid: self._draw_gutters(t))

    def _line_face_for(self, text_line: str, tk_font: tkfont.Font) -> str:
        """
        Minimal rules:
        - suspicious_line(...) -> 😡
        - elif exists_outside_printable_ascii_plane(...) -> 😐
        - else -> 🙂
        """
        try:
            if suspicious_line(text_line, tk_font):
                return SAFE_FACE_BAD
        except Exception:
            return SAFE_FACE_MED

        try:
            if exists_outside_printable_ascii_plane(text_line):
                return SAFE_FACE_MED
        except Exception:
            return SAFE_FACE_MED

        return SAFE_FACE_OK

    # ========== Line Sanitize Dialog (selective) ==========

    def _on_face_click(self, tid: int, event):
        """
        Clicking the face opens a simple explanatory dialog.
        """
        tab = self._tabs.get(tid)
        if not tab:
            return
        txt: tk.Text = tab["text"]
        index = txt.index(f"@0,{event.y}")
        line_no = int(index.split(".")[0])
        line_text = txt.get(f"{line_no}.0", f"{line_no}.end")

        try:
            tk_font = tkfont.Font(font=txt["font"])
        except Exception:
            tk_font = tkfont.nametofont("TkFixedFont")
        face_char = self._line_face_for(line_text, tk_font)

        # ↓↓↓ pass tid so the dialog can find the right Text widget/tab
        self._open_face_legend_dialog(tid, line_no)

    def _bucketize_issues(self, line_text: str, issues: List[Tuple[int, str]]) -> Dict[str, List[Tuple[int, str]]]:
        """
        Group issues into coarse categories the user can act on individually:
          - 'url'    : URL-related
          - 'email'  : Email-related
          - 'other'  : Controls/ignorable/bidi/etc.
        """
        buckets: Dict[str, List[Tuple[int, str]]] = {"url": [], "email": [], "other": []}
        for off, msg in issues:
            lower = msg.lower()
            if "url" in lower or "idn" in lower or "punycode" in lower:
                buckets["url"].append((off, msg))
            elif "email" in lower:
                buckets["email"].append((off, msg))
            else:
                buckets["other"].append((off, msg))
        # If heuristic mis-buckets (rare), still safe—the sanitize toggles correspond to our selective paths
        return buckets

    def _line_issue_dialog(self, line_no: int, text: str, buckets: Dict[str, List[Tuple[int, str]]]) -> Optional[Dict[str, bool]]:
        """
        Present a dialog listing issues and checkboxes for which categories to sanitize.
        Returns {'url': bool, 'email': bool, 'other': bool} or None if cancelled.
        """
        win = tk.Toplevel(self)
        win.withdraw()
        win.title(f"Line {line_no} — Issues")
        win.configure(bg=DARK_PANEL)
        win.transient(self)
        win.grab_set()

        # Header
        tk.Label(win, text=f"Line {line_no} issues:", bg=DARK_PANEL, fg=FG_TEXT, anchor="w").pack(fill="x", padx=14, pady=(14, 6))

        # Issues list
        frame = tk.Frame(win, bg=DARK_PANEL)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        def add_bucket(title: str, items: List[Tuple[int, str]]):
            lab = tk.Label(frame, text=title, bg=DARK_PANEL, fg=FG_TEXT, anchor="w")
            lab.pack(fill="x", pady=(8, 2))
            if not items:
                tk.Label(frame, text="(none)", bg=DARK_PANEL, fg=FG_DIM, anchor="w").pack(fill="x")
            else:
                box = tk.Listbox(frame, height=min(6, max(1, len(items))), bg="#0b1220", fg=FG_TEXT, activestyle="none", highlightthickness=0, relief="flat")
                for off, msg in items:
                    box.insert("end", f"{off}: {msg}")
                box.pack(fill="x")

        add_bucket("URL-related:", buckets.get("url", []))
        add_bucket("Email-related:", buckets.get("email", []))
        add_bucket("Other (controls/ignorable/bidi):", buckets.get("other", []))

        # Checkboxes
        var_url = tk.BooleanVar(value=bool(buckets.get("url")))
        var_mail = tk.BooleanVar(value=bool(buckets.get("email")))
        var_other = tk.BooleanVar(value=bool(buckets.get("other")))
        opts = tk.Frame(win, bg=DARK_PANEL)
        opts.pack(fill="x", padx=14, pady=(6, 6))
        tk.Checkbutton(opts, text="Fix URL issues", variable=var_url, bg=DARK_PANEL, fg=FG_TEXT, selectcolor=DARK_PANEL_2, activebackground=DARK_PANEL, activeforeground=FG_TEXT).pack(anchor="w")
        tk.Checkbutton(opts, text="Fix Email issues", variable=var_mail, bg=DARK_PANEL, fg=FG_TEXT, selectcolor=DARK_PANEL_2, activebackground=DARK_PANEL, activeforeground=FG_TEXT).pack(anchor="w")
        tk.Checkbutton(opts, text="Fix Other dangerous controls", variable=var_other, bg=DARK_PANEL, fg=FG_TEXT, selectcolor=DARK_PANEL_2, activebackground=DARK_PANEL, activeforeground=FG_TEXT).pack(anchor="w")

        # Buttons
        btns = tk.Frame(win, bg=DARK_PANEL)
        btns.pack(fill="x", padx=14, pady=(6, 12))
        out: Dict[str, bool] = {}

        def on_ok():
            out.update(url=bool(var_url.get()), email=bool(var_mail.get()), other=bool(var_other.get()))
            win.destroy()

        def on_cancel():
            out.clear()
            win.destroy()

        ttk.Button(btns, text="Sanitize Selected", command=on_ok).pack(side="right")
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right", padx=(0, 8))

        win.update_idletasks()
        try:
            px, py = self.winfo_rootx(), self.winfo_rooty()
            pw, ph = self.winfo_width(), self.winfo_height()
            ww, wh = max(520, win.winfo_reqwidth()), max(300, win.winfo_reqheight())
            x = px + max(0, (pw - ww) // 2)
            y = py + max(0, (ph - wh) // 3)
            win.geometry(f"{ww}x{wh}+{x}+{y}")
        except Exception:
            pass
        win.deiconify()
        win.lift()
        win.focus_set()
        win.wait_window()
        return out if out else None

    # Selective sanitize: reuse minimal rules but honor the chosen categories
    def _sanitize_line_selective(self, line: str, choice: Dict[str, bool]) -> Optional[str]:
        """
        Implement selective sanitization without changing your utils API by composing
        sanitize_line_minimal and per-chunk cleanup.

        Strategy:
          - If all True -> sanitize_line_minimal(line)
          - Else, we run a small inlined dispatcher for this line:
              • URLs -> sanitize iff choice['url']
              • Emails -> sanitize iff choice['email']
              • Else -> low-aggression cleanup iff choice['other']
        """
        if choice.get("url") and choice.get("email") and choice.get("other"):
            return sanitize_line_minimal(line)

        # Local lightweight re-implementation, aligned with utils' dispatcher
        import regex as _re
        from string_safety_utils import (
            _SCHEME_URL_RE as SRE,
            _HOSTLIKE_RE as HRE,
            _EMAIL_RE as ERE,
            url_token_sanitize,
            email_token_sanitize,
            deceptive_line_sanitize,
        )

        def iter_urls(s: str):
            covered = [False] * len(s)
            for m in SRE.finditer(s):
                yield ("scheme", m.start(), m.end(), m.group(1));  covered[m.start():m.end()] = [True]* (m.end()-m.start())
            for m in HRE.finditer(s):
                if any(covered[i] for i in range(m.start(), min(m.end(), len(s)))):
                    continue
                yield ("hostlike", m.start(), m.end(), m.group(1))
                covered[m.start():m.end()] = [True]* (m.end()-m.start())
            return

        changed = False
        out: List[str] = []
        i = 0
        # URLs
        url_spans = list(iter_urls(line))
        for _, st, en, tok in url_spans:
            if st > i:
                seg = line[i:st]
                if choice.get("other"):
                    rep = deceptive_line_sanitize(seg, low_aggression=True, prefer_silent_removal=True)
                    out.append(rep if rep is not None else seg); changed |= (rep is not None)
                else:
                    out.append(seg)
            if choice.get("url"):
                rep = url_token_sanitize(tok)
                out.append(rep if rep is not None else tok); changed |= (rep is not None)
            else:
                out.append(tok)
            i = en
        tail = line[i:]

        # Emails (non-overlapping with URLs)
        covered_tail = [False] * len(tail)
        j = 0
        for m in ERE.finditer(tail):
            if any(covered_tail[k] for k in range(m.start(), m.end())):
                continue
            if m.start() > j:
                seg = tail[j:m.start()]
                if choice.get("other"):
                    rep = deceptive_line_sanitize(seg, low_aggression=True, prefer_silent_removal=True)
                    out.append(rep if rep is not None else seg); changed |= (rep is not None)
                else:
                    out.append(seg)
            tok = m.group(0)
            if choice.get("email"):
                rep = email_token_sanitize(tok)
                out.append(rep if rep is not None else tok); changed |= (rep is not None)
            else:
                out.append(tok)
            j = m.end()
        rest = tail[j:]

        if rest:
            if choice.get("other"):
                rep = deceptive_line_sanitize(rest, low_aggression=True, prefer_silent_removal=True)
                out.append(rep if rep is not None else rest); changed |= (rep is not None)
            else:
                out.append(rest)

        res = "".join(out)
        return res if changed else None

    # =====================================================================
    # Utils
    # =====================================================================

    @staticmethod
    def _normalize_eols(s: str) -> str:
        s = s.replace("\r\n", "\n")
        s = s.replace("\r", "\n")
        return s

    def _current_tab(self) -> Optional[Dict]:
        cur = self._nb.select()
        if not cur or cur == str(self._plus_tab):
            return None
        for _tid, tab in self._tabs.items():
            if str(tab["frame"]) == cur:
                return tab
        return None

    # =====================================================================
    # File menu: Open Selected / Save Over Selected
    # =====================================================================

    def _files_panel_selected_path(self) -> Optional[Path]:
        """Return selected Path from sibling File panel, if any."""
        try:
            p = getattr(self, "_selected_path", None)
            return Path(p) if p else None
        except Exception:
            return None

    def file_open_selected(self):
        p = self._files_panel_selected_path()
        if not p:
            messagebox.showinfo("Open Selected", "No item selected in the File panel.")
            return
        if p.is_dir():
            messagebox.showinfo("Open Selected", "The selected item is a folder. Pick a file.")
            return

        # Reuse FilePanel chooser if present
        if hasattr(self, "_prompt_open_file") and callable(getattr(self, "_prompt_open_file")):
            self._prompt_open_file(p)
            return

        enc, errors, add_bom = prompt_open_with_encoding(self, p)
        if not enc:
            return
        try:
            data = read_text_bytes(p)
            text = decode_bytes(data, enc, errors)
        except Exception as e:
            messagebox.showerror("Open failed", f"Could not open {p}:\n{e}")
            return

        text = self._normalize_eols(text)
        frame = tk.Frame(self._nb, bg=DARK_PANEL)
        tid = self._mk_tab_ui(
            frame,
            title=p.name,
            path=p,
            initial_text=text,
            encoding=enc,
            add_bom=bool(add_bom),
        )
        self._add_tab_to_nb(frame, title=p.name)
        self._nb.select(frame)
        return tid

    # =====================================================================
    # Helper: force-clear dirty indicators after programmatic loads/saves
    # =====================================================================
    def _force_clean_state(self, tid: int):
        tab = self._tabs.get(tid)
        if not tab:
            return
        txt: tk.Text = tab["text"]
        try:
            txt.edit_reset()
            txt.edit_modified(False)
        except Exception:
            pass
        tab["dirty"] = False
        self._retitle_tab(
            tid,
            tab.get("title") or (tab.get("path").name if tab.get("path") else "Untitled"),
            dirty=False,
        )
        self._update_status_for_tab(tab)

    # =========================
    # Modified-flag squelching
    # =========================
    def _mod_squelch_begin(self, tab: Dict):
        """Increment a counter that tells _on_modified to ignore spurious events."""
        tab["squelch_mod"] = int(tab.get("squelch_mod", 0)) + 1

    def _mod_squelch_end(self, tab: Dict):
        """Decrement squelch counter (never below zero)."""
        tab["squelch_mod"] = max(0, int(tab.get("squelch_mod", 0)) - 1)

    # ==========================================
    # Build a tab's internals (single definition)
    # ==========================================
    def _mk_tab_ui(
        self,
        frame: tk.Frame,
        title: str,
        *,
        path: Optional[Path] = None,
        initial_text: str = "",
        encoding: str = "utf-8",
        add_bom: bool = False,
    ) -> int:
        # Font
        mono = tkfont.Font(family="Monospace", size=11)

        # Container
        host = tk.Frame(frame, bg=DARK_PANEL, highlightthickness=0, bd=0)
        host.pack(fill="both", expand=True)
        host.grid_rowconfigure(0, weight=1)
        for c in (0, 1, 2):
            host.grid_columnconfigure(c, weight=0)
        host.grid_columnconfigure(3, weight=1)

        # Line numbers gutter (unselectable)
        ln = tk.Canvas(host, width=48, bg="#101828", highlightthickness=0, bd=0, takefocus=0)
        ln.grid(row=0, column=0, sticky="ns")
        ln.bind("<Button-1>", lambda e: "break")

        # Safety faces gutter (unselectable)
        face = tk.Canvas(host, width=18, bg="#0d1628", highlightthickness=0, bd=0, takefocus=0)
        face.grid(row=0, column=1, sticky="ns")
        face.bind("<Button-1>", lambda e: "break")

        # Soft spacer
        sep = tk.Frame(host, width=1, bg=DARK_PANEL, highlightthickness=0, bd=0)
        sep.grid(row=0, column=2, sticky="ns")

        # Text + Scrollbar
        txt = tk.Text(
            host,
            wrap="none",
            undo=True,
            background=DARK_BG,
            foreground=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            bd=0,
            padx=8,
            pady=6,
            font=mono,
            highlightthickness=0,
        )
        txt.grid(row=0, column=3, sticky="nsew")
        scroll = ttk.Scrollbar(host, orient="vertical", command=txt.yview)
        scroll.grid(row=0, column=4, sticky="ns")
        txt.configure(
            yscrollcommand=lambda first, last, tid=None: self._on_text_yscroll(id(frame), first, last)
        )

        # Model
        tab = {
            "frame": frame,
            "host": host,
            "ln": ln,
            "face": face,
            "text": txt,
            "scroll": scroll,
            "path": path,
            "title": title,
            "encoding": encoding,
            "add_bom": add_bom,
            "dirty": False,
            "last_paint": 0.0,
            "repaint_due": None,
            "squelch_mod": 0,  # guard for spurious <<Modified>> during programmatic edits
        }
        tid = id(frame)
        self._tabs[tid] = tab

        # Fill content under a squelch window so <<Modified>> won't mark dirty
        self._mod_squelch_begin(tab)
        try:
            if initial_text:
                txt.insert("1.0", self._normalize_eols(initial_text))
            txt.edit_reset()
            txt.edit_modified(False)
        finally:
            # End squelch after idle in case <<Modified>> is delivered late
            self.after_idle(lambda t=tab: (self._mod_squelch_end(t), t["text"].edit_modified(False)))

        # Bindings
        txt.bind("<<Modified>>", lambda _e, t=tid: self._on_modified(t), add="+")
        txt.bind("<KeyRelease>", lambda _e, t=tid: self._on_text_activity(t), add="+")
        txt.bind("<ButtonRelease-1>", lambda _e, t=tid: self._on_text_activity(t), add="+")
        txt.bind("<Configure>", lambda _e, t=tid: self._schedule_draw_gutters(t), add="+")
        txt.bind("<MouseWheel>", lambda _e, t=tid: self._schedule_draw_gutters(t), add="+")
        txt.bind("<Button-4>", lambda _e, t=tid: self._schedule_draw_gutters(t), add="+")
        txt.bind("<Button-5>", lambda _e, t=tid: self._schedule_draw_gutters(t), add="+")
        txt.bind("<Control-a>", lambda e, t=tid: (txt.tag_add("sel", "1.0", "end-1c"), "break"))

        # Click faces to open a simple legend
        face.bind("<Button-1>", lambda e, t=tid: self._on_face_click(t, e))

        # Title & first paint
        self._retitle_tab(tid, title, dirty=False)
        self._update_status_for_tab(tab)
        self._schedule_draw_gutters(tid, fast=True)
        return tid


    # ==================================================
    # Rename hook from FilePanel (replacement, squelched)
    # ==================================================
    def on_path_renamed(self, old_path: Path, new_path: Path):
        """Update any open tab's path/title WITHOUT marking it dirty."""
        try:
            old_r = Path(old_path).resolve()
            new_r = Path(new_path).resolve()
        except Exception:
            return

        for tid, tab in list(self._tabs.items()):
            p = tab.get("path")
            if not p:
                continue
            try:
                if Path(p).resolve() != old_r:
                    continue
            except Exception:
                continue

            was_dirty = bool(tab.get("dirty"))
            txt: tk.Text = tab["text"]

            # Squelch any spurious <<Modified>> around title/path churn.
            self._mod_squelch_begin(tab)
            try:
                tab["path"] = new_r
                self._retitle_tab(tid, new_r.name, dirty=was_dirty)
                self._update_status_for_tab(tab)
                try:
                    txt.edit_modified(False)
                except Exception:
                    pass
            finally:
                # End after idle – some Tk builds deliver <<Modified>> late.
                self.after_idle(lambda t=tab: (self._mod_squelch_end(t), t["text"].edit_modified(False)))

    # =====================================================================
    # Save Over Selected (File menu) — overwrite selected file *content only*
    # =====================================================================
    def save_over_selected(self):
        tab = self._current_tab()
        if not tab:
            messagebox.showinfo("Save Over Selected", "No text tab is active.")
            return

        target = getattr(self, "_selected_path", None)
        if not isinstance(target, Path) or (not target.exists()) or (not target.is_file()):
            messagebox.showinfo("Save Over Selected", "Please select a file in the File Manager.")
            return

        # prepare content & encoding
        default_enc = tab.get("encoding") or "utf-8"
        content = tab["text"].get("1.0", "end-1c")
        data, final_enc = encode_text_inline(self, content, default_enc)  # one dialog; wide enough

        # Write-in-place (preserve metadata other than size/mtime)
        with open(target, "r+b") as f:
            f.truncate(0)
            f.write(data)
            f.flush()

        # The tab should now point at the overwritten file (and be clean)
        tab["path"] = target
        tab["encoding"] = final_enc
        tab["add_bom"] = (final_enc.lower() == "utf-8-with-bom")
        tab["dirty"] = False

        try:
            tab["text"].edit_modified(False)
            tab["text"].edit_reset()
        except Exception:
            pass

        self._retitle_tab(id(tab["frame"]), target.name, dirty=False)
        self._update_status_for_tab(tab)
        messagebox.showinfo("Save Over Selected", f"Saved over:\n{target}")

    # =====================================================================
    # Modified/Dirty tracking — ensure both tab label *and* status get the star
    # =====================================================================

    def _update_status_for_tab(self, tab: dict):
        txt: tk.Text = tab["text"]
        try:
            line_s, col_s = txt.index("insert").split(".")
            line, col = int(line_s), int(col_s) + 1
        except Exception:
            line, col = 1, 1
        enc = tab.get("encoding") or "utf-8"
        dirty_star = "*" if tab.get("dirty") else ""
        path_str = str(tab["path"]) if tab.get("path") else "(untitled)"
        self._status_path_var.set(f"{path_str}{dirty_star}")
        self._status_info.config(text=f"Ln {line}, Col {col}  | {enc}")

    def _on_modified(self, tid: int):
        tab = self._tabs.get(tid)
        if not tab:
            return
        if int(tab.get("squelch_mod", 0)) > 0:
            try:
                tab["text"].edit_modified(False)
            except Exception:
                pass
            return

        tab["dirty"] = True
        try:
            tab["text"].edit_modified(False)
        except Exception:
            pass

        base_title = tab.get("title") or (tab.get("path").name if tab.get("path") else "Untitled")
        self._retitle_tab(tid, base_title, dirty=True)
        self._update_status_for_tab(tab)
        self._schedule_draw_gutters(tid, fast=False)

    # =====================================================================
    # Disk I/O helpers
    # =====================================================================

    def _revert_from_disk(self, tab: Dict):
        p = tab.get("path")
        if not p:
            return
        if not messagebox.askyesno("Revert", f"Discard changes and reload from disk?\n\n{p}"):
            return

        try:
            data = read_text_bytes(p)
            text = decode_bytes(data, tab.get("encoding") or "utf-8", "strict")
            text = self._normalize_eols(text)
        except Exception as e:
            messagebox.showerror("Revert failed", f"Could not reload {p}:\n{e}")
            return

        txt: tk.Text = tab["text"]

        self._mod_squelch_begin(tab)
        try:
            txt.delete("1.0", "end")
            txt.insert("1.0", text)
            tab["dirty"] = False
            try:
                txt.edit_modified(False)
                txt.edit_reset()
            except Exception:
                pass
        finally:
            self.after_idle(lambda t=tab: (self._mod_squelch_end(t), t["text"].edit_modified(False)))

        title = (tab["path"].name if tab.get("path") else tab.get("title") or "Untitled")
        self._retitle_tab(id(tab["frame"]), title, dirty=False)
        self._update_status_for_tab(tab)
        self._schedule_draw_gutters(id(tab["frame"]), fast=True)

    def _save_tab_to_path(self, tab: Dict, target: Path):
        """Save the current tab to path `target`; preserve clean state after save."""
        s = tab["text"].get("1.0", "end-1c")
        try:
            enc = tab.get("encoding") or "utf-8"
            add_bom = bool(tab.get("add_bom"))
            data = encode_text(s, enc, add_bom)
            save_to_path(target, data)
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save to {target}:\n{e}")
            return

        txt: tk.Text = tab["text"]
        self._mod_squelch_begin(tab)
        try:
            tab["path"] = Path(target)
            tab["dirty"] = False
            self._retitle_tab(id(tab["frame"]), tab["path"].name, dirty=False)
            try:
                txt.edit_modified(False)
                txt.edit_reset()
            except Exception:
                pass
        finally:
            self.after_idle(lambda t=tab: (self._mod_squelch_end(t), t["text"].edit_modified(False)))

        self._update_status_for_tab(tab)
        self._schedule_draw_gutters(id(tab["frame"]), fast=True)

    def open_with_zeropad(self, path: Path, override_encoding: str | None = None):
        """Open file; normalize EOLs to LF. If override_encoding is provided, use it."""
        try:
            enc = override_encoding or suggest_open_encoding(path)
            data = read_text_bytes(path)
            text = decode_bytes(data, enc, "strict")
        except Exception as e:
            messagebox.showerror("Open failed", f"Could not open {path}:\n{e}")
            return

        text = self._normalize_eols(text)
        frame = tk.Frame(self._nb, bg=DARK_PANEL)
        tid = self._mk_tab_ui(
            frame,
            title=Path(path).name,
            path=Path(path),
            initial_text=text,
            encoding=enc,
            add_bom=(enc.lower() == "utf-8-with-bom"),
        )
        self._add_tab_to_nb(frame, title=Path(path).name)
        self._nb.select(frame)

        self._force_clean_state(tid)
        self._schedule_draw_gutters(tid, fast=True)
        return tid

    # =====================================================================
    # Notebook tab interactions (close/new)
    # =====================================================================

    def _install_nb_close_binding(self):
        """
        Install a highest-priority click handler for the notebook tabs.
        We intercept on press so we can consume the event before ttk selects the tab.
        """
        self._NB_CLOSE_TAG = "ZP_NB_CLOSE"
        # Put our tag first so we run before widget/class/default bindings
        tags = list(self._nb.bindtags())
        if self._NB_CLOSE_TAG in tags:
            tags.remove(self._NB_CLOSE_TAG)
        tags.insert(0, self._NB_CLOSE_TAG)
        self._nb.bindtags(tuple(tags))

        # Bind on press
        self.bind_class(self._NB_CLOSE_TAG, "<Button-1>", self._nb_click_intercept, add="+")

    def _add_tab_to_nb(self, frame: tk.Frame, title: str):
        label = f"{title}"  # no cross
        try:
            self._nb.insert(1, frame, text=label)  # after '+'
        except tk.TclError:
            self._nb.add(frame, text=label)

    def _retitle_tab(self, tab_id: int, title: str, dirty: bool):
        star = "*" if dirty else ""
        label = f"{title}{star}"  # no cross
        tab = self._tabs.get(tab_id)
        if not tab:
            return
        tab["title"] = title
        frame = tab["frame"]
        try:
            self._nb.tab(frame, text=label)
        except Exception:
            pass

    # _nb_click_intercept
    def _nb_click_intercept(self, event):
        nb = self._nb
        if not nb.winfo_ismapped():
            return

        try:
            nx = event.x_root - nb.winfo_rootx()
            ny = event.y_root - nb.winfo_rooty()
        except Exception:
            return

        try:
            idx = nb.index(f"@{nx},{ny}")
        except Exception:
            return  # not over a tab

        try:
            bx, by, bw, bh = nb.bbox(idx)
        except Exception:
            return

        if not (bx <= nx <= bx + bw and by <= ny <= by + bh):
            return

        # modifier keys
        state = getattr(event, "state", 0)
        shift_held   = bool(state & 0x0001)  # ShiftMask
        ctrl_held    = bool(state & 0x0004)  # ControlMask

        # '+' tab behavior
        if idx == 0:
            tabs = nb.tabs()
            if shift_held or ctrl_held:
                # focus first real tab (index 1), do nothing else
                if len(tabs) > 1:
                    try:
                        nb.select(tabs[1])
                    except Exception:
                        pass
                return "break"
            else:
                # normal '+' click → create new tab
                self._create_empty_tab_and_select()
                return "break"  # don't let ttk select '+'

        # For normal tabs, just let ttk handle selection.

    def _open_face_legend_dialog(self, tid: int, line_no: int):
        """
        Modal dialog to sanitize the *line's* text for the given tab.
        Modes:
        - Strip only: keep ASCII printable [0x20..0x7E]
        - Confusables skeleton → Strip: confusable_skeleton(line) then keep [0x20..0x7E]
        On OK: replace that line in the tab's Text widget. On Cancel: no changes.
        Includes dark-theme hover styles for radio/buttons. Cancel is on the right.
        """
        import tkinter as tk
        from tkinter import ttk

        # ---- resolve tab + text widget ----
        tab = self._tabs.get(tid)
        if not tab:
            return
        textw: tk.Text = tab["text"]

        # ---- helpers ----
        def ascii_printable_strip(s: str) -> str:
            # Keep only ASCII printable chars 0x20 (space) to 0x7E (~)
            return "".join(ch for ch in s if 0x20 <= ord(ch) <= 0x7E)

        # Try the likely module first, then the alternative the project mentioned.
        try:
            # If your function lives here:
            from basic_string_safety_utils import confusable_skeleton
        except Exception:
            try:
                # Or here, if your project uses this name:
                from basis_string_safety import confusable_skeleton
            except Exception:
                # Fallback: no-op skeleton
                def confusable_skeleton(text: str, mapping=None) -> str:
                    return text

        # ---- parent toplevel (for proper modality) ----
        try:
            parent = self.winfo_toplevel()
        except Exception:
            parent = getattr(self, "root", None)
        if parent is None:
            parent = tk._get_default_root()

        # ---- snapshot scroll + caret position ----
        yview = textw.yview()
        insert_index = textw.index("insert")
        insert_line = int(insert_index.split(".")[0])
        insert_col = int(insert_index.split(".")[1]) if insert_line == int(line_no) else None

        # ---- get current line text ----
        line_start = f"{int(line_no)}.0"
        line_end   = f"{int(line_no)}.end"  # excludes trailing newline in Text
        try:
            original_line = textw.get(line_start, line_end)
        except Exception:
            original_line = ""

        # ---- dialog (hidden → mapped → grabbed) ----
        win = tk.Toplevel(parent)
        self._legend_win = win
        if getattr(self, "_legend_open", False):
            try:
                self._legend_win.lift(); self._legend_win.focus_set()
            except Exception:
                pass
            return
        self._legend_open = True

        # Dark panel styling
        win.withdraw()
        win.transient(parent)
        win.title(f"Sanitize Line {line_no}")
        win.resizable(False, False)
        try:
            win.configure(bg=DARK_PANEL)
        except Exception:
            pass

        # ---- ttk styles (dark + hover) ----
        style = ttk.Style(win)
        # Radiobutton
        style.configure(
            "Dark.TRadiobutton",
            background=DARK_PANEL,
            foreground=FG_TEXT
        )
        style.map(
            "Dark.TRadiobutton",
            foreground=[("active", FG_TEXT)],
            background=[("active", DARK_PANEL_2)]
        )
        # Buttons
        style.configure(
            "Dark.TButton",
            background=DARK_PANEL_2,
            foreground=FG_TEXT,
            padding=(10, 4)
        )
        style.map(
            "Dark.TButton",
            background=[("active", "#162033")],
            foreground=[("active", FG_TEXT)]
        )

        container = ttk.Frame(win, padding=12, style="Dark.TFrame")
        # Some themes ignore TFrame bg; add a manual bg label wrapper if needed
        try:
            style.configure("Dark.TFrame", background=DARK_PANEL)
        except Exception:
            pass

        container.grid(row=0, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        lbl = ttk.Label(container, text=f"Choose sanitation for line {line_no}", style="Dark.TLabel")
        try:
            style.configure("Dark.TLabel", background=DARK_PANEL, foreground=FG_TEXT)
        except Exception:
            pass
        lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        mode = tk.StringVar(value="strip")  # 'strip' or 'skeleton_strip'

        strip_rb = ttk.Radiobutton(
            container, text="Strip only (keep ASCII 0x20–0x7E)", variable=mode, value="strip",
            style="Dark.TRadiobutton"
        )
        skel_rb = ttk.Radiobutton(
            container, text="Confusables skeleton → Strip", variable=mode, value="skeleton_strip",
            style="Dark.TRadiobutton"
        )
        strip_rb.grid(row=1, column=0, columnspan=2, sticky="w")
        skel_rb.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ---- buttons (OK on left, Cancel on right) ----
        btns = ttk.Frame(container, style="Dark.TFrame")
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def close_modal(*_):
            try:
                win.grab_release()
            except Exception:
                pass
            self._legend_open = False
            try:
                del self._legend_win
            except Exception:
                pass
            win.destroy()

        def apply_and_close():
            chosen = mode.get()
            if chosen == "strip":
                new_line = ascii_printable_strip(original_line)
            else:
                try:
                    new_line = confusable_skeleton(original_line)
                except Exception:
                    new_line = original_line
                new_line = ascii_printable_strip(new_line)

            # Replace the line (single undo step)
            textw.edit_separator()
            textw.delete(line_start, line_end)
            textw.insert(line_start, new_line)

            # Preserve caret on that line if it was there
            if insert_col is not None:
                new_col = min(insert_col, len(new_line))
                try:
                    textw.mark_set("insert", f"{int(line_no)}.{new_col}")
                except Exception:
                    pass

            # Restore scroll
            try:
                textw.yview_moveto(yview[0])
            except Exception:
                pass

            # Repaint gutters promptly
            try:
                self._schedule_draw_gutters(tid, fast=True)
            except Exception:
                pass

            close_modal()

        ok_btn     = ttk.Button(btns, text="OK",     command=apply_and_close, style="Dark.TButton")
        cancel_btn = ttk.Button(btns, text="Cancel", command=close_modal,     style="Dark.TButton")
        # Put Cancel on the other side (rightmost)
        ok_btn.grid(row=0, column=0, padx=(0, 8))
        cancel_btn.grid(row=0, column=1)

        # shortcuts
        win.bind("<Return>", lambda e: apply_and_close())
        win.bind("<Escape>", close_modal)

        # center near parent
        win.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() // 2)
            py = parent.winfo_rooty() + (parent.winfo_height() // 2)
            w = max(win.winfo_reqwidth(), 420)
            h = max(win.winfo_reqheight(), 160)
            x = max(px - w // 2, 0)
            y = max(py - h // 2, 0)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        # show safely after mapping (prevents "not viewable" grab error)
        def _show_modal():
            try:
                win.deiconify()
                win.update_idletasks()
                try:
                    win.wait_visibility()
                except Exception:
                    pass
                try:
                    win.grab_set()
                except tk.TclError:
                    pass
                win.focus_set()
                win.wait_window()
            finally:
                if getattr(self, "_legend_open", False):
                    self._legend_open = False
                try:
                    del self._legend_win
                except Exception:
                    pass

        win.after(0, _show_modal)
