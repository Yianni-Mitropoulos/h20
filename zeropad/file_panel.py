"""
FILE PANEL (Zeropad)

COLUMN WIDTH MODEL — READ THIS BEFORE EDITING:

Each column has a persistent *target width ratio* in [0..1] stored in `self._col_ratio`.
When rendering, the actual pixel width of each *visible* column is:

    px(col) = (target_ratio(col) / sum_of_target_ratios_of_visible_cols) * treeview_pixel_width

This guarantees columns:
  • Fill the full width of the tree,
  • Keep their relative proportions stable across refreshes, sorts, and directory changes,
  • Remember their size even when temporarily hidden.

The ONLY time target ratios are updated is when the user manually resizes a column
by dragging a header separator. We detect that with <ButtonPress-1>/<ButtonRelease-1>
and reading `identify_region(...) == "separator"` to know it's a resize gesture.

DO NOT update ratios on sort, refresh, or directory change — that will cause width drift.
"""

import os
import stat
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime

# ---- safety utils (your file) ----
from string_safety_utils import (
    bad_filename_check,
    bad_filename_sanitize,
    deceptive_line_check,
    deceptive_line_sanitize,
)


class FilePanel:
    def init_file_panel(self):
        """Build the left File panel with three vertically stacked subpanels."""
        palette = getattr(self, "_palette", {})
        self._BG_PANEL = palette.get("BG_PANEL", "#111827")
        self._FG_TEXT  = palette.get("FG_TEXT",  "#e5e7eb")
        self._BG_ENTRY = "#0b1220"
        self._FG_DIM   = "#9ca3af"
        self._BTN_BG   = "#1f2937"
        self._BTN_BG_H = "#374151"
        self._BTN_BG_D = "#111827"
        self._ACC_BG   = "#2563eb"
        self._ACC_BG_H = "#3b82f6"
        self._ACC_BG_D = "#0b1220"
        self._ERR_RED  = "#ef4444"

        # Root frame for the file panel
        self.fm = tk.Frame(self.hpaned, bg=self._BG_PANEL)

        # ---------- Styles ----------
        style = ttk.Style(self)
        style.configure("NoHover.TCheckbutton", background=self._BG_PANEL, foreground=self._FG_TEXT)
        style.map("NoHover.TCheckbutton",
                  background=[("active", self._BG_PANEL), ("!disabled", self._BG_PANEL)],
                  foreground=[("active", self._FG_TEXT), ("!disabled", self._FG_TEXT)])

        style.configure("Toolbar.TButton", background=self._BTN_BG, foreground=self._FG_TEXT,
                        borderwidth=0, padding=(8, 2))
        style.map("Toolbar.TButton",
                  background=[("active", self._BTN_BG_H), ("disabled", self._BTN_BG_D)],
                  foreground=[("disabled", self._FG_DIM)])

        style.configure("Primary.TButton", background=self._ACC_BG, foreground="#ffffff",
                        borderwidth=0, padding=(10, 4))
        style.map("Primary.TButton",
                  background=[("active", self._ACC_BG_H), ("disabled", self._ACC_BG_D)],
                  foreground=[("disabled", self._FG_DIM)])
        style.configure("Secondary.TButton", background=self._BTN_BG, foreground=self._FG_TEXT,
                        borderwidth=0, padding=(10, 4))
        style.map("Secondary.TButton",
                  background=[("active", self._BTN_BG_H)],
                  foreground=[("disabled", self._FG_DIM)])

        style.configure("Treeview",
                        background=self._BG_PANEL, fieldbackground=self._BG_PANEL,
                        foreground=self._FG_TEXT, borderwidth=0)
        style.configure("Treeview.Heading",
                        background=self._BTN_BG, foreground=self._FG_TEXT, relief="flat")
        style.map("Treeview.Heading",
                  background=[("active", self._BTN_BG_H), ("pressed", self._BTN_BG_H)],
                  foreground=[("active", self._FG_TEXT), ("pressed", self._FG_TEXT)])

        # ---------- Subpanel 1: Show Hiddens + Up + Home ----------
        topbar = tk.Frame(self.fm, bg=self._BG_PANEL)
        topbar.pack(side="top", fill="x")

        self.show_hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(topbar, text="Show Hiddens", variable=self.show_hidden,
                        command=self._on_show_hidden, style="NoHover.TCheckbutton",
                        takefocus=False).pack(side="left", padx=(8, 6), pady=6)

        self.up_btn = ttk.Button(topbar, text="Up", style="Toolbar.TButton", command=self._go_up)
        self.up_btn.pack(side="left", padx=(0, 6), pady=6)

        self.home_btn = ttk.Button(topbar, text="Home", style="Toolbar.TButton",
                                   command=lambda: self.set_cwd(Path.home()))
        self.home_btn.pack(side="left", padx=(0, 8), pady=6)

        # ---------- Subpanel 2: Tree ----------
        middle = tk.Frame(self.fm, bg=self._BG_PANEL)
        middle.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(middle, show="tree headings", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)

        # Headings clicks for sorting
        self.tree.heading("#0", text="Kind", command=lambda: self._on_heading_click("#0"))

        # Bold font for "Create New" rows
        base = tkfont.nametofont("TkDefaultFont")
        self._bold_font = tkfont.Font(self, family=base.cget("family"),
                                      size=base.cget("size"), weight="bold")
        self.tree.tag_configure("bold", font=self._bold_font)

        # Column width ratios (0..1) including the narrow safety column "safe"
        self._col_ratio = {
            "#0": 0.40,     # Kind (or Filename when Kind hidden)
            "name": 0.40,   # Filename (when Kind visible)
            "safe": 0.06,   # centered safety indicator column
            "size": 0.25,
            "modified": 0.25,
            "mode": 0.10,
        }
        self._col_min_px = {"#0": 90, "name": 150, "safe": 28, "size": 90, "modified": 140, "mode": 70}

        # === Column resize detection (update ratios only on real separator drags) ===
        self._resizing_col = False
        self.tree.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release, add="+")
        # Re-apply pixel widths from ratios on size changes
        self.tree.bind("<Configure>", lambda _e: self._apply_pixels_from_ratios())

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Map item_id -> dict(path=Path, kind='dir'|'file'|'create_dir'|'create_file', role='...')
        self._node = {}

        # Sorting state
        self._sort_key = "name"
        self._sort_desc = False
        self._last_cwd: Path | None = None

        # ---------- Subpanel 3: Metadata + visibility checkboxes ----------
        bottom = tk.Frame(self.fm, bg=self._BG_PANEL)
        bottom.pack(side="top", fill="x")

        form = tk.Frame(bottom, bg=self._BG_PANEL, highlightthickness=0, bd=0)
        form.pack(side="top", fill="x", padx=8, pady=(8, 6))
        form.grid_columnconfigure(2, weight=1)
        form.grid_columnconfigure(3, weight=0, minsize=24)  # small column for safety glyph

        # Column visibility toggles
        self.col_kind     = tk.BooleanVar(value=False)  # hidden by default
        self.col_name     = tk.BooleanVar(value=True)   # not toggleable in UI
        self.col_size     = tk.BooleanVar(value=True)
        self.col_modified = tk.BooleanVar(value=False)
        self.col_mode     = tk.BooleanVar(value=False)

        # Row 0: Kind
        ttk.Checkbutton(form, variable=self.col_kind, text="Kind",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.meta_kind = tk.Label(form, anchor="w", bg=self._BG_PANEL, fg=self._FG_TEXT)
        self.meta_kind.grid(row=0, column=2, sticky="ew", pady=2)

        # Row 1: Filename (non-toggleable)
        fn_frame = tk.Frame(form, bg=self._BG_PANEL)
        fn_frame.grid(row=1, column=0, sticky="w", padx=(0, 6))
        ttk.Checkbutton(fn_frame, variable=self.col_name, text="Filename",
                        style="NoHover.TCheckbutton", takefocus=False, state="disabled").pack(anchor="w")

        self.meta_filename = tk.Entry(form, bg=self._BG_ENTRY, fg=self._FG_TEXT,
                                      insertbackground=self._FG_TEXT, relief="flat")
        self.meta_filename.grid(row=1, column=2, sticky="ew", pady=2)

        # Safety glyph next to filename entry (🙂 safe; ☹ unsafe)
        self.meta_fname_flag = tk.Label(form, text="🙂", bg=self._BG_PANEL, fg=self._FG_TEXT, cursor="hand2")
        self.meta_fname_flag.grid(row=1, column=3, sticky="e", padx=(6, 0))
        self.meta_fname_flag.bind("<Button-1>", lambda _e: self._on_meta_flag_clicked())

        # Row 2: Size
        ttk.Checkbutton(form, variable=self.col_size, text="Size",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=2, column=0, sticky="w", padx=(0, 6))
        self.meta_size = tk.Label(form, anchor="w", bg=self._BG_PANEL, fg=self._FG_TEXT)
        self.meta_size.grid(row=2, column=2, sticky="ew", pady=2)

        # Row 3: Modified
        ttk.Checkbutton(form, variable=self.col_modified, text="Modified",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=3, column=0, sticky="w", padx=(0, 6))
        self.meta_modified = tk.Entry(form, bg=self._BG_ENTRY, fg=self._FG_TEXT,
                                      insertbackground=self._FG_TEXT, relief="flat")
        self.meta_modified.grid(row=3, column=2, sticky="ew", pady=2)

        # Row 4: Mode
        ttk.Checkbutton(form, variable=self.col_mode, text="Mode",
                        command=self._apply_tree_columns,
                        style="NoHover.TCheckbutton", takefocus=False)\
            .grid(row=4, column=0, sticky="w", padx=(0, 6))
        self.meta_mode = tk.Entry(form, bg=self._BG_ENTRY, fg=self._FG_TEXT,
                                  insertbackground=self._FG_TEXT, relief="flat")
        self.meta_mode.grid(row=4, column=2, sticky="ew", pady=2)

        # Buttons
        btns = tk.Frame(bottom, bg=self._BG_PANEL)
        btns.pack(side="top", fill="x", padx=8, pady=(0, 8))
        self.accept_btn = ttk.Button(btns, text="Accept", command=self._on_accept, style="Primary.TButton")
        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self._on_cancel, style="Secondary.TButton")
        self.accept_btn.pack(side="right")
        self.cancel_btn.pack(side="right", padx=(0, 8))
        self._set_accept_enabled(False)

        # Selection + originals for dirty tracking and create mode
        self._selected_path: Path | None = None
        self._meta_original = {"filename": "", "modified": "", "mode": ""}
        self._create_mode: str | None = None  # None | "dir" | "file"

        # Dirty tracking + dynamic safety glyph for filename entry
        for w in (self.meta_filename, self.meta_modified, self.meta_mode):
            w.bind("<KeyRelease>", self._on_meta_edited)

        # First-time column config
        self._apply_tree_columns()

    # ------------------- Safety icons & helpers -------------------

    def _filename_issues(self, name: str):
        """Collect issues from both checkers (aggressive for deceptive_line_check)."""
        issues = []
        for _i, msg in deceptive_line_check(name, low_aggression=False):
            issues.append(msg)
        for _i, msg in bad_filename_check(name):
            issues.append(msg)
        return issues

    def _is_name_safe(self, name: str) -> bool:
        # UI rule: empty string is considered "fine" for display
        return (name is None) or (name == "") or (len(self._filename_issues(name)) == 0)

    def _tree_safety_icon(self, name: str) -> str:
        """Icon for Subpanel 2 '!' column: empty if safe, ☹ if not."""
        return "" if self._is_name_safe(name) else "☹"

    def _meta_safety_icon(self, name: str) -> str:
        """Icon for Subpanel 3 next to the Filename entry: 🙂 if safe, ☹ if not."""
        return "🙂" if self._is_name_safe(name) else "☹"

    # ------------------- Column model -------------------

    def _visible_cols(self):
        """Visible columns in UI order. '#0' is always present; include 'safe' after filename."""
        cols = ["#0"]
        if self.col_kind.get():
            cols += ["name", "safe"]
        else:
            cols += ["safe"]  # when Kind hidden, '#0' shows Filename; still include 'safe'
        if self.col_size.get():     cols.append("size")
        if self.col_modified.get(): cols.append("modified")
        if self.col_mode.get():     cols.append("mode")
        return cols

    def _tree_columns(self):
        """Return (data_columns, headings). Does not include '#0'."""
        cols = []
        heads = {}
        if self.col_kind.get():
            cols += ["name", "safe"]; heads["name"] = "Filename"; heads["safe"] = "!"
        else:
            cols += ["safe"]; heads["safe"] = "!"
        if self.col_size.get():
            cols.append("size");     heads["size"] = "Size"
        if self.col_modified.get():
            cols.append("modified"); heads["modified"] = "Modified"
        if self.col_mode.get():
            cols.append("mode");     heads["mode"] = "Mode"
        return cols, heads

    def _apply_tree_columns(self):
        """Reconfigure columns (headings, widths) and refresh rows; DO NOT change ratios here."""
        cols, heads = self._tree_columns()
        self.tree.configure(columns=cols)

        # Headings + sort handlers (no sorting on the safety "!" column)
        self.tree.heading("#0", text=self._sort_label_for("#0"), command=lambda: self._on_heading_click("#0"))
        for c in ("name", "safe", "size", "modified", "mode"):
            if c not in cols:
                continue
            if c == "safe":
                self.tree.heading(c, text=heads.get(c, "!"))
                continue
            label = self._sort_label_for(c)
            self.tree.heading(c, text=label, command=lambda col=c: self._on_heading_click(col))

        # Apply widths from ratios (fill full width)
        self._apply_pixels_from_ratios()

        # Rebuild rows (keep sort & selection)
        self.refresh_file_panel()

    def _apply_pixels_from_ratios(self):
        """Compute pixel widths from ratios so visible columns fill the full width (respect mins)."""
        vis = self._visible_cols()
        if not vis:
            return
        tree_w = max(self.tree.winfo_width(), 1)
        if tree_w <= 2:
            self.tree.after(16, self._apply_pixels_from_ratios)
            return

        for c in ["#0", "name", "safe", "size", "modified", "mode"]:
            self._col_ratio.setdefault(c, 1.0 / 3.0)

        vis_sum = sum(self._col_ratio.get(c, 0.0) for c in vis)
        if vis_sum <= 0:
            equal = 1.0 / float(len(vis))
            for c in vis:
                self._col_ratio[c] = equal
            vis_sum = 1.0

        px = []
        for c in vis:
            r = self._col_ratio.get(c, 0.0) / vis_sum
            w = int(round(r * tree_w))
            w = max(self._col_min_px.get(c, 50), w)
            px.append(w)

        diff = tree_w - sum(px)
        if px:
            px[-1] += diff

        for c, w in zip(vis, px):
            # '#0' and 'name' left; 'safe' centered; others left
            if c in ("#0", "name"):
                anchor = "w"
            elif c == "safe":
                anchor = "center"
            else:
                anchor = "w"
            self.tree.column(c if c != "#0" else "#0", width=max(1, w), stretch=True, anchor=anchor)

        # Park hidden data columns to a sane min (not visible; doesn't affect ratios)
        for c in ("name", "safe", "size", "modified", "mode"):
            if c not in self.tree["columns"]:
                continue
            if c not in vis:
                self.tree.column(c, width=self._col_min_px.get(c, 50), stretch=False, anchor="w")

    # === User resize detection → update target ratios ===

    def _on_tree_press(self, event):
        region = self.tree.identify_region(event.x, event.y)
        self._resizing_col = (region == "separator")

    def _on_tree_release(self, event):
        if self._resizing_col:
            self._update_ratios_from_visible_pixels()
        self._resizing_col = False

    def _update_ratios_from_visible_pixels(self):
        """After a real resize gesture, convert current visible pixels to target ratios."""
        vis = self._visible_cols()
        if not vis:
            return
        widths = []
        for c in vis:
            try:
                w = int(self.tree.column(c if c != "#0" else "#0", option="width"))
            except Exception:
                w = 1
            widths.append(max(1, w))
        total = sum(widths) or 1
        for c, w in zip(vis, widths):
            self._col_ratio[c] = w / total
        # Re-apply to remove rounding creep
        self._apply_pixels_from_ratios()

    # ------------------- Rendering & stable sorting -------------------

    def _on_show_hidden(self):
        self.refresh_file_panel()

    def refresh_file_panel(self):
        """Re-render the tree; preserves selection and column sizing."""
        cols, heads = self._tree_columns()
        self.tree.configure(columns=cols)

        self.tree.heading("#0", text=self._sort_label_for("#0"), command=lambda: self._on_heading_click("#0"))
        for c in ("name", "safe", "size", "modified", "mode"):
            if c in cols:
                if c == "safe":
                    self.tree.heading(c, text=heads.get(c, "!"))
                else:
                    self.tree.heading(c, text=self._sort_label_for(c),
                                      command=lambda col=c: self._on_heading_click(col))

        self._apply_pixels_from_ratios()

        cwd_changed = (self._last_cwd is None) or (self.cwd != self._last_cwd)
        self._last_cwd = self.cwd

        selected_before = self._selected_path
        rank_dirs, rank_files = self._current_order_ranks()

        self.tree.delete(*self.tree.get_children())
        self._node.clear()

        # Breadcrumbs (unsorted)
        for path, name in self._breadcrumb_items():
            meta = self._values_for_path(path)
            safe = self._tree_safety_icon(name)
            if self.col_kind.get():
                row_text = meta.get("#0", "Folder")
                row_vals = []
                for dc in cols:
                    if dc == "name":
                        row_vals.append(name)
                    elif dc == "safe":
                        row_vals.append(safe)
                    else:
                        row_vals.append(meta.get(dc, ""))
            else:
                row_text = name
                row_vals = []
                for dc in cols:
                    if dc == "safe":
                        row_vals.append(safe)
                    else:
                        row_vals.append(meta.get(dc, ""))
            iid = self.tree.insert("", "end", text=row_text, values=row_vals)
            self._node[iid] = {"path": path, "kind": "dir", "role": "breadcrumb"}

        # Create New Folder (bold)
        sep1_vals = []
        for dc in cols:
            sep1_vals.append("" if dc != "name" else "=== Create New Folder ===")
        sep1_text = "" if self.col_kind.get() else "=== Create New Folder ==="
        sep1 = self.tree.insert("", "end", text=sep1_text, values=sep1_vals, tags=("bold",))
        self._node[sep1] = {"path": None, "kind": "create_dir"}

        # CWD entries
        try:
            entries = list(self.cwd.iterdir())
        except Exception:
            entries = []
        show_hidden = self.show_hidden.get()
        dirs = [e for e in entries if e.is_dir() and (show_hidden or not e.name.startswith("."))]
        files = [e for e in entries if e.is_file() and (show_hidden or not e.name.startswith("."))]

        # On directory change, start from filename sort; otherwise keep current order ranks.
        if cwd_changed:
            dirs = sorted(dirs, key=lambda p: p.name.lower())
            files = sorted(files, key=lambda p: p.name.lower())
        else:
            dirs = sorted(dirs, key=lambda p: rank_dirs.get(p.resolve(), 10**9))
            files = sorted(files, key=lambda p: rank_files.get(p.resolve(), 10**9))

        # Then apply current sort stably
        dirs = self._stably_sort_entries(dirs)
        files = self._stably_sort_entries(files)

        # Insert dirs
        for d in dirs:
            meta = self._values_for_path(d)
            safe = self._tree_safety_icon(d.name)
            if self.col_kind.get():
                row_text = meta.get("#0", "Folder")
                row_vals = [meta.get(dc, "") if dc not in ("name", "safe")
                            else (d.name if dc == "name" else safe) for dc in cols]
            else:
                row_text = d.name
                row_vals = [meta.get(dc, "") if dc != "safe" else safe for dc in cols]
            iid = self.tree.insert("", "end", text=row_text, values=row_vals)
            self._node[iid] = {"path": d, "kind": "dir", "role": "cwd-dir"}

        # Create New File (bold)
        sep2_vals = []
        for dc in cols:
            sep2_vals.append("" if dc != "name" else "=== Create New File ===")
        sep2_text = "" if self.col_kind.get() else "=== Create New File ==="
        sep2 = self.tree.insert("", "end", text=sep2_text, values=sep2_vals, tags=("bold",))
        self._node[sep2] = {"path": None, "kind": "create_file"}

        # Insert files
        for f in files:
            meta = self._values_for_path(f)
            safe = self._tree_safety_icon(f.name)
            if self.col_kind.get():
                row_text = meta.get("#0", "File")
                row_vals = [meta.get(dc, "") if dc not in ("name", "safe")
                            else (f.name if dc == "name" else safe) for dc in cols]
            else:
                row_text = f.name
                row_vals = [meta.get(dc, "") if dc != "safe" else safe for dc in cols]
            iid = self.tree.insert("", "end", text=row_text, values=row_vals)
            self._node[iid] = {"path": f, "kind": "file", "role": "cwd-file"}

        self._update_nav_buttons()
        if selected_before is not None:
            self._select_path(selected_before)

        # also refresh metadata safety glyph if there's a selected path or typed text
        self._update_meta_safety_from_entry()

    # ------------------- Sorting helpers -------------------

    def _effective_sort_attr(self, col: str) -> str:
        if col == "#0":
            return "kind" if self.col_kind.get() else "name"
        return col

    def _stably_sort_entries(self, entries):
        key = self._effective_sort_attr(self._sort_key)
        reverse = self._sort_desc

        def k(p: Path):
            try:
                if key == "name":
                    return p.name.lower()
                st = p.stat()
                if key == "kind":
                    return "Folder" if p.is_dir() else "File"
                if key == "size":
                    return -1 if p.is_dir() else st.st_size
                if key == "modified":
                    return st.st_mtime
                if key == "mode":
                    return stat.S_IMODE(st.st_mode)
            except Exception:
                return 0
            return p.name.lower()

        # Python's sort is stable: applying this after an initial name sort preserves
        # that order among equal keys.
        return sorted(entries, key=k, reverse=reverse)

    def _current_order_ranks(self):
        rank_dirs, rank_files = {}, {}
        if not self._node:
            return rank_dirs, rank_files
        idx_dir = idx_file = 0
        for iid in self.tree.get_children(""):
            meta = self._node.get(iid)
            if not meta:
                continue
            role = meta.get("role")
            p = meta.get("path")
            if role == "cwd-dir" and p:
                rank_dirs[Path(p).resolve()] = idx_dir; idx_dir += 1
            elif role == "cwd-file" and p:
                rank_files[Path(p).resolve()] = idx_file; idx_file += 1
        return rank_dirs, rank_files

    def _on_heading_click(self, col: str):
        # Toggle sort; DO NOT touch ratios here.
        if col == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key = col
            self._sort_desc = False
        self.refresh_file_panel()

    def _sort_label_for(self, col: str) -> str:
        if col == "#0":
            base = "Kind" if self.col_kind.get() else "Filename"
        else:
            base = "Filename" if col == "name" else ("!" if col == "safe" else col.capitalize())
        if col == self._sort_key and col != "safe":
            return f"{base} {'▼' if not self._sort_desc else '▲'}"
        return base

    # ------------------- Selection & metadata -------------------

    def _on_tree_select(self, _evt):
        iid = self._first_selection()
        if not iid:
            return
        info = self._node.get(iid, {})
        kind = info.get("kind")

        if kind == "create_dir":
            self._enter_create_mode("dir"); return
        if kind == "create_file":
            self._enter_create_mode("file"); return

        if kind in ("dir", "file"):
            path = info.get("path")
            if path:
                self._selected_path = path
                self._create_mode = None
                self._load_metadata_from_path(path)

    def _enter_create_mode(self, what: str):
        self._selected_path = None
        self._create_mode = what
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode = "0755" if what == "dir" else "0644"
        kind = "Folder" if what == "dir" else "File"
        size = "-" if what == "dir" else "0 B"

        self.meta_filename.delete(0, tk.END)
        self.meta_kind.config(text=kind)
        self.meta_size.config(text=size)
        self.meta_modified.delete(0, tk.END); self.meta_modified.insert(0, now)
        self.meta_mode.delete(0, tk.END);     self.meta_mode.insert(0, mode)

        self._meta_original = {"filename": "", "modified": now, "mode": mode}
        self._set_accept_enabled(False)
        self._update_meta_safety_from_entry()
        self.meta_filename.focus_set()

    def _on_tree_double_click(self, _evt):
        iid = self._first_selection()
        if not iid:
            return
        info = self._node.get(iid)
        if not info:
            return
        if info.get("kind") == "dir":
            self.set_cwd(info["path"])

    def _first_selection(self):
        sels = self.tree.selection()
        return sels[0] if sels else None

    def _select_path(self, p: Path):
        target = None
        for iid, meta in self._node.items():
            if meta.get("path") and Path(meta["path"]).resolve() == Path(p).resolve():
                target = iid; break
        if target:
            try:
                self.tree.selection_set(target)
                self.tree.focus(target)
                self.tree.see(target)
            except Exception:
                pass

    def _load_metadata_from_path(self, p: Path):
        try:
            st = p.stat()
        except Exception as e:
            messagebox.showerror("Error", f"Unable to stat: {p}\n{e}")
            return

        kind = "Folder" if p.is_dir() else "File"
        size = "-" if p.is_dir() else self._human_size(st.st_size)
        mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        mode_str = f"{stat.S_IMODE(st.st_mode):04o}"

        self.meta_filename.delete(0, tk.END); self.meta_filename.insert(0, p.name)
        self.meta_kind.config(text=kind)
        self.meta_size.config(text=size)
        self.meta_modified.delete(0, tk.END); self.meta_modified.insert(0, mtime_str)
        self.meta_mode.delete(0, tk.END);     self.meta_mode.insert(0, mode_str)

        self._meta_original = {"filename": p.name, "modified": mtime_str, "mode": mode_str}
        self._create_mode = None
        self._set_accept_enabled(False)
        self._update_meta_safety_from_entry()

    def _on_meta_edited(self, _evt):
        # live-update the little safety glyph
        self._update_meta_safety_from_entry()

        if self._create_mode:
            filename_ok = True  # empty string allowed visually; creation still requires non-empty at Accept
            modified_ok = self._validate_datetime(self.meta_modified.get().strip())
            mode_ok     = self._validate_mode(self.meta_mode.get().strip())
            filename_nonempty = bool(self.meta_filename.get().strip())
            self._set_accept_enabled(filename_nonempty and modified_ok and mode_ok)
            return

        if not self._selected_path:
            self._set_accept_enabled(False)
            return

        dirty = (
            self.meta_filename.get() != self._meta_original["filename"] or
            self.meta_modified.get() != self._meta_original["modified"] or
            self.meta_mode.get()     != self._meta_original["mode"]
        )
        self._set_accept_enabled(dirty)

    def _set_accept_enabled(self, enabled: bool):
        if enabled: self.accept_btn.state(["!disabled"])
        else:       self.accept_btn.state(["disabled"])

    # ------------------- Accept / Cancel -------------------

    def _on_accept(self):
        # CREATE mode
        if self._create_mode:
            name = self.meta_filename.get().strip()
            if not name:
                messagebox.showerror("Invalid", "Please enter a filename or folder name.")
                return
            mod_str  = self.meta_modified.get().strip()
            mode_str = self.meta_mode.get().strip()

            ok, mod_ts = self._parse_datetime(mod_str)
            if not ok:
                messagebox.showerror("Invalid Modified", "Use format: YYYY-MM-DD HH:MM:SS"); return
            ok, mode_val = self._parse_mode(mode_str)
            if not ok:
                messagebox.showerror("Invalid Mode", "Enter an octal like 0644 or 755 (0–7777)."); return

            try:
                target = Path(name)
                if not target.is_absolute():
                    target = (self.cwd / target).resolve()
            except Exception as e:
                messagebox.showerror("Invalid Filename", f"Cannot resolve path: {name}\n{e}"); return
            if target.exists():
                messagebox.showerror("Exists", f"Target already exists:\n{target}"); return

            try:
                if self._create_mode == "dir":
                    target.mkdir(parents=True, exist_ok=False)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "x"): pass
                st = target.stat()
                os.utime(target, (st.st_atime, mod_ts))
                os.chmod(target, mode_val)
            except Exception as e:
                messagebox.showerror("Create Failed", f"Could not create:\n{e}"); return

            self.refresh_file_panel()
            self._selected_path = target
            self._select_path(target)
            self._load_metadata_from_path(target)
            self._create_mode = None
            self._set_accept_enabled(False)
            return

        # EDIT mode
        if not self._selected_path:
            return

        src = self._selected_path
        was_cwd = (src == self.cwd)
        new_name = self.meta_filename.get().strip()
        if new_name == "":
            messagebox.showerror("Invalid", "Filename cannot be empty.")
            return
        new_mtime_str = self.meta_modified.get().strip()
        new_mode_str  = self.meta_mode.get().strip()

        ok, new_mtime_ts = self._parse_datetime(new_mtime_str)
        if not ok:
            messagebox.showerror("Invalid Modified", "Use format: YYYY-MM-DD HH:MM:SS"); return
        ok, mode_val = self._parse_mode(new_mode_str)
        if not ok:
            messagebox.showerror("Invalid Mode", "Enter an octal like 0644 or 755 (0–7777)."); return

        try:
            target = Path(new_name)
            if not target.is_absolute():
                target = (src.parent / target).resolve()
        except Exception as e:
            messagebox.showerror("Invalid Filename", f"Cannot resolve path: {new_name}\n{e}"); return

        do_rename = (target != src)
        if do_rename and target.exists():
            messagebox.showerror("Exists", f"Target already exists:\n{target}"); return

        try:
            if do_rename:
                src.rename(target)
                src = target
                self._selected_path = target
                if was_cwd and target.is_dir():
                    self.set_cwd(target)

            st = src.stat()
            os.utime(src, (st.st_atime, new_mtime_ts))
            os.chmod(src, mode_val)
        except Exception as e:
            messagebox.showerror("Apply Failed", f"Could not apply changes:\n{e}"); return

        if not was_cwd:
            self.refresh_file_panel()
        self._selected_path = src
        self._select_path(src)
        self._load_metadata_from_path(src)
        self._set_accept_enabled(False)

    def _on_cancel(self):
        if self._create_mode:
            self._create_mode = None
            self.refresh_file_panel()
            return

        if not self._selected_path:
            self._set_accept_enabled(False)
            return

        self._load_metadata_from_path(self._selected_path)
        self._set_accept_enabled(False)

    # ------------------- Safety: dialog from metadata face only -------------------

    def _on_meta_flag_clicked(self):
        """Clicking the face next to the Filename entry opens the dialog on the Entry text (if issues)."""
        current = self.meta_filename.get()
        issues = self._filename_issues(current)
        if not issues:
            return
        self._show_safety_dialog_and_maybe_sanitize(current)

    def _show_safety_dialog_and_maybe_sanitize(self, name: str):
        issues = self._filename_issues(name)
        if not issues:
            return
        msg = "The current filename has potential issues:\n\n- " + "\n- ".join(issues) + \
              "\n\nSanitize now? (You can still review and Accept later.)"
        if messagebox.askyesno("Filename Safety", msg, icon="warning", default="yes"):
            new_name = name
            dls = deceptive_line_sanitize(new_name, low_aggression=False)
            if dls is not None:
                new_name = dls
            bfs = bad_filename_sanitize(new_name)
            if bfs is not None:
                new_name = bfs

            if new_name != name:
                self.meta_filename.delete(0, tk.END)
                self.meta_filename.insert(0, new_name)
                # mark dirty
                self._on_meta_edited(None)
            else:
                messagebox.showinfo("Sanitize", "No changes were necessary after sanitation.")

    def _update_meta_safety_from_entry(self):
        """Update the 🙂 / ☹ glyph next to the filename entry to reflect current text."""
        name = self.meta_filename.get()
        icon = self._meta_safety_icon(name)
        is_safe = (icon == "🙂")
        self.meta_fname_flag.config(text=icon,
                                    fg=(self._FG_TEXT if is_safe else self._ERR_RED))

    # ------------------- helpers -------------------

    def _go_up(self):
        if not self.cwd:
            return
        parent = self.cwd.parent
        if parent and parent != self.cwd and parent.exists():
            self.set_cwd(parent)

    def _update_nav_buttons(self):
        try:
            parent = self.cwd.parent if self.cwd else None
            at_root = (not self.cwd) or (parent == self.cwd) or (parent is None) or (not parent.exists())
            if at_root: self.up_btn.state(["disabled"])
            else:       self.up_btn.state(["!disabled"])
        except Exception:
            self.up_btn.state(["disabled"])

    def _breadcrumb_items(self):
        p = Path(self.cwd).resolve() if getattr(self, "cwd", None) else None
        if not p:
            return []
        parts = list(p.parts)
        items = []
        if p.anchor:
            acc = Path(p.anchor); start_idx = 1
        else:
            acc = Path(parts[0]) if parts else Path("."); start_idx = 1 if parts else 0
        for name in parts[start_idx:]:
            acc = acc / name; items.append((acc, name))
        if not items and parts:
            items.append((p, parts[-1]))
        return items

    def _values_for_path(self, p: Path) -> dict:
        out = {"#0": "", "name": "", "size": "", "modified": "", "mode": ""}
        try:
            st = p.stat()
            is_dir = p.is_dir()
            out["#0"] = "Folder" if is_dir else "File"
            out["name"] = p.name
            out["size"] = "-" if is_dir else self._human_size(st.st_size)
            out["modified"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            out["mode"] = f"{stat.S_IMODE(st.st_mode):04o}"
        except Exception:
            out["#0"] = "Folder" if p.is_dir() else "File"
            out["name"] = p.name
        return out

    @staticmethod
    def _human_size(n: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]; i = 0; f = float(n)
        while f >= 1024 and i < len(units) - 1:
            f /= 1024.0; i += 1
        return f"{f:.1f} {units[i]}"

    @staticmethod
    def _validate_datetime(s: str) -> bool:
        try:
            time.strptime(s, "%Y-%m-%d %H:%M:%S"); return True
        except Exception:
            return False

    @staticmethod
    def _parse_datetime(s: str):
        try:
            return True, time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
        except Exception:
            return False, None

    @staticmethod
    def _validate_mode(s: str) -> bool:
        try:
            cleaned = s.strip().lstrip("0") or "0"
            v = int(cleaned, 8); return 0 <= v <= 0o7777
        except Exception:
            return False

    @staticmethod
    def _parse_mode(s: str):
        try:
            cleaned = s.strip().lstrip("0") or "0"
            v = int(cleaned, 8)
            if not (0 <= v <= 0o7777): return False, None
            return True, v
        except Exception:
            return False, None
