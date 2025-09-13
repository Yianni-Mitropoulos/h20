import os
import shlex
import shutil
import signal
import subprocess
import uuid
import tkinter as tk
from pathlib import Path


class TerminalPanel:
    """
    Embeds xterm in the terminal pane and runs tmux inside it.

    Features
    --------
    • Fresh tmux per app run (unique socket) -> no session persistence
    • Visual bell + tmux bell disabled -> no beeps
    • CWD sync both ways:
        - Poll tmux #{pane_current_path}; if changed, call set_cwd(..., origin="terminal")
        - When app set_cwd(..., origin="app"), send a clean, hidden `cd` to tmux
    • Clean shutdown via a private hook _terminal_cleanup() added to self._cleanup_hooks
    """

    POLL_MS = 800  # ms between tmux cwd polls

    def init_terminal_panel(self):
        palette = getattr(self, "_palette", {})
        self._TERM_BG = palette.get("BG_CANVAS", "#0b1220")
        self._TERM_FG = palette.get("FG_TEXT",   "#e5e7eb")

        # Unique tmux namespace per run to avoid persistence across launches
        self.TMUX_SOCKET  = f"zeropad-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.TMUX_SESSION = "zeropad"

        # Terminal frame (the pane main.py toggles)
        self.terminal = tk.Frame(self.vpaned, bg=self._TERM_BG)

        # Container frame that will host xterm via -into <XID>
        self._term_container = tk.Frame(self.terminal, bg=self._TERM_BG, highlightthickness=0, bd=0)
        self._term_container.pack(fill="both", expand=True)

        # Process/state
        self._xterm_proc: subprocess.Popen | None = None
        self._xterm_started = False
        self._tmux_ready = False
        self._last_tmux_cwd: Path | None = None
        self._pending_cd: Path | None = None  # queued cd if tmux not ready yet

        # Spawn xterm/tmux once we have a window id; then start polling
        self.after(50, self._maybe_spawn_xterm)

        # Register cleanup hook (private name to avoid Tk attribute lookup confusion)
        if not hasattr(self, "_cleanup_hooks"):
            self._cleanup_hooks = []
        self._cleanup_hooks.append(self._terminal_cleanup)

    # ---------- lifecycle ----------

    def _maybe_spawn_xterm(self):
        """Spawn xterm into the container and start a fresh tmux session."""
        if self._xterm_started:
            self._schedule_poll()
            return

        if not self._term_container.winfo_ismapped():
            self.after(50, self._maybe_spawn_xterm)
            return

        xterm_path = shutil.which("xterm")
        tmux_path  = shutil.which("tmux")
        if not xterm_path or not tmux_path:
            self._show_missing_tools(xterm_path, tmux_path)
            return

        # Container X11 window id
        self._term_container.update_idletasks()
        wid = self._term_container.winfo_id()

        bg = self._TERM_BG
        fg = self._TERM_FG

        # Fresh session (no -A) on our unique socket
        tmux_cmd = [
            tmux_path, "-L", self.TMUX_SOCKET,
            "new-session", "-s", self.TMUX_SESSION
        ]

        # xterm embedded into our frame; visual bell and no urgency on bell
        cmd = [
            xterm_path,
            "-into", str(wid),
            "-fa", "Monospace",
            "-fs", "11",
            "-bg", bg,
            "-fg", fg,
            "+sb",           # no scrollbar
            "-bc",           # brighter bold
            "-cr", fg,       # cursor color
            "-maximized",
            "-vb",                               # visual bell only (no audio)
            "-xrm", "XTerm.vt100.bellIsUrgent: false",
            "-e", *tmux_cmd,
        ]

        try:
            self._xterm_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid  # separate process group for clean kill
            )
            self._xterm_started = True
        except Exception as e:
            self._show_error(f"Failed to start xterm: {e}")
            return

        # Give tmux a moment, then check readiness and prime any pending cd
        self.after(600, self._mark_tmux_ready_and_prime)

    def _mark_tmux_ready_and_prime(self):
        self._tmux_ready = self._tmux_has_session()
        if self._tmux_ready:
            self._tmux_quiet_bell()  # keep bells silent inside tmux
            if self._pending_cd:
                self._tmux_cd_to(self._pending_cd)
                self._pending_cd = None
        self._schedule_poll()

    def _schedule_poll(self):
        self.after(self.POLL_MS, self._poll_tmux_cwd)

    def _poll_tmux_cwd(self):
        """Poll tmux for the pane cwd and update the app if terminal cd'ed."""
        try:
            if not self._tmux_ready:
                self._tmux_ready = self._tmux_has_session()

            if self._tmux_ready:
                pane_cwd = self._tmux_get_cwd()
                if pane_cwd:
                    p = Path(pane_cwd).resolve()
                    if self._last_tmux_cwd is None or p != self._last_tmux_cwd:
                        self._last_tmux_cwd = p
                        if getattr(self, "cwd", None) is None or p != Path(self.cwd).resolve():
                            # Avoid loops: origin='terminal' tells app not to push back to tmux
                            try:
                                self.set_cwd(p, origin="terminal")
                            except TypeError:
                                self.set_cwd(p)
        finally:
            self._schedule_poll()

    # ---------- public API used by main ----------

    def terminal_set_cwd(self, path: Path | str):
        """
        Called by main when the app changes cwd (origin='app').
        If tmux isn't ready yet, we queue it.
        """
        target = Path(path).resolve()
        if not self._tmux_ready:
            self._pending_cd = target
            return
        self._tmux_cd_to(target)

    # ---------- tmux helpers ----------

    def _tmux_has_session(self) -> bool:
        tmux = shutil.which("tmux")
        if not tmux:
            return False
        try:
            r = subprocess.run(
                [tmux, "-L", self.TMUX_SOCKET, "has-session", "-t", self.TMUX_SESSION],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
            return r.returncode == 0
        except Exception:
            return False

    def _tmux_get_cwd(self) -> str | None:
        """Read the current pane path as seen by our session."""
        tmux = shutil.which("tmux")
        if not tmux:
            return None
        try:
            r = subprocess.run(
                [tmux, "-L", self.TMUX_SOCKET, "display-message",
                 "-t", self.TMUX_SESSION, "-p", "-F", "#{pane_current_path}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False
            )
            s = (r.stdout or "").strip()
            return s or None
        except Exception:
            return None

    def _tmux_cd_to(self, path: Path):
        """
        Clear input with readline (no beeps), cd, then clear screen:
        - Ctrl-U + Ctrl-K clears the command line without backspaces
        - Send literal 'cd -- <path>' then Enter
        - Ctrl-L to redraw a clean prompt at the new cwd
        """
        tmux = shutil.which("tmux")
        if not tmux:
            return
        quoted = shlex.quote(str(path))

        try:
            # 1) Clear any partially typed input in a bell-free way
            subprocess.run([tmux, "-L", self.TMUX_SOCKET, "send-keys", "C-u"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([tmux, "-L", self.TMUX_SOCKET, "send-keys", "C-k"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            # 2) Type the cd command literally and execute it
            line = f"cd -- {quoted}"
            subprocess.run([tmux, "-L", self.TMUX_SOCKET, "send-keys", "-l", line],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([tmux, "-L", self.TMUX_SOCKET, "send-keys", "Enter"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            # 3) Clear screen for a crisp prompt at the new location
            subprocess.run([tmux, "-L", self.TMUX_SOCKET, "send-keys", "C-l"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            self._last_tmux_cwd = path.resolve()
        except Exception:
            pass

    def _tmux_quiet_bell(self):
        """Tell this tmux server/session to ignore bells and activity beeps."""
        tmux = shutil.which("tmux")
        if not tmux:
            return
        for args in [
            ["set-option", "-g", "bell-action", "none"],
            ["set-option", "-g", "visual-activity", "off"],
            ["set-option", "-g", "monitor-activity", "off"],
        ]:
            subprocess.run([tmux, "-L", self.TMUX_SOCKET, *args],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    # ---------- shutdown ----------

    def _terminal_cleanup(self):
        """Terminate embedded xterm and kill the tmux server for this run."""
        # Kill xterm process group
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

        # Kill tmux server tied to our unique socket
        tmux = shutil.which("tmux")
        if tmux:
            try:
                subprocess.run([tmux, "-L", self.TMUX_SOCKET, "kill-server"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            except Exception:
                pass

        self._xterm_started = False
        self._tmux_ready = False
        self._last_tmux_cwd = None
        self._pending_cd = None

    # ---------- UI helpers ----------

    def _show_missing_tools(self, xterm_path, tmux_path):
        for child in self._term_container.winfo_children():
            child.destroy()
        lines = []
        if not xterm_path:
            lines.append("• Missing dependency: xterm")
        if not tmux_path:
            lines.append("• Missing dependency: tmux")
        if not lines:
            lines.append("xterm/tmux OK.")
        else:
            lines += ["", "Install on Debian:", "  sudo apt install xterm tmux"]
        tk.Label(self._term_container, text="\n".join(lines),
                 bg=self._TERM_BG, fg=self._TERM_FG, justify="left")\
          .pack(anchor="nw", padx=12, pady=12)

    def _show_error(self, text):
        for child in self._term_container.winfo_children():
            child.destroy()
        tk.Label(self._term_container, text=text, bg=self._TERM_BG, fg=self._TERM_FG, justify="left")\
          .pack(anchor="nw", padx=12, pady=12)
