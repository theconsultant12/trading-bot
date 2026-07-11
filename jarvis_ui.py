"""
Live dashboard for interactive.py ("Jarvis").

Runs as an independent process (spawned by interactive.py) and never touches
its internals. Everything shown here is reconstructed by watching the same
files/shared memory interactive.py already writes:
  - /tmp/<user>trading-bot-process.pid      -> bot status
  - logs/interactive-logs/<date>controller-logs.log -> voice + activity feed
  - stocks-to-trade.csv / <date>-traded.csv -> stock universe / traded today
  - shared_memory "alpaca_prices"           -> live price ticks
"""
import os
import re
import glob
import json
import time
import math
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime
from multiprocessing import shared_memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs", "interactive-logs")
STOCKS_FILE = os.path.join(BASE_DIR, "stocks-to-trade.csv")
SHM_NAME = "alpaca_prices"
SHM_SIZE = 1024
PARENT_PID = os.getppid()

BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
TEXT = "#c9d1d9"
DIM = "#6e7681"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d29922"
CYAN = "#58a6ff"
MONO = ("Menlo", 11)
MONO_BOLD = ("Menlo", 11, "bold")


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def is_process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class LogTailer:
    def __init__(self):
        self.path = None
        self.pos = 0

    def _current_path(self):
        date = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(LOG_DIR, f"{date}controller-logs.log")

    def poll(self):
        path = self._current_path()
        if path != self.path:
            self.path = path
            self.pos = os.path.getsize(path) if os.path.exists(path) else 0
        if not os.path.exists(path):
            return []
        with open(path, "r", errors="ignore") as f:
            f.seek(self.pos)
            new = f.read()
            self.pos = f.tell()
        return new.splitlines() if new else []


class HeaderBar(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=PANEL, height=64)
        self.pack_propagate(False)
        self.dot = tk.Canvas(self, width=24, height=24, bg=PANEL, highlightthickness=0)
        self.dot.pack(side="left", padx=(16, 8), pady=20)
        title = tk.Label(self, text="JARVIS", font=("Menlo", 18, "bold"), fg=TEXT, bg=PANEL)
        title.pack(side="left")
        self.status_label = tk.Label(self, text="starting…", font=MONO, fg=DIM, bg=PANEL)
        self.status_label.pack(side="left", padx=16)
        self.clock = tk.Label(self, font=MONO, fg=DIM, bg=PANEL)
        self.clock.pack(side="right", padx=16)

        self._phase = 0.0
        self._state = "idle"
        self._heard_until = 0
        self._tick()

    def set_listening(self):
        self._state = "listen"
        self.status_label.config(text="LISTENING…", fg=GREEN)

    def set_heard(self, text):
        self._state = "heard"
        self._heard_until = time.time() + 3
        shown = text.strip() or "(unrecognized)"
        self.status_label.config(text=f'HEARD: "{shown}"', fg=CYAN)

    def set_idle(self, text):
        self._state = "idle"
        self.status_label.config(text=text, fg=DIM)

    def _tick(self):
        if self._state == "heard" and time.time() > self._heard_until:
            self._state = "listen"
            self.status_label.config(text="LISTENING…", fg=GREEN)

        self.dot.delete("all")
        color = {"listen": GREEN, "heard": CYAN, "idle": DIM}[self._state]
        if self._state == "idle":
            r = 6
        else:
            self._phase += 0.12
            r = 5 + 3 * (0.5 + 0.5 * math.sin(self._phase))
        cx, cy = 12, 12
        self.dot.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")

        self.clock.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.after(60, self._tick)


