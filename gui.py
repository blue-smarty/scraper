#!/usr/bin/env python3
"""
Tkinter GUI front-end for scraper.py.

Run with:
    python gui.py
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

import scraper as sc

# ---------------------------------------------------------------------------
# Logging handler that feeds into a thread-safe queue
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self._queue.put(self.format(record))


# ---------------------------------------------------------------------------
# Main GUI application
# ---------------------------------------------------------------------------

class ScraperApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Car Image Scraper")
        self.resizable(True, True)

        self._log_queue: queue.Queue = queue.Queue()
        self._scrape_thread: threading.Thread | None = None
        self._stop_event: threading.Event = threading.Event()

        # Configure a single queue handler attached once for the lifetime of the app
        self._queue_handler = _QueueHandler(self._log_queue)
        self._queue_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(self._queue_handler)

        self._build_ui()
        self._start_log_polling()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        padding = {"padx": 8, "pady": 4}

        # ── Settings frame ──────────────────────────────────────────────
        settings = ttk.LabelFrame(self, text="Settings")
        settings.pack(fill="x", padx=10, pady=(10, 0))

        # Search URL
        ttk.Label(settings, text="Search URL:").grid(
            row=0, column=0, sticky="w", **padding)
        self._search_url = tk.StringVar(value=sc.SEARCH_URL)
        ttk.Entry(settings, textvariable=self._search_url, width=36).grid(
            row=0, column=1, columnspan=2, sticky="ew", **padding)

        # Output directory
        ttk.Label(settings, text="Output directory:").grid(
            row=1, column=0, sticky="w", **padding)
        self._output_dir = tk.StringVar(value=sc.DEFAULT_OUTPUT_DIR)
        ttk.Entry(settings, textvariable=self._output_dir, width=36).grid(
            row=1, column=1, sticky="ew", **padding)
        ttk.Button(settings, text="Browse…", command=self._browse_output).grid(
            row=1, column=2, **padding)

        # Max cars
        ttk.Label(settings, text="Max cars:").grid(
            row=2, column=0, sticky="w", **padding)
        self._max_cars = tk.IntVar(value=sc.DEFAULT_MAX_CARS)
        ttk.Spinbox(settings, textvariable=self._max_cars,
                    from_=1, to=10_000, width=10).grid(
            row=2, column=1, sticky="w", **padding)

        # Delay
        ttk.Label(settings, text="Request delay (s):").grid(
            row=3, column=0, sticky="w", **padding)
        self._delay = tk.DoubleVar(value=sc.DEFAULT_DELAY)
        ttk.Spinbox(settings, textvariable=self._delay,
                    from_=0.0, to=30.0, increment=0.5, format="%.1f",
                    width=10).grid(row=3, column=1, sticky="w", **padding)

        # Car make
        ttk.Label(settings, text="Car make:").grid(
            row=4, column=0, sticky="w", **padding)
        self._make = tk.StringVar()
        ttk.Entry(settings, textvariable=self._make, width=20).grid(
            row=4, column=1, sticky="w", **padding)
        ttk.Label(settings, text="(e.g. Toyota, Ford — leave blank for all)",
                  foreground="grey").grid(row=4, column=2, sticky="w", **padding)

        # Min price
        ttk.Label(settings, text="Min price (AUD):").grid(
            row=5, column=0, sticky="w", **padding)
        self._min_price = tk.StringVar()
        ttk.Entry(settings, textvariable=self._min_price, width=14).grid(
            row=5, column=1, sticky="w", **padding)

        # Max price
        ttk.Label(settings, text="Max price (AUD):").grid(
            row=6, column=0, sticky="w", **padding)
        self._max_price = tk.StringVar()
        ttk.Entry(settings, textvariable=self._max_price, width=14).grid(
            row=6, column=1, sticky="w", **padding)

        # Deep-scrape checkbox
        self._deep_scrape = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings,
            text="Deep-scrape (visit each listing page for full-resolution images)",
            variable=self._deep_scrape,
        ).grid(row=7, column=0, columnspan=3, sticky="w", **padding)

        # Verbose checkbox
        self._verbose = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings, text="Verbose logging (DEBUG)", variable=self._verbose,
        ).grid(row=8, column=0, columnspan=3, sticky="w", **padding)

        settings.columnconfigure(1, weight=1)

        # ── Controls ────────────────────────────────────────────────────
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=10, pady=6)

        self._start_btn = ttk.Button(
            controls, text="▶  Start Scraping", command=self._on_start)
        self._start_btn.pack(side="left", padx=(0, 6))

        self._stop_btn = ttk.Button(
            controls, text="⏹  Stop", command=self._on_stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 6))

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(controls, textvariable=self._status_var,
                  foreground="grey").pack(side="left", padx=12)

        # ── Log output ──────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._log_widget = scrolledtext.ScrolledText(
            log_frame, state="disabled", height=18, wrap="word",
            font=("Courier", 9))
        self._log_widget.pack(fill="both", expand=True, padx=4, pady=4)

        # Colour tags for log levels
        self._log_widget.tag_config("ERROR",   foreground="#cc0000")
        self._log_widget.tag_config("WARNING", foreground="#cc6600")
        self._log_widget.tag_config("DEBUG",   foreground="#888888")

    # ------------------------------------------------------------------
    # Button helpers
    # ------------------------------------------------------------------

    def _browse_output(self) -> None:
        directory = filedialog.askdirectory(title="Select output directory")
        if directory:
            self._output_dir.set(directory)

    def _on_start(self) -> None:
        if self._scrape_thread and self._scrape_thread.is_alive():
            return

        # Validate numeric fields
        try:
            min_price = int(self._min_price.get()) if self._min_price.get().strip() else None
            max_price = int(self._max_price.get()) if self._max_price.get().strip() else None
        except ValueError:
            self._append_log("ERROR: Min/Max price must be integers.", "ERROR")
            return

        # Configure logging level for this run
        level = logging.DEBUG if self._verbose.get() else logging.INFO
        logging.getLogger().setLevel(level)
        self._queue_handler.setLevel(level)

        # Capture all parameters now (before thread starts)
        kwargs = dict(
            search_url=self._search_url.get().strip() or None,
            output_dir=self._output_dir.get(),
            max_cars=self._max_cars.get(),
            delay=self._delay.get(),
            make=self._make.get().strip() or None,
            min_price=min_price,
            max_price=max_price,
            deep_scrape=self._deep_scrape.get(),
        )

        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._status_var.set("Running…")

        self._stop_event = threading.Event()
        kwargs["stop_event"] = self._stop_event

        self._scrape_thread = threading.Thread(
            target=self._run_scraper, kwargs=kwargs, daemon=True)
        self._scrape_thread.start()

    def _on_stop(self) -> None:
        self._stop_event.set()
        self._stop_btn.config(state="disabled")
        self._status_var.set("Stopping…")

    # ------------------------------------------------------------------
    # Scraper thread
    # ------------------------------------------------------------------

    def _run_scraper(self, **kwargs) -> None:
        stop_event = kwargs.get("stop_event")
        try:
            sc.scrape_cars(**kwargs)
            if stop_event and stop_event.is_set():
                self._log_queue.put("__STOPPED__")
            else:
                self._log_queue.put("__DONE__")
        except Exception as exc:
            logging.getLogger(__name__).error("Scraper error: %s", exc, exc_info=True)
            self._log_queue.put("__ERROR__")

    # ------------------------------------------------------------------
    # Log polling (runs in the main thread via after())
    # ------------------------------------------------------------------

    def _start_log_polling(self) -> None:
        self._poll_log()

    def _poll_log(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if msg == "__DONE__":
                    self._status_var.set("Done ✓")
                    self._start_btn.config(state="normal")
                    self._stop_btn.config(state="disabled")
                elif msg == "__STOPPED__":
                    self._status_var.set("Stopped ◼")
                    self._start_btn.config(state="normal")
                    self._stop_btn.config(state="disabled")
                elif msg == "__ERROR__":
                    self._status_var.set("Error ✗")
                    self._start_btn.config(state="normal")
                    self._stop_btn.config(state="disabled")
                else:
                    tag = "ERROR" if "[ERROR]" in msg else (
                          "WARNING" if "[WARNING]" in msg else (
                          "DEBUG" if "[DEBUG]" in msg else ""))
                    self._append_log(msg, tag)
        except queue.Empty:
            pass
        finally:
            self.after(200, self._poll_log)

    # ------------------------------------------------------------------
    # Log widget helper
    # ------------------------------------------------------------------

    def _append_log(self, text: str, tag: str = "") -> None:
        self._log_widget.config(state="normal")
        self._log_widget.insert("end", text + "\n", tag)
        self._log_widget.see("end")
        self._log_widget.config(state="disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = ScraperApp()
    app.mainloop()


if __name__ == "__main__":
    main()
