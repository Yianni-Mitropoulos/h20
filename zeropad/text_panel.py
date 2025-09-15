# text_panel.py
from __future__ import annotations
import time
from pathlib import Path
from typing import Dict, Optional

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

# line safety (per line, aggressive)
from string_safety_utils import deceptive_line_check, deceptive_line_sanitize

# editor I/O helpers (encoding detection & save plumbing)
from editor_io import (
    prompt_open_with_encoding,                     # (owner, path) -> (encoding, errors, add_bom)
    read_text_bytes, decode_bytes,                # bytes <-> text
    encode_text, save_to_path,                    # (text, encoding, add_bom=False) -> bytes
    prompt_save_as_with_encoding,                 # (owner, suggest_path, suggest_enc, suggest_bom) -> (path, encoding, errors, add_bom) | None
    encode_text_inline,                           # (owner, text, default_encoding) -> (data, final_encoding)
    suggest_open_encoding,                        # path -> encoding str
)

# =========================
# Palette / Theme Constants
# =========================
DARK_BG      = "#0b1220"
DARK_PANEL   = "#111827"
DARK_PANEL_2 = "#0f172a"
FG_TEXT      = "#e5e7eb"
FG_DIM       = "#9ca3af"

SAFE_FACE_BAD = "☹"

# Repaint throttles
REPAINT_FAST_MS = 60
REPAINT_SLOW_MS = 140
REPAINT_HUGE_MS = 260