class BotStatusPanel(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(self, text="TRADING BOTS", font=MONO_BOLD, fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        self.rows_frame = tk.Frame(self, bg=PANEL)
        self.rows_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.rows = {}
        self._phase = 0.0
        self._animate()
        self.poll()

    def poll(self):
        pattern = os.path.join("/tmp", "*trading-bot-process.pid")
        found = {}
        for path in glob.glob(pattern):
            m = re.match(r"^([A-Za-z0-9]+)trading-bot-process\.pid$", os.path.basename(path))
            if not m:
                continue
            user = m.group(1)
            try:
                with open(path) as f:
                    pid = int(f.read().strip())
                running = is_process_alive(pid)
            except (ValueError, OSError):
                running = False
            found[user] = running

        for user in list(self.rows.keys()):
            if user not in found:
                self.rows[user]["frame"].destroy()
                del self.rows[user]

        for user in sorted(found.keys()):
            running = found[user]
            if user not in self.rows:
                row = tk.Frame(self.rows_frame, bg=PANEL)
                row.pack(fill="x", pady=2)
                canvas = tk.Canvas(row, width=16, height=16, bg=PANEL, highlightthickness=0)
                canvas.pack(side="left", padx=(0, 8))
                label = tk.Label(row, text=user, font=MONO, fg=TEXT, bg=PANEL, width=8, anchor="w")
                label.pack(side="left")
                status = tk.Label(row, text="", font=MONO, bg=PANEL, anchor="w")
                status.pack(side="left")
                self.rows[user] = {"frame": row, "canvas": canvas, "status": status}
            self.rows[user]["status"].config(
                text="RUNNING" if running else "STOPPED", fg=GREEN if running else DIM
            )
            self.rows[user]["running"] = running

        if not found:
            if "_empty" not in self.rows:
                lbl = tk.Label(self.rows_frame, text="no bots running", font=MONO, fg=DIM, bg=PANEL)
                lbl.pack(anchor="w")
                self.rows["_empty"] = {"frame": lbl, "running": False}
        elif "_empty" in self.rows:
            self.rows["_empty"]["frame"].destroy()
            del self.rows["_empty"]

        self.after(2000, self.poll)

    def _animate(self):
        self._phase += 0.15
        for user, row in self.rows.items():
            if user == "_empty" or "canvas" not in row:
                continue
            canvas = row["canvas"]
            canvas.delete("all")
            if row.get("running"):
                r = 4 + 2 * (0.5 + 0.5 * math.sin(self._phase))
                color = GREEN
            else:
                r = 4
                color = "#30363d"
            canvas.create_oval(8 - r, 8 - r, 8 + r, 8 + r, fill=color, outline="")
        self.after(80, self._animate)


class StocksPanel(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(self, text="STOCK UNIVERSE", font=MONO_BOLD, fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        tk.Label(self, text="traded today", font=MONO, fg=GREEN, bg=PANEL).pack(anchor="w", padx=12)
        self.traded_wrap = tk.Frame(self, bg=PANEL)
        self.traded_wrap.pack(fill="x", padx=12, pady=(2, 8))
        tk.Label(self, text="pending", font=MONO, fg=YELLOW, bg=PANEL).pack(anchor="w", padx=12)
        self.pending_wrap = tk.Frame(self, bg=PANEL)
        self.pending_wrap.pack(fill="x", padx=12, pady=(2, 10))
        self.poll()

    @staticmethod
    def _read_csv(path):
        if not os.path.exists(path):
            return []
        with open(path) as f:
            content = f.read().strip()
        return [s.strip().upper() for s in content.split(",") if s.strip()]

    def _render_chips(self, wrap, symbols, color):
        for child in wrap.winfo_children():
            child.destroy()
        if not symbols:
            tk.Label(wrap, text="(none)", font=MONO, fg=DIM, bg=PANEL).pack(anchor="w")
            return
        line = tk.Frame(wrap, bg=PANEL)
        line.pack(anchor="w", fill="x")
        count = 0
        for sym in symbols:
            if count and count % 6 == 0:
                line = tk.Frame(wrap, bg=PANEL)
                line.pack(anchor="w", fill="x")
            chip = tk.Label(
                line, text=f" {sym} ", font=MONO, fg="#0d1117", bg=color, padx=2
            )
            chip.pack(side="left", padx=2, pady=2)
            count += 1

    def poll(self):
        date = datetime.now().strftime("%Y-%m-%d")
        universe = self._read_csv(STOCKS_FILE)
        traded = set(self._read_csv(os.path.join(BASE_DIR, f"{date}-traded.csv")))
        pending = [s for s in universe if s not in traded]
        traded_list = [s for s in universe if s in traded]

        self._render_chips(self.traded_wrap, traded_list, GREEN)
        self._render_chips(self.pending_wrap, pending, YELLOW)
        self.after(5000, self.poll)


class PriceStreamPanel(tk.Frame):
    FLASH_MS = 900

    def __init__(self, master):
        super().__init__(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(self, text="LIVE PRICE STREAM", font=MONO_BOLD, fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        self.status = tk.Label(self, text="attaching to stream…", font=MONO, fg=DIM, bg=PANEL)
        self.status.pack(anchor="w", padx=12)
        self.rows_frame = tk.Frame(self, bg=PANEL)
        self.rows_frame.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.rows = {}
        self.shm = None
        self.last_prices = {}
        self.poll()
        self._animate()

    def _attach(self):
        try:
            self.shm = shared_memory.SharedMemory(name=SHM_NAME)
            self.status.config(text="connected", fg=GREEN)
        except FileNotFoundError:
            self.shm = None

    def _read(self):
        if self.shm is None:
            self._attach()
            return {}
        try:
            raw = bytes(self.shm.buf[:SHM_SIZE]).decode(errors="ignore")
            last_brace = raw.rfind("}")
            if last_brace == -1:
                return {}
            return json.loads(raw[: last_brace + 1])
        except Exception:
            return {}

    def poll(self):
        data = self._read()
        for symbol, price in sorted(data.items()):
            prev = self.last_prices.get(symbol)
            if symbol not in self.rows:
                row = tk.Frame(self.rows_frame, bg=PANEL)
                row.pack(fill="x", pady=1)
                sym_label = tk.Label(row, text=symbol, font=MONO, fg=TEXT, bg=PANEL, width=8, anchor="w")
                sym_label.pack(side="left")
                price_label = tk.Label(row, text="", font=MONO, fg=TEXT, bg=PANEL, anchor="w")
                price_label.pack(side="left")
                self.rows[symbol] = {"row": row, "price_label": price_label, "flash_until": 0, "flash_color": PANEL}

            r = self.rows[symbol]
            r["price_label"].config(text=f"${price:.2f}")
            if prev is not None and price != prev:
                r["flash_color"] = GREEN if price > prev else RED
                r["flash_until"] = time.time() + self.FLASH_MS / 1000
            self.last_prices[symbol] = price

        if data:
            self.status.config(text=f"connected · {len(data)} symbols", fg=GREEN)
        elif self.shm is None:
            self.status.config(text="waiting for stream to start…", fg=DIM)

        self.after(1000, self.poll)

    def _animate(self):
        now = time.time()
        for r in self.rows.values():
            remaining = r["flash_until"] - now
            if remaining > 0:
                t = remaining / (self.FLASH_MS / 1000)
                bg = lerp_color(PANEL, r["flash_color"], t)
            else:
                bg = PANEL
            r["row"].config(bg=bg)
            r["price_label"].config(bg=bg)
        self.after(50, self._animate)


class ActivityConsole(tk.Frame):
    MAX_LINES = 400
    LEVEL_COLORS = {"INFO": TEXT, "WARNING": YELLOW, "ERROR": RED, "DEBUG": DIM}

    def __init__(self, master, on_event=None):
        super().__init__(master, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(self, text="ACTIVITY", font=MONO_BOLD, fg=TEXT, bg=PANEL).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        self.text = tk.Text(
            self, bg="#010409", fg=TEXT, font=MONO, insertbackground=TEXT,
            relief="flat", wrap="word", state="disabled", padx=8, pady=6,
        )
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for level, color in self.LEVEL_COLORS.items():
            self.text.tag_config(level, foreground=color)
        self.text.tag_config("VOICE", foreground=CYAN)

        self.tailer = LogTailer()
        self.on_event = on_event
        self.poll()

    def _append(self, line):
        m = re.match(r"^(\S+ \S+) - (\w+) - (.*)$", line)
        if m:
            _, level, message = m.groups()
        else:
            level, message = "INFO", line

        tag = "VOICE" if "Recognized command" in message else self.LEVEL_COLORS and level
        self.text.config(state="normal")
        self.text.insert("end", message + "\n", tag if tag in self.LEVEL_COLORS or tag == "VOICE" else "INFO")
        line_count = int(self.text.index("end-1c").split(".")[0])
        if line_count > self.MAX_LINES:
            self.text.delete("1.0", f"{line_count - self.MAX_LINES}.0")
        self.text.see("end")
        self.text.config(state="disabled")

        if self.on_event:
            self.on_event(message)

    def poll(self):
        for line in self.tailer.poll():
            if line.strip():
                self._append(line)
        self.after(700, self.poll)


class DashboardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jarvis Trading Dashboard")
        self.geometry("1180x760")
        self.configure(bg=BG)
        try:
            self.tk.call("tk", "scaling", 1.2)
        except tk.TclError:
            pass

        self.header = HeaderBar(self)
        self.header.pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        top = tk.Frame(body, bg=BG)
        top.pack(fill="both", expand=True)

        self.bots = BotStatusPanel(top)
        self.bots.pack(side="left", fill="both", padx=(0, 8), pady=(0, 8))

        self.stocks = StocksPanel(top)
        self.stocks.pack(side="left", fill="both", expand=True, padx=8, pady=(0, 8))

        self.prices = PriceStreamPanel(top)
        self.prices.pack(side="left", fill="both", padx=(8, 0), pady=(0, 8))

        self.console = ActivityConsole(body, on_event=self._on_log_event)
        self.console.pack(fill="both", expand=True)

        self.header.set_idle("waiting for interactive.py…")
        self._watch_parent()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.prices.shm is not None:
            self.prices.shm.close()
        self.destroy()

    def _on_log_event(self, message):
        if "Listening for voice commands" in message:
            self.header.set_listening()
        else:
            m = re.search(r"Recognized command:\s*(.*)", message)
            if m:
                self.header.set_heard(m.group(1))

    def _watch_parent(self):
        if PARENT_PID > 1 and not is_process_alive(PARENT_PID):
            self._on_close()
            return
        self.after(5000, self._watch_parent)


if __name__ == "__main__":
    DashboardApp().mainloop()
