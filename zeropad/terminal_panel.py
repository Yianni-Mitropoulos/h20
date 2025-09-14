import os
import shlex
import shutil
import signal
import subprocess
import time
import uuid
import tkinter as tk
from pathlib import Path

# Hard-require python-xlib (install: sudo apt install python3-xlib)
from Xlib import display as xdisplay, X


class TerminalPanel:
    """
    Hardened xterm+tmux embed with:
      • Private tmux UNIX socket (0700 dir, 0600 sock)
      • Xlib-only pixel resizing (fills panel) + tmux grid sync
      • CWD sync both ways (poll tmux; push cd from app)
      • Ctrl+D passthrough to tmux via a global, highest-priority bindtag
      • Auto-respawn if xterm/tmux dies
      • Clean shutdown on app close

    NOTE: Ctrl+Z passthrough was removed per request. We'll handle that differently later.
    """

    POLL_MS = 800              # tmux cwd poll
    SIZE_PERIODIC_MS = 1200    # periodic size reconcile (safety net)
    RESPAWN_COOLDOWN = 1.0     # seconds

    def init_terminal_panel(self):
        palette = getattr(self, "_palette", {})
        self._TERM_BG = palette.get("BG_CANVAS", "#0b1220")
        self._TERM_FG = palette.get("FG_TEXT",   "#e5e7eb")

        # Unique tmux session + private socket dir/path per run
        self.TMUX_SESSION = "zeropad"
        run_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.TMUX_DIR  = Path.home() / ".cache" / "zeropad-tmux" / run_id
        self.TMUX_SOCK = self.TMUX_DIR / "sock"

        # Terminal pane
        self.terminal = tk.Frame(self.vpaned, bg=self._TERM_BG)
        self._term_container = tk.Frame(self.terminal, bg=self._TERM_BG, highlightthickness=0, bd=0)
        self._term_container.pack(fill="both", expand=True)

        # Processes/state
        self._xterm_proc: subprocess.Popen | None = None
        self._xterm_started = False
        self._tmux_ready = False
        self._last_tmux_cwd: Path | None = None
        self._pending_cd: Path | None = None

        # Size tracking
        self._cell_w = 8.0
        self._cell_h = 16.0
        self._client_tty: str | None = None

        # Xlib
        self._x_dpy = None
        self._x_child = None

        # Key passthrough / intercept
        self._terminal_active = False
        self._intercept_tag = "ZP_TermIntercept"
        self._intercept_installed = False

        # Respawn guard
        self._last_respawn = 0.0

        # Private tmux socket dir (0700)
        try:
            self.TMUX_DIR.mkdir(mode=0o700, parents=True, exist_ok=False)
        except FileExistsError:
            try:
                os.chmod(self.TMUX_DIR, 0o700)
            except Exception:
                pass
        except Exception as e:
            self._show_error(f"Failed to create tmux dir: {e}")
            return

        # Spawn xterm/tmux when container is mapped
        self.after(50, self._maybe_spawn_xterm)

        # --- IMMEDIATE resize on every container <Configure> ---
        self._term_container.bind("<Configure>", self._on_container_configure)

        # Activation: clicking/focusing terminal enables intercept
        self._term_container.bind("<Button-1>", self._on_terminal_click)
        self._term_container.bind("<FocusIn>",  self._on_terminal_focus)
        self._term_container.bind("<FocusOut>", self._on_terminal_blur)

        # Bind handlers to our custom high-priority tag
        # (Only Ctrl+D now; Ctrl+Z removed.)
        self.bind_class(self._intercept_tag, "<Control-Key-d>", self._intercept_ctrl, add="+")

        # Periodic size reconcile (safety net) + cleanup hook
        self.after(self.SIZE_PERIODIC_MS, self._periodic_size_reconcile)
        if not hasattr(self, "_cleanup_hooks"):
            self._cleanup_hooks = []
        self._cleanup_hooks.append(self._terminal_cleanup)

    # ---------- Activation & global intercept ----------

    def _on_terminal_click(self, _e):
        self._terminal_active = True
        try:
            self._term_container.focus_set()
        except Exception:
            pass
        self._install_global_intercept()

    def _on_terminal_focus(self, _e):
        self._terminal_active = True
        self._install_global_intercept()

    def _on_terminal_blur(self, _e):
        # Deactivate on blur so other widgets regain normal shortcuts
        self._terminal_active = False
        self._remove_global_intercept()

    def _install_global_intercept(self):
        """Insert our custom tag at the FRONT of every widget's bindtags."""
        if self._intercept_installed:
            return
        for w in self._walk_widgets(self):
            try:
                tags = list(w.bindtags())
                if tags and tags[0] != self._intercept_tag:
                    if self._intercept_tag in tags:
                        tags.remove(self._intercept_tag)
                    tags.insert(0, self._intercept_tag)
                    w.bindtags(tuple(tags))
            except Exception:
                continue
        self._intercept_installed = True

    def _remove_global_intercept(self):
        if not self._intercept_installed:
            return
        for w in self._walk_widgets(self):
            try:
                tags = list(w.bindtags())
                if self._intercept_tag in tags:
                    tags.remove(self._intercept_tag)
                    w.bindtags(tuple(tags))
            except Exception:
                continue
        self._intercept_installed = False

    def _intercept_ctrl(self, event):
        """
        High-priority handler (runs before widget/class/toplevel/all).
        Forwards Ctrl+D to tmux and suppresses Tk default handling when terminal is active.
        """
        if not self._terminal_active:
            return  # let normal Tk bindings handle it
        ks = (event.keysym or "").lower()
        if ks == "d":
            self._tmux_send_ctrl("d")
            return "break"
        # Not one we handle -> let others process

    @staticmethod
    def _walk_widgets(root):
        """Yield root and all descendants."""
        stack = [root]
        while stack:
            w = stack.pop()
            yield w
            try:
                stack.extend(w.winfo_children())
            except Exception:
                pass

    def _tmux_send_ctrl(self, letter: str):
        if not self._tmux_ready:
            return
        tmux = shutil.which("tmux")
        if not tmux:
            return
        subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "send-keys", f"C-{letter.lower()}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    # ---------- Lifecycle / spawn ----------

    def _maybe_spawn_xterm(self):
        if self._xterm_started:
            self.after(self.POLL_MS, self._poll_tmux_cwd)
            return

        if not self._term_container.winfo_ismapped():
            self.after(50, self._maybe_spawn_xterm)
            return

        xterm_path = shutil.which("xterm")
        tmux_path  = shutil.which("tmux")
        if not xterm_path or not tmux_path:
            self._show_missing_tools(xterm_path, tmux_path)
            return

        # Container X window id
        self._term_container.update_idletasks()
        wid = self._term_container.winfo_id()

        bg = self._TERM_BG
        fg = self._TERM_FG

        # Fresh tmux session on private socket
        tmux_cmd = [tmux_path, "-S", str(self.TMUX_SOCK), "new-session", "-s", self.TMUX_SESSION]

        cmd = [
            xterm_path,
            "-into", str(wid),
            "-fa", "Monospace", "-fs", "11",
            "-bg", bg, "-fg", fg, "+sb", "-bc", "-cr", fg,
            "-vb", "-xrm", "XTerm.vt100.bellIsUrgent: false",
            "-e", *tmux_cmd,
        ]

        def _preexec():
            os.setsid()
            os.umask(0o077)

        try:
            self._xterm_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_preexec
            )
            self._xterm_started = True
        except Exception as e:
            self._show_error(f"Failed to start xterm: {e}")
            return

        try:
            self._x_dpy = xdisplay.Display()
        except Exception as e:
            self._show_error(f"Xlib display error: {e}")
            return

        self.after(600, self._mark_tmux_ready_and_prime)

    def _mark_tmux_ready_and_prime(self):
        self._tmux_ready = self._tmux_has_session()
        if self._tmux_ready:
            self._tmux_quiet_bell()
            self._client_tty = self._tmux_first_client_tty()
            if self._pending_cd:
                self._tmux_cd_to(self._pending_cd)
                self._pending_cd = None
        self.after(self.POLL_MS, self._poll_tmux_cwd)
        self.after(200, self._discover_xchild)

    # ---------- Keep-alive / respawn ----------

    def _ensure_alive(self):
        now = time.time()
        if self._xterm_proc and self._xterm_proc.poll() is not None:
            if now - self._last_respawn >= self.RESPAWN_COOLDOWN:
                self._last_respawn = now
                self._respawn_xterm_and_tmux()
            return
        if not self._tmux_has_session():
            if now - self._last_respawn >= self.RESPAWN_COOLDOWN:
                self._last_respawn = now
                self._restart_tmux_session()

    def _respawn_xterm_and_tmux(self):
        tmux = shutil.which("tmux")
        if tmux:
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "kill-server"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        p = self._xterm_proc
        if p:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                p.wait(timeout=0.6)
            except Exception:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:
                    pass
        self._xterm_proc = None
        self._xterm_started = False
        self._tmux_ready = False
        self._client_tty = None
        self._x_child = None
        self._maybe_spawn_xterm()

    def _restart_tmux_session(self):
        tmux = shutil.which("tmux")
        if not tmux:
            return
        r = subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "new-session", "-ds", self.TMUX_SESSION],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if r.returncode == 0:
            self._tmux_ready = True
            self._tmux_quiet_bell()
            self._client_tty = self._tmux_first_client_tty()
            try:
                if getattr(self, "cwd", None):
                    self._tmux_cd_to(Path(self.cwd))
            except Exception:
                pass

    # ---------- Timers ----------

    def _poll_tmux_cwd(self):
        try:
            self._ensure_alive()
            if not self._tmux_ready:
                self._tmux_ready = self._tmux_has_session()
            if self._tmux_ready:
                pane_cwd = self._tmux_get_cwd()
                if pane_cwd:
                    p = Path(pane_cwd).resolve()
                    if self._last_tmux_cwd is None or p != self._last_tmux_cwd:
                        self._last_tmux_cwd = p
                        if getattr(self, "cwd", None) is None or p != Path(self.cwd).resolve():
                            try:
                                self.set_cwd(p, origin="terminal")
                            except TypeError:
                                self.set_cwd(p)
        finally:
            self.after(self.POLL_MS, self._poll_tmux_cwd)

    # ---------- Immediate sizing ----------

    def _on_container_configure(self, _e):
        """Immediate resize on every geometry change."""
        self._immediate_resize()

    def _periodic_size_reconcile(self):
        """Safety net to keep sizes in sync (handles rare missed events)."""
        try:
            self._immediate_resize()
        finally:
            self.after(self.SIZE_PERIODIC_MS, self._periodic_size_reconcile)

    def _immediate_resize(self):
        if not self._xterm_started:
            return
        self._ensure_alive()
        w_px = max(self._term_container.winfo_width(), 1)
        h_px = max(self._term_container.winfo_height(), 1)
        self._resize_xterm_child(w_px, h_px)

        if not self._tmux_ready:
            return
        # Refine cell size and refresh tmux client grid
        pane_cols, pane_rows = self._tmux_get_pane_size()
        cur_cols, cur_rows   = self._tmux_get_client_size()
        ref_cols = pane_cols or cur_cols or 80
        ref_rows = pane_rows or cur_rows or 24
        if ref_cols > 0 and ref_rows > 0:
            alpha = 0.35
            est_w = w_px / max(ref_cols, 1)
            est_h = h_px / max(ref_rows, 1)
            self._cell_w = (1 - alpha) * self._cell_w + alpha * est_w
            self._cell_h = (1 - alpha) * self._cell_h + alpha * est_h
        want_cols = max(20, min(400, int(round(w_px / max(self._cell_w, 1.0)))))
        want_rows = max(5,  min(200, int(round(h_px / max(self._cell_h, 1.0)))))
        cc = self._tmux_get_client_size()
        if cc != (want_cols, want_rows):
            self._tmux_refresh_client(want_cols, want_rows)

    # --- Xlib helpers ---

    def _discover_xchild(self):
        if self._x_child is not None or self._x_dpy is None:
            return
        try:
            parent_id = self._term_container.winfo_id()
            parent = self._x_dpy.create_resource_object('window', parent_id)
            tree = parent.query_tree()
            chosen = None
            for child in tree.children:
                try:
                    cls = child.get_wm_class()
                    if cls and any("xterm" in s.lower() for s in cls):
                        chosen = child
                        break
                except Exception:
                    continue
            if not chosen and tree.children:
                chosen = tree.children[0]
            if chosen:
                self._x_child = chosen.id
        except Exception:
            self._x_child = None

    def _resize_xterm_child(self, w_px: int, h_px: int):
        if self._x_dpy is None:
            return
        if self._x_child is None:
            self._discover_xchild()
            if self._x_child is None:
                return
        try:
            win = self._x_dpy.create_resource_object('window', self._x_child)
            win.configure(width=max(1, int(w_px)), height=max(1, int(h_px)),
                          border_width=0, stack_mode=X.Above)
            self._x_dpy.sync()
        except Exception:
            self._x_child = None  # try rediscover next time

    # ---------- Public API ----------

    def terminal_set_cwd(self, path: Path | str):
        target = Path(path).resolve()
        if not self._tmux_ready:
            self._pending_cd = target
            return
        self._tmux_cd_to(target)

    # ---------- tmux helpers (private socket -S) ----------

    def _tmux_has_session(self) -> bool:
        tmux = shutil.which("tmux")
        if not tmux:
            return False
        r = subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "has-session", "-t", self.TMUX_SESSION],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return r.returncode == 0

    def _tmux_first_client_tty(self) -> str | None:
        tmux = shutil.which("tmux")
        if not tmux:
            return None
        r = subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "list-clients", "-t", self.TMUX_SESSION,
                            "-F", "#{client_tty}"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, check=False)
        lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        return lines[0] if lines else None

    def _tmux_get_cwd(self) -> str | None:
        tmux = shutil.which("tmux")
        if not tmux:
            return None
        r = subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "display-message",
                            "-t", self.TMUX_SESSION, "-p", "-F", "#{pane_current_path}"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        s = (r.stdout or "").strip()
        return s or None

    def _tmux_get_client_size(self):
        tmux = shutil.which("tmux")
        if not tmux:
            return None, None
        args = [tmux, "-S", str(self.TMUX_SOCK), "display-message", "-p"]
        if self._client_tty:
            args += ["-t", self._client_tty]
        args += ["-F", "#{client_width} #{client_height}"]
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, check=False)
        out = (r.stdout or "").strip().split()
        if len(out) == 2:
            return int(out[0]), int(out[1])
        return None, None

    def _tmux_get_pane_size(self):
        tmux = shutil.which("tmux")
        if not tmux:
            return None, None
        r = subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "display-message",
                            "-t", self.TMUX_SESSION, "-p", "-F", "#{pane_width} #{pane_height}"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        out = (r.stdout or "").strip().split()
        if len(out) == 2:
            return int(out[0]), int(out[1])
        return None, None

    def _tmux_refresh_client(self, cols: int, rows: int):
        tmux = shutil.which("tmux")
        if not tmux:
            return
        args = [tmux, "-S", str(self.TMUX_SOCK), "refresh-client", "-C", f"{cols},{rows}"]
        if self._client_tty:
            args[4:4] = ["-t", self._client_tty]
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    def _tmux_cd_to(self, path: Path):
        tmux = shutil.which("tmux")
        if not tmux:
            return
        q = shlex.quote(str(path))
        try:
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "send-keys", "C-u"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "send-keys", "C-k"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "send-keys", "-l", f"cd -- {q}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "send-keys", "Enter"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "send-keys", "C-l"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            self._last_tmux_cwd = Path(path).resolve()
        except Exception:
            pass

    def _tmux_quiet_bell(self):
        tmux = shutil.which("tmux")
        if not tmux:
            return
        for args in [
            ["set-option", "-g", "bell-action", "none"],
            ["set-option", "-g", "visual-activity", "off"],
            ["set-option", "-g", "monitor-activity", "off"],
        ]:
            subprocess.run([tmux, "-S", str(self.TMUX_SOCK), *args],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    # ---------- Shutdown ----------

    def _terminal_cleanup(self):
        p = self._xterm_proc
        if p:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                p.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:
                    pass
            self._xterm_proc = None

        tmux = shutil.which("tmux")
        if tmux:
            try:
                subprocess.run([tmux, "-S", str(self.TMUX_SOCK), "kill-server"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            except Exception:
                pass

        try:
            if self._x_dpy is not None:
                self._x_dpy.close()
        except Exception:
            pass
        self._x_dpy = None
        self._x_child = None

        try:
            if self.TMUX_DIR.exists():
                for entry in self.TMUX_DIR.iterdir():
                    try:
                        entry.unlink()
                    except Exception:
                        pass
                self.TMUX_DIR.rmdir()
        except Exception:
            pass

        self._xterm_started = False
        self._tmux_ready = False
        self._last_tmux_cwd = None
        self._pending_cd = None
        self._client_tty = None

    # ---------- UI helpers ----------

    def _show_missing_tools(self, xterm_path, tmux_path):
        for c in self._term_container.winfo_children():
            c.destroy()
        lines = []
        if not xterm_path:
            lines.append("• Missing dependency: xterm")
        if not tmux_path:
            lines.append("• Missing dependency: tmux")
        if not lines:
            lines.append("xterm/tmux OK.")
        tk.Label(self._term_container, text="\n".join(lines),
                 bg=self._TERM_BG, fg=self._TERM_FG, justify="left")\
          .pack(anchor="nw", padx=12, pady=12)

    def _show_error(self, text):
        for c in self._term_container.winfo_children():
            c.destroy()
        tk.Label(self._term_container, text=text, bg=self._TERM_BG, fg=self._TERM_FG, justify="left")\
          .pack(anchor="nw", padx=12, pady=12)