class TextPanel:
    """
    Dark-themed, tabbed text editor panel with:
      • Fixed “+” tab (index 0) to create new tabs.
      • Line-number and safety gutters (flags suspicious characters per line).
      • Status bar with path[*], cursor position, total lines, encoding.
      • File actions: new/open/save/save-as/revert/close/select-all,
        plus “open selected” and “save over selected” integrated with a sibling File panel.
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

        # Status: right info
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

    def _add_tab_to_nb(self, frame: tk.Frame, title: str):
        label = f"{title}  ✕"
        try:
            self._nb.insert(1, frame, text=label)  # after '+'
        except tk.TclError:
            self._nb.add(frame, text=label)

    def _on_tab_changed(self, _evt):
        # Auto-create a new tab if the '+' tab is selected
        if self._nb.select() == str(self._plus_tab):
            self._create_empty_tab_and_select()

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
        # Use len(text) as proxy to avoid repeated UTF-8 encodes on every keystroke.
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

        # Font metrics
        try:
            fh = tkfont.Font(font=txt["font"]).metrics("linespace")
        except Exception:
            fh = 15  # fallback metric only; not an API fallback

        for line_no in range(first_line, last_line + 1):
            dline = txt.dlineinfo(f"{line_no}.0")
            if not dline:
                continue
            y = dline[1]
            # Line number (right aligned)
            ln.create_text(44, y, anchor="ne", fill=FG_DIM, text=str(line_no))
            # Safety face
            text_line = txt.get(f"{line_no}.0", f"{line_no}.end")
            issues = deceptive_line_check(text_line, low_aggression=False)
            if issues:
                # Centered in 18px gutter
                face.create_text(
                    9, y, anchor="n", fill="#ef4444", text=SAFE_FACE_BAD, tags=(f"line-{line_no}",)
                )

        # Click handling (clicking anywhere in the face gutter will resolve the line)
        def click_cb(ev):
            self._on_face_click(tid, ev)

        face.tag_bind("all", "<Button-1>", click_cb)

    def _on_face_click(self, tid: int, event):
        tab = self._tabs.get(tid)
        if not tab:
            return
        txt: tk.Text = tab["text"]
        index = txt.index(f"@0,{event.y}")
        line_no = int(index.split(".")[0])
        line_text = txt.get(f"{line_no}.0", f"{line_no}.end")
        issues = deceptive_line_check(line_text, low_aggression=False)
        if not issues:
            return
        msg = (
            "This line contains potentially deceptive characters:\n\n- "
            + "\n- ".join(m for _, m in issues)
            + "\n\nSanitize this line?"
        )
        if not messagebox.askyesno("Sanitize line", msg, icon="warning", default="yes"):
            return
        new_line = line_text
        rep = deceptive_line_sanitize(new_line, low_aggression=False)
        if rep is not None:
            new_line = rep
        if new_line != line_text:
            txt.delete(f"{line_no}.0", f"{line_no}.end")
            txt.insert(f"{line_no}.0", new_line)
            tab["dirty"] = True
            self._update_status_for_tab(tab)
            self._schedule_draw_gutters(tid, fast=True)

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
        """
        Returns the currently selected Path from the File panel, if any.
        We rely on FilePanel setting `self._selected_path` as the user moves around.
        """
        try:
            p = getattr(self, "_selected_path", None)
            return Path(p) if p else None
        except Exception:
            return None

    def file_open_selected(self):
        """
        Same behavior as double-clicking the selected file in the File panel:
          - For files: prompt 'System default vs Open in Zeropad'.
          - If 'Open in Zeropad': guess encoding, allow override, then open in a new tab.
        """
        p = self._files_panel_selected_path()
        if not p:
            messagebox.showinfo("Open Selected", "No item selected in the File panel.")
            return
        if p.is_dir():
            messagebox.showinfo("Open Selected", "The selected item is a folder. Pick a file.")
            return

        # Reuse the FilePanel's chooser if available (keeps behavior identical to double-click)
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
            # Clear Tk's internal modified flag & undo stack; keep our own dirty = False.
            txt.edit_reset()
            txt.edit_modified(False)
        except Exception:
            pass
        tab["dirty"] = False
        # Re-title without a star
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

        # Click unhappy faces to sanitize that line
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
        """
        Overwrite the *content* of the currently selected file in the File Manager
        using the active tab's text. Encoding comes from the active tab by default,
        but the user can pick a different one inline (handled by editor_io.encode_text_inline).
        """
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
    def _retitle_tab(self, tab_id: int, title: str, dirty: bool):
        star = "*" if dirty else ""
        label = f"{title}{star}  ✕"
        tab = self._tabs.get(tab_id)
        if not tab:
            return
        tab["title"] = title  # keep the base title without star
        frame = tab["frame"]
        try:
            self._nb.tab(frame, text=label)
        except Exception:
            pass

    def _update_status_for_tab(self, tab: dict):
        txt: tk.Text = tab["text"]
        try:
            line_s, col_s = txt.index("insert").split(".")
            line, col = int(line_s), int(col_s) + 1
        except Exception:
            line, col = 1, 1
        total = int(txt.index("end-1c").split(".")[0])
        enc = tab.get("encoding") or "utf-8"
        dirty_star = "*" if tab.get("dirty") else ""
        path_str = str(tab["path"]) if tab.get("path") else "(untitled)"
        self._status_path_var.set(f"{path_str}{dirty_star}")
        self._status_info.config(text=f"Ln {line}, Col {col} | {total} lines | {enc}")

    def _on_modified(self, tid: int):
        tab = self._tabs.get(tid)
        if not tab:
            return
        # Ignore programmatic edits
        if int(tab.get("squelch_mod", 0)) > 0:
            try:
                tab["text"].edit_modified(False)
            except Exception:
                pass
            return

        tab["dirty"] = True
        # Clear Tk's modified flag so future edits still fire <<Modified>>
        try:
            tab["text"].edit_modified(False)
        except Exception:
            pass

        # Star in tab title + status
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

        # Replace under squelch
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

        # Retitle & status (no star)
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
            data = encode_text(s, enc, add_bom)  # editor_io should support add_bom
            save_to_path(target, data)
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save to {target}:\n{e}")
            return

        # Update model under squelch (avoid <<Modified>> from relabel/flag flips)
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

        # Ensure the tab is clean right after creation
        self._force_clean_state(tid)
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

    def _nb_click_intercept(self, event):
        """
        High-priority tab-click hook that:
        • creates a new tab when '+' is clicked
        • closes a tab only if the click is inside the ✕ zone
        • otherwise lets ttk handle normal selection
        """
        nb = self._nb
        if not nb.winfo_ismapped():
            return

        # Convert to notebook-relative coords (tab bboxes are in notebook coords)
        try:
            nx = event.x_root - nb.winfo_rootx()
            ny = event.y_root - nb.winfo_rooty()
        except Exception:
            return

        # Which tab index was hit?
        try:
            idx = nb.index(f"@{nx},{ny}")
        except Exception:
            return  # not over a tab

        # Get its bbox; bail if we can’t
        try:
            bx, by, bw, bh = nb.bbox(idx)
        except Exception:
            return

        # Must be inside the tab's bbox
        if not (bx <= nx <= bx + bw and by <= ny <= by + bh):
            return

        # '+' tab?
        if idx == 0:
            # Only trigger when clicking the label area (safe enough: inside bbox)
            self._create_empty_tab_and_select()
            return "break"  # consume so ttk doesn't also try to "select" '+'

        # Close zone: a DPI-aware strip on the far right of the tab label
        close_w = max(14, min(28, int(round(bh * 0.8))))
        if nx >= bx + bw - close_w:
            tabs = nb.tabs()
            if 0 <= idx < len(tabs):
                tab_widget = tabs[idx]
                if tab_widget != str(self._plus_tab):
                    # ensure the tab to close is the active one, so Ctrl+W path matches
                    try:
                        nb.select(tab_widget)
                    except Exception:
                        pass
                    # Use the same public API bound to Ctrl+W
                    self.file_close_active_tab()
                    return "break"  # stop ttk default from re-selecting
        # otherwise, not a close click → let ttk select normally
