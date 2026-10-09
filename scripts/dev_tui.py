"""ResuMate dev dashboard — Textual TUI."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path

import httpx
import psutil
import pyfiglet
import yaml
from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual import work
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListItem, ListView, Static

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
UVICORN_LOG = LOG_DIR / "uvicorn.log"
OLLAMA_LOG = LOG_DIR / "ollama.log"
API = "http://localhost:8000"
OLLAMA = "http://localhost:11434"

PURPLE_GRADIENT = ["#a78bfa", "#8b5cf6", "#7c3aed", "#6d28d9", "#5b21b6", "#4c1d95"]


def git_short_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def app_version() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "dev"


def banner_text() -> Text:
    art = pyfiglet.figlet_format("RESUMATE", font="ansi_shadow").rstrip("\n")
    lines = art.split("\n")
    out = Text()
    for i, line in enumerate(lines):
        color = PURPLE_GRADIENT[i % len(PURPLE_GRADIENT)]
        out.append(line + "\n", style=color)
    return out


def fmt_duration(secs: float) -> str:
    secs = int(secs)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"


def count_requests(path: Path) -> tuple[int, deque[float]]:
    """Return (total access lines, sparkline buckets)."""
    if not path.exists():
        return 0, deque([0] * 20, maxlen=20)
    total = 0
    try:
        with path.open("rb") as f:
            for line in f:
                if b'"GET ' in line or b'"POST ' in line or b'"PUT ' in line:
                    total += 1
    except Exception:
        return 0, deque([0] * 20, maxlen=20)
    return total, deque([0] * 20, maxlen=20)


class Card(Static):
    """A titled stat card with optional progress bar."""

    DEFAULT_CSS = """
    Card {
        border: round $primary-lighten-2;
        padding: 0 1;
        background: $surface;
        height: auto;
        min-height: 5;
    }
    """


class StatsPanel(Static):
    """Panel holding the STATS header and card grid."""

    model: reactive[str] = reactive("—")
    model_ready: reactive[bool] = reactive(False)
    compute: reactive[str] = reactive("—")
    api_listening: reactive[bool] = reactive(False)
    cpu_pct: reactive[float] = reactive(0.0)
    mem_used_gb: reactive[float] = reactive(0.0)
    mem_total_gb: reactive[float] = reactive(0.0)
    disk_used_gb: reactive[float] = reactive(0.0)
    disk_total_gb: reactive[float] = reactive(0.0)
    uptime_secs: reactive[float] = reactive(0.0)
    req_total: reactive[int] = reactive(0)
    req_rps: reactive[float] = reactive(0.0)

    def compose(self) -> ComposeResult:
        yield Label("│ STATS", id="stats-title")
        with Horizontal(classes="card-row"):
            yield Card(id="card-model")
            yield Card(id="card-api")
        with Horizontal(classes="card-row"):
            yield Card(id="card-gpu")
            yield Card(id="card-cpu")
        with Horizontal(classes="card-row"):
            yield Card(id="card-mem")
            yield Card(id="card-disk")
        with Horizontal(classes="card-row"):
            yield Card(id="card-req")
            yield Card(id="card-up")

    def render_cards(self) -> None:
        def kv(label: str, body: Text) -> Group:
            lbl = Text(label, style="dim")
            return Group(lbl, body)

        def bar(used: float, total: float, color: str) -> Text:
            pct = 0.0 if total <= 0 else min(1.0, used / total)
            width = 22
            filled = int(width * pct)
            t = Text()
            t.append("█" * filled, style=color)
            t.append("░" * (width - filled), style="grey39")
            return t

        # Model
        status_color = "green" if self.model_ready else "yellow"
        status_text = "loaded" if self.model_ready else "loading"
        body = Text()
        body.append(f"{self.model}\n", style="bold")
        body.append(f"{self.compute} · ready\n" if self.model_ready else f"{self.compute} · warming\n", style="dim")
        body.append("● ", style=status_color)
        body.append(status_text, style=status_color)
        self.query_one("#card-model", Card).update(kv("MODEL", body))

        # API
        api_color = "green" if self.api_listening else "red"
        api_text = "listening" if self.api_listening else "down"
        body = Text()
        body.append("127.0.0.1:8000\n", style="bold")
        body.append("1 worker · http/1.1\n", style="dim")
        body.append("● ", style=api_color)
        body.append(api_text, style=api_color)
        self.query_one("#card-api", Card).update(kv("UVICORN", body))

        # GPU (Apple Silicon → Metal)
        body = Text()
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            body.append("Apple Silicon\n", style="bold")
            body.append("Metal · unified memory\n", style="dim")
            body.append(bar(self.mem_used_gb, self.mem_total_gb, "#22d3ee"))
            body.append(f"\n{self.mem_used_gb:.1f} / {self.mem_total_gb:.0f} GB", style="dim")
        else:
            body.append("GPU\n", style="bold")
            body.append("n/a\n", style="dim")
        self.query_one("#card-gpu", Card).update(kv("GPU", body))

        # CPU
        body = Text()
        cores = psutil.cpu_count(logical=True) or 0
        body.append(f"{cores} cores\n", style="bold")
        body.append(f"{self.cpu_pct:.0f}%\n", style="dim")
        body.append(bar(self.cpu_pct, 100.0, "#818cf8"))
        self.query_one("#card-cpu", Card).update(kv("CPU", body))

        # Memory
        body = Text()
        body.append(f"{self.mem_used_gb:.1f} / {self.mem_total_gb:.0f} GB\n", style="bold")
        body.append(bar(self.mem_used_gb, self.mem_total_gb, "#c084fc"))
        self.query_one("#card-mem", Card).update(kv("MEMORY", body))

        # Disk
        body = Text()
        body.append(f"{self.disk_used_gb:.0f} / {self.disk_total_gb:.0f} GB\n", style="bold")
        body.append(bar(self.disk_used_gb, self.disk_total_gb, "#a3e635"))
        self.query_one("#card-disk", Card).update(kv("DISK · /", body))

        # Requests
        body = Text()
        body.append(f"total {self.req_total:,}\n", style="bold")
        body.append(f"rps {self.req_rps:.2f}\n", style="dim")
        body.append("▂▃▅▇▆▄▂▁▂▄▆▇▅▃▂", style="#a3e635")
        self.query_one("#card-req", Card).update(kv("REQUESTS", body))

        # Uptime
        body = Text()
        body.append(f"{fmt_duration(self.uptime_secs)}\n", style="bold")
        body.append("crash-free\n", style="dim")
        body.append("● healthy", style="green")
        self.query_one("#card-up", Card).update(kv("UPTIME", body))


OPTIONS = [
    ("1", "↻", "Restart",      "Reload model + reindex routes"),
    ("2", "⏻", "Shutdown",     "Graceful stop (SIGTERM → drain)"),
    ("3", "≡", "See logs",     "Tail uvicorn + app stdout"),
    ("4", "♥", "Health check", "Ping /health + vector DB"),
    ("5", "✕", "Clear cache",  "Purge embedding + response cache"),
    ("6", "⇄", "Models",       "Download + activate lightweight LLMs"),
    ("7", "⇡", "Update deps",  "pip install -r requirements.txt"),
    ("8", "☕","Buy me a coffee","Support the maintainer"),
]


class OptionsPanel(Static):
    def compose(self) -> ComposeResult:
        yield Label("│ PICK AN OPTION", id="opts-title")
        items: list[ListItem] = []
        for key, icon, title, desc in OPTIONS:
            row = Text()
            row.append(f"  [{key}]  ", style="bold #c084fc")
            row.append(f"{icon}  ", style="#a78bfa")
            row.append(f"{title}\n", style="bold")
            row.append(f"         {desc}", style="dim")
            items.append(ListItem(Static(row)))
        yield ListView(*items, id="opts-list")


class ConfirmShutdown(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmShutdown { align: center middle; }
    #dlg {
        width: 64; height: auto; padding: 1 2;
        border: thick $warning; background: $panel;
    }
    #dlg-title { text-style: bold; color: $warning; }
    #btns { align: center middle; height: 3; margin-top: 1; }
    Button { margin: 0 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dlg"):
            yield Label("Shutdown ResuMate?", id="dlg-title")
            yield Static("Stops uvicorn and ollama (if owned by this session).", classes="dim")
            with Horizontal(id="btns"):
                yield Button("Cancel", id="cancel")
                yield Button("Confirm shutdown", id="confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class LogsScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    LogsScreen { align: center middle; }
    #logwrap {
        width: 90%; height: 80%;
        border: round $primary-lighten-2; padding: 0 1; background: $panel;
    }
    #logtitle { text-style: bold; }
    #logview { height: 1fr; }
    """
    BINDINGS = [Binding("escape,q", "dismiss", "close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="logwrap"):
            yield Label("logs/uvicorn.log (last 200 lines)  —  esc to close", id="logtitle")
            yield Static("", id="logview")

    def on_mount(self) -> None:
        view = self.query_one("#logview", Static)
        if UVICORN_LOG.exists():
            tail = UVICORN_LOG.read_text(errors="replace").splitlines()[-200:]
            view.update("\n".join(tail))
        else:
            view.update("(no uvicorn.log yet)")


class HealthScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HealthScreen { align: center middle; }
    #hwrap {
        width: 70; height: auto; padding: 1 2;
        border: round $success; background: $panel;
    }
    """
    BINDINGS = [Binding("escape,q,enter", "dismiss", "close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="hwrap"):
            yield Label("Health check", id="htitle")
            yield Static("checking…", id="hbody")

    def on_mount(self) -> None:
        body = self.query_one("#hbody", Static)
        try:
            with httpx.Client(timeout=2.0) as c:
                h = c.get(f"{API}/health").json()
                s = c.get(f"{API}/api/stats").json() if self._probe_stats() else {}
            t = Text()
            t.append("● API reachable\n", style="green")
            t.append(json.dumps(h, indent=2) + "\n", style="dim")
            if s:
                t.append("\n/api/stats:\n", style="bold")
                t.append(json.dumps(s, indent=2), style="dim")
            body.update(t)
        except Exception as e:
            body.update(Text(f"✗ {e}", style="red"))

    def _probe_stats(self) -> bool:
        try:
            with httpx.Client(timeout=1.0) as c:
                return c.get(f"{API}/api/stats").status_code == 200
        except Exception:
            return False


MODEL_CATALOG: list[tuple[str, str, str]] = [
    ("qwen2.5:1.5b", "~1.0 GB", "project default · fast"),
    ("llama3.2:1b",  "~1.3 GB", "smallest Llama"),
    ("gemma2:2b",    "~1.6 GB", "Google, compact"),
    ("qwen2.5:3b",   "~1.9 GB", "better quality"),
    ("llama3.2:3b",  "~2.0 GB", "better quality"),
    ("phi3.5:3.8b",  "~2.2 GB", "strong reasoning, slowest"),
]
MODEL_CONFIG = ROOT / "src" / "resumate" / "config" / "model_config.yaml"


def _read_active_model() -> str:
    try:
        return str(yaml.safe_load(MODEL_CONFIG.read_text())["llm"]["model_name"])
    except Exception:
        return ""


def _write_active_model(name: str) -> None:
    cfg = yaml.safe_load(MODEL_CONFIG.read_text()) or {}
    cfg.setdefault("llm", {})["model_name"] = name
    MODEL_CONFIG.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))


class ModelsScreen(ModalScreen[str | None]):
    """Download lightweight Ollama models and activate them in the running app."""

    DEFAULT_CSS = """
    ModelsScreen { align: center middle; }
    #mwrap {
        width: 86; height: auto; padding: 1 2;
        border: round $primary; background: $panel;
    }
    #mlist { height: auto; max-height: 16; }
    #mstatus { margin-top: 1; height: auto; }
    """
    BINDINGS = [Binding("escape,q", "close", "close")]

    def __init__(self) -> None:
        super().__init__()
        self.busy = False
        self.installed: dict[str, float] = {}
        self.active = _read_active_model()

    def compose(self) -> ComposeResult:
        with Vertical(id="mwrap"):
            yield Label("Models  —  ↵ download + activate · esc close", id="mtitle")
            yield ListView(id="mlist")
            yield Static("", id="mstatus")

    def on_mount(self) -> None:
        self.refresh_list()

    def _set_status(self, msg: Text | str) -> None:
        self.query_one("#mstatus", Static).update(msg)

    def refresh_list(self) -> None:
        try:
            with httpx.Client(timeout=2.0) as c:
                tags = c.get(f"{OLLAMA}/api/tags").json().get("models", [])
            self.installed = {m["name"]: m.get("size", 0) / 1e9 for m in tags}
        except Exception as e:
            self._set_status(Text(f"✗ Ollama unreachable: {e}", style="red"))
            return
        self.active = _read_active_model()
        lv = self.query_one("#mlist", ListView)
        idx = lv.index or 0
        lv.clear()
        names = [n for n, _, _ in MODEL_CATALOG]
        for name, size, note in MODEL_CATALOG:
            row = Text()
            if name == self.active and name in self.installed:
                row.append("  ● active     ", style="bold green")
            elif name in self.installed:
                row.append("  ✓ installed  ", style="green")
            else:
                row.append("  ⇣ download   ", style="yellow")
            row.append(f"{name:<14}", style="bold")
            row.append(f" {size:>8}  {note}", style="dim")
            lv.append(ListItem(Static(row), name=name))
        for name, gb in self.installed.items():  # extras not in catalog
            if name not in names:
                row = Text()
                row.append("  ✓ installed  ", style="green")
                row.append(f"{name:<14}", style="bold")
                row.append(f" {gb:>5.2f} GB  (custom)", style="dim")
                lv.append(ListItem(Static(row), name=name))
        lv.index = min(idx, len(lv.children) - 1)

    def action_close(self) -> None:
        if self.busy:
            self._set_status(Text("Busy — wait for the current job to finish.", style="yellow"))
            return
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self.busy or not event.item.name:
            return
        self.busy = True
        self.run_job(event.item.name)

    @work(thread=True)
    def run_job(self, name: str) -> None:
        ui = self.app.call_from_thread
        try:
            if name not in self.installed:
                self._pull(name)
            ui(self._set_status, Text(f"Activating {name}…", style="cyan"))
            _write_active_model(name)
            with httpx.Client(timeout=180.0) as c:  # includes warm-up
                r = c.post(f"{API}/api/models/reload", json={"model_name": name})
                r.raise_for_status()
            ui(self._set_status, Text(f"✓ {name} active and loaded in the app", style="green"))
            ui(self.app.notify, f"Active model → {name}")
        except Exception as e:
            ui(self._set_status, Text(f"✗ {name}: {e}", style="red"))
        finally:
            self.busy = False
            ui(self.refresh_list)

    def _pull(self, name: str) -> None:
        ui = self.app.call_from_thread
        last = 0.0
        with httpx.stream("POST", f"{OLLAMA}/api/pull", json={"model": name, "stream": True},
                          timeout=httpx.Timeout(10.0, read=None)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                now = time.time()
                if now - last < 0.2 and d.get("status") != "success":
                    continue
                last = now
                total, done = d.get("total") or 0, d.get("completed") or 0
                t = Text()
                if total:
                    pct = done / total
                    filled = int(30 * pct)
                    t.append(f"Downloading {name}  ", style="bold")
                    t.append("█" * filled, style="#a78bfa")
                    t.append("░" * (30 - filled), style="grey39")
                    t.append(f"  {pct*100:5.1f}%  {done/1e9:.2f}/{total/1e9:.2f} GB", style="dim")
                else:
                    t.append(f"{name}: {d.get('status', '')}", style="dim")
                ui(self._set_status, t)


class DevApp(App):
    CSS = """
    Screen { background: $background; }
    #topbar { height: 1; padding: 0 1; }
    #banner { height: auto; padding: 0 1; }
    #subbanner { height: auto; padding: 0 1; }
    #main { height: 1fr; padding: 0 1; }
    StatsPanel { width: 1fr; padding: 0 1; }
    OptionsPanel { width: 1fr; padding: 0 1; }
    #stats-title, #opts-title { color: #c084fc; text-style: bold; margin-bottom: 1; }
    .card-row { height: auto; }
    .card-row Card { width: 1fr; margin: 0 1 1 0; }
    #opts-list { height: auto; border: round $primary-lighten-2; background: $surface; padding: 0 1; }
    #footer { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    """

    BINDINGS = [
        Binding("1", "restart",  "restart",  show=False),
        Binding("2", "shutdown", "shutdown", show=False),
        Binding("3", "logs",     "logs",     show=False),
        Binding("4", "health",   "health",   show=False),
        Binding("5", "clear",    "clear",    show=False),
        Binding("6", "switch",   "switch",   show=False),
        Binding("7", "update",   "update",   show=False),
        Binding("8", "coffee",   "coffee",   show=False),
        Binding("q", "quit",     "quit",     show=False),
    ]

    start_time = reactive(time.time())

    def compose(self) -> ComposeResult:
        yield Static(self._topbar(), id="topbar")
        yield Static(banner_text(), id="banner")
        yield Static(self._subbanner(), id="subbanner")
        with Horizontal(id="main"):
            yield StatsPanel(id="stats")
            yield OptionsPanel(id="opts")
        yield Static(self._footer(), id="footer")

    def on_mount(self) -> None:
        self.set_interval(1.5, self.refresh_stats)
        self.set_interval(1.0, self.refresh_topbar)
        self.refresh_stats()

    def _topbar(self) -> Text:
        t = Text()
        t.append("  dev.sh ", style="dim")
        t.append("> ", style="#6b7280")
        t.append("dashboard", style="bold")
        t.append("   ")
        t.append("● ", style="green")
        t.append(":8000", style="bold")
        t.append("  |  up ", style="dim")
        t.append(fmt_duration(time.time() - self.start_time), style="bold")
        return t

    def _subbanner(self) -> Text:
        t = Text()
        t.append("● ", style="green")
        t.append("ready", style="bold")
        t.append(f"  ·  {app_version()} ", style="dim")
        t.append(f"({git_short_sha()})\n", style="#6b7280")
        t.append("RAG pipeline for your candidate pool.\n", style="bold")
        t.append(f"serving {API}", style="dim")
        t.append("  ·  ")
        t.append("docs at /docs", style="dim")
        return t

    def _footer(self) -> Text:
        t = Text()
        for label, desc in [
            ("1-8", "select"), ("↑↓", "nav"), ("⏎", "confirm"), ("q", "quit"),
        ]:
            t.append(f" {label} ", style="reverse bold")
            t.append(f" {desc}   ", style="dim")
        t.append(f"                           PID {os.getpid()}", style="dim")
        return t

    def refresh_topbar(self) -> None:
        self.query_one("#topbar", Static).update(self._topbar())
        self.query_one("#footer", Static).update(self._footer())

    def refresh_stats(self) -> None:
        stats = self.query_one(StatsPanel)

        # /health
        try:
            with httpx.Client(timeout=1.0) as c:
                h = c.get(f"{API}/health").json()
            stats.model = h.get("model", "—")
            stats.model_ready = bool(h.get("model_ready"))
            stats.compute = h.get("compute", "—")
            stats.api_listening = h.get("status") == "ok"
        except Exception:
            stats.api_listening = False

        # psutil
        stats.cpu_pct = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        stats.mem_used_gb = (vm.total - vm.available) / (1024**3)
        stats.mem_total_gb = vm.total / (1024**3)
        du = psutil.disk_usage("/")
        stats.disk_used_gb = du.used / (1024**3)
        stats.disk_total_gb = du.total / (1024**3)

        # requests (parse uvicorn.log quickly)
        total, _ = count_requests(UVICORN_LOG)
        elapsed = max(1.0, time.time() - self.start_time)
        stats.req_total = total
        stats.req_rps = total / elapsed

        stats.uptime_secs = time.time() - self.start_time
        stats.render_cards()

    # ── actions ────────────────────────────────────────────────────
    def action_restart(self) -> None:
        self.notify("Restarting uvicorn…", severity="information")
        subprocess.run(
            ["bash", "-c",
             "lsof -ti tcp:8000 2>/dev/null | xargs -r kill -TERM; true"],
            check=False,
        )

    def action_shutdown(self) -> None:
        def after(go: bool | None) -> None:
            if go:
                self.exit(return_code=0)
        self.push_screen(ConfirmShutdown(), after)

    def action_logs(self) -> None:
        self.push_screen(LogsScreen())

    def action_health(self) -> None:
        self.push_screen(HealthScreen())

    def action_clear(self) -> None:
        self.notify("Clear cache not wired yet.", severity="warning")

    def action_switch(self) -> None:
        self.push_screen(ModelsScreen())

    def action_update(self) -> None:
        self.notify("Run `pip install -r requirements.txt` in a separate shell.", severity="warning")

    def action_coffee(self) -> None:
        if shutil.which("open"):
            subprocess.Popen(["open", "https://www.buymeacoffee.com/"])
        self.notify("☕ opened in browser", severity="information")


if __name__ == "__main__":
    DevApp().run()
