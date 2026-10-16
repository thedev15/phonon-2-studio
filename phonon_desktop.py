from __future__ import annotations

import queue
import json
import math
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import wave
from array import array
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tempfile import NamedTemporaryFile

from ontology import SpeechOntology

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".phonon-venv" / "Scripts" / "python.exe"
PHONON = ROOT / ".phonon-venv" / "Scripts" / "phonon.exe"
if not PHONON.exists():
    PHONON = "phonon"


class PhononDesktop(tk.Tk):
    AUDIO_QUEUE_SIZE = 32
    AUDIO_PACKET_BYTES = 3200
    LIVE_READY_TIMEOUT = 5.0
    MODEL_LATCH_TIMEOUT = 2.0
    MAX_EVENTS_PER_TICK = 200
    VISUAL_INTERVAL_MS = 45
    EVENT_INTERVAL_MS = 30

    def __init__(self) -> None:
        super().__init__()
        self.title("Phonon 2 Studio")
        self.geometry("1240x800")
        self.minsize(900, 620)
        self.configure(bg="#080d19")
        self.tk.call("tk", "scaling", 1.08)
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.file_path = tk.StringVar()
        self.hotwords = tk.StringVar()
        self.port = tk.IntVar(value=8000)
        self.json_output = tk.BooleanVar(value=True)
        self.noise_suppression = tk.BooleanVar(value=True)
        self._noise_suppression_enabled = True
        self.ontology = SpeechOntology()
        self.status = tk.StringVar(value="Ready")
        self.model_status = tk.StringVar(value="Phonon-2 • local CPU engine")
        self.activity = tk.StringVar(value="No active transcription")
        self.engine_value = tk.StringVar(value="AVX2 CPU")
        self.privacy_value = tk.StringVar(value="100% offline")
        self.recording_stop = threading.Event()
        self.recording_thread: threading.Thread | None = None
        self.recording_stream = None
        self.recording_path: Path | None = None
        self.live_stop = threading.Event()
        self.live_thread: threading.Thread | None = None
        self.live_text = ""
        self.live_server: subprocess.Popen[str] | None = None
        self.live_port = 18001
        self.live_threads = 8
        self.live_partial_start = "end-1c"
        self.live_ready = threading.Event()
        self.audio_started = threading.Event()
        self.model_latched = threading.Event()
        self.live_start_error = ""
        self._partial_lock = threading.Lock()
        self._latest_partial: str | None = None
        self._compact_layout = False
        self.signal_level = 0.05
        self.signal_target = 0.05
        self._latest_audio_level = 0.05
        self._signal_bars: list[int] = []
        self._signal_bar_count = 0
        self._signal_color = ""
        self.playing = False
        self.play_started = 0.0
        self.play_duration = 0.0
        self.play_after: str | None = None
        self._configure_style()
        self._build_ui()
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._run_background(["describe"], "describe")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#0a0f1d")
        style.configure("Card.TFrame", background="#121a2d")
        style.configure("Panel.TFrame", background="#0d1425")
        style.configure("TLabel", background="#0a0f1d", foreground="#d9e2ff")
        style.configure("Muted.TLabel", background="#121a2d", foreground="#8391b5")
        style.configure("Title.TLabel", background="#0a0f1d", foreground="#f6f8ff",
                        font=("Segoe UI", 27, "bold"))
        style.configure("Subtitle.TLabel", background="#0a0f1d", foreground="#8391b5",
                        font=("Segoe UI", 10))
        style.configure("Heading.TLabel", background="#121a2d", foreground="#f3f6ff",
                        font=("Segoe UI", 13, "bold"))
        style.configure("Accent.TButton", background="#6d5dfc", foreground="white",
                        padding=(14, 10), font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Accent.TButton", background=[("active", "#8173ff")])
        style.configure("Ghost.TButton", background="#202b48", foreground="#d9e2ff",
                        padding=(12, 8))
        style.map("Ghost.TButton", background=[("active", "#2d3b61")])
        style.configure("TEntry", fieldbackground="#1b2742", foreground="#e9edff",
                        insertcolor="white", padding=9, borderwidth=0)
        style.configure("TSpinbox", fieldbackground="#1b2742", foreground="#e9edff",
                        arrowsize=12, padding=6)
        style.configure("TCheckbutton", background="#121a2d", foreground="#d9e2ff")
        style.configure("Status.TLabel", background="#111a2e", foreground="#aab8dc",
                        padding=11, font=("Segoe UI", 9))
        style.configure("Tab.TButton", background="#121a2d", foreground="#8391b5",
                        padding=(12, 8), font=("Segoe UI", 9, "bold"))
        style.map("Tab.TButton", background=[("active", "#1e2a48")],
                  foreground=[("active", "#f3f6ff")])
        style.configure("TSeparator", background="#293755")
        style.configure("TScrollbar", background="#18243b", troughcolor="#0a1120",
                        bordercolor="#0a1120", arrowcolor="#8190b3")
        style.map("TEntry", bordercolor=[("focus", "#7c6cff")],
                  lightcolor=[("focus", "#7c6cff")], darkcolor=[("focus", "#7c6cff")])

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(28, 24, 28, 18))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        brand = ttk.Frame(header)
        brand.pack(side="left")
        tk.Label(brand, text="PHONON", bg="#0a0f1d", fg="#7c6cff",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(brand, text="Phonon 2 Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            brand, text="A beautiful command center for private, local speech recognition.",
            style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        self._badge = tk.Label(
            header, textvariable=self.model_status, bg="#17233e", fg="#a9b9ff",
            padx=14, pady=9, font=("Segoe UI", 9, "bold"),
        )
        self._badge.pack(side="right", anchor="n", pady=(8, 0))

        metrics = ttk.Frame(outer)
        metrics.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self._metric(metrics, "ENGINE", self.engine_value, "#7c6cff")
        self._metric(metrics, "PRIVACY", self.privacy_value, "#38d6a3")
        self._metric(metrics, "ACTIVITY", self.activity, "#f2b866")

        body_view = ttk.Frame(outer)
        body_view.grid(row=2, column=0, sticky="nsew")
        body_view.columnconfigure(0, weight=1)
        body_view.rowconfigure(0, weight=1)
        body_canvas = tk.Canvas(body_view, bg="#080d19", highlightthickness=0, bd=0)
        body_canvas.grid(row=0, column=0, sticky="nsew")
        body_scroll = ttk.Scrollbar(body_view, orient="vertical", command=body_canvas.yview)
        body_scroll.grid(row=0, column=1, sticky="ns")
        body_canvas.configure(yscrollcommand=body_scroll.set)
        body = ttk.Frame(body_canvas)
        body_window = body_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: body_canvas.configure(
            scrollregion=body_canvas.bbox("all")
        ))
        body_canvas.bind("<Configure>", lambda event: body_canvas.itemconfigure(
            body_window, width=event.width
        ))
        body_canvas.bind_all("<MouseWheel>", lambda event: body_canvas.yview_scroll(
            int(-event.delta / 120), "units"
        ), add="+")
        self._body_canvas = body_canvas
        self._body_scroll = body_scroll
        body.columnconfigure(0, weight=0, minsize=315)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, style="Card.TFrame", padding=24)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right = ttk.Frame(body, style="Card.TFrame", padding=24)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_controls(left)
        self._build_output(right)
        self._body = body
        self._left_panel = left
        self._right_panel = right
        self._signal_canvas = None
        self._animate_visuals()
        self.bind("<Configure>", self._layout_responsive, add="+")
        self.bind("<Control-o>", lambda _event: self._browse(), add="+")
        self.bind("<Control-Return>", lambda _event: self._transcribe_file(), add="+")
        self.bind("<Control-s>", lambda _event: self._save_output(), add="+")
        self.bind("<Control-l>", lambda _event: self._toggle_listen(), add="+")
        self.bind("<Control-k>", lambda _event: self._clear_output(), add="+")
        self.bind("<Escape>", lambda _event: self._stop_active(), add="+")

        ttk.Label(outer, textvariable=self.status, style="Status.TLabel").grid(
            row=3, column=0, sticky="ew", pady=(16, 0)
        )

    def _layout_responsive(self, event: tk.Event) -> None:
        compact = event.width < 1040
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        if compact:
            self._body.columnconfigure(0, weight=1, minsize=0)
            self._body.columnconfigure(1, weight=1)
            self._left_panel.grid_configure(row=0, column=0, columnspan=2, padx=0, pady=(0, 14))
            self._right_panel.grid_configure(row=1, column=0, columnspan=2)
        else:
            self._body.columnconfigure(0, weight=0, minsize=315)
            self._body.columnconfigure(1, weight=1)
            self._left_panel.grid_configure(row=0, column=0, columnspan=1, padx=(0, 16), pady=0)
            self._right_panel.grid_configure(row=0, column=1, columnspan=1)

    def _stop_active(self) -> None:
        if self.live_thread is not None:
            self._stop_windows_live()
        elif self.process and self.process.poll() is None:
            self._stop_process()
            self.status.set("Stopped")
            self.activity.set("Ready for a new session")

    def _metric(self, parent: ttk.Frame, label: str, value: tk.StringVar, color: str) -> None:
        card = tk.Frame(parent, bg="#121a2d", padx=16, pady=12)
        card.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Frame(card, bg=color, width=4).pack(side="left", fill="y", padx=(0, 12))
        text = tk.Frame(card, bg="#121a2d")
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=label, bg="#121a2d", fg="#7180a4",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(text, textvariable=value, bg="#121a2d", fg="#f1f4ff",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(3, 0))

    def _build_controls(self, parent: ttk.Frame) -> None:
        tk.Label(parent, text="WORKSPACE", bg="#121a2d", fg="#7180a4",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Transcribe a file", style="Heading.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(parent, text="Turn a recording into searchable text on this device.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        file_row = ttk.Frame(parent, style="Card.TFrame")
        file_row.pack(fill="x")
        ttk.Entry(file_row, textvariable=self.file_path, width=34).pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Open  (Ctrl+O)", command=self._browse,
                   style="Ghost.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(parent, text="✦  Transcribe file  (Ctrl+Enter)", command=self._transcribe_file,
                   style="Accent.TButton").pack(fill="x", pady=(12, 22))
        playback_row = ttk.Frame(parent, style="Card.TFrame")
        playback_row.pack(fill="x", pady=(0, 16))
        self.play_button = ttk.Button(playback_row, text="▶  Play preview",
                                      command=self._toggle_playback, style="Tab.TButton")
        self.play_button.pack(side="left", fill="x", expand=True)
        ttk.Button(playback_row, text="■", command=self._stop_playback,
                   style="Tab.TButton").pack(side="left", padx=(8, 0))
        self.play_progress = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.play_progress.pack(fill="x", pady=(0, 4))
        ttk.Label(parent, text="Preview follows the selected WAV while the signal animates.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        ttk.Separator(parent).pack(fill="x", pady=(0, 20))
        ttk.Label(parent, text="Live microphone", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Stream microphone speech with live partial results.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 12))
        mic_row = ttk.Frame(parent, style="Card.TFrame")
        mic_row.pack(fill="x")
        self.listen_button = ttk.Button(mic_row, text="●  Start listening  (Ctrl+L)", command=self._toggle_listen,
                                        style="Accent.TButton")
        self.listen_button.pack(side="left", fill="x", expand=True)
        ttk.Button(mic_row, text="Clear", command=self._clear_output,
                   style="Ghost.TButton").pack(side="left", padx=(8, 0))

        ttk.Separator(parent).pack(fill="x", pady=(22, 20))
        ttk.Label(parent, text="Recognition options", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Tune vocabulary and output without leaving the workspace.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
        hotwords_entry = ttk.Entry(parent, textvariable=self.hotwords)
        hotwords_entry.pack(fill="x")
        hotwords_entry.insert(0, "")
        ttk.Label(parent, text="Hotwords  ·  comma-separated names and terms",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        ttk.Checkbutton(parent, text="Include word timestamps in JSON",
                        variable=self.json_output).pack(anchor="w", pady=(12, 20))
        ttk.Checkbutton(
            parent, text="Adaptive noise suppression (live mic)",
            variable=self.noise_suppression,
            command=self._update_noise_suppression,
        ).pack(anchor="w", pady=(0, 20))

        ttk.Separator(parent).pack(fill="x", pady=(0, 20))
        ttk.Label(parent, text="Local API server", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Connect your own tools to a loopback-only endpoint.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
        port_row = ttk.Frame(parent, style="Card.TFrame")
        port_row.pack(fill="x")
        ttk.Label(port_row, text="Port", style="Muted.TLabel").pack(side="left")
        ttk.Spinbox(port_row, from_=1024, to=65535, textvariable=self.port, width=8).pack(side="right")
        self.server_button = ttk.Button(parent, text="Start API server",
                                        command=self._toggle_server, style="Ghost.TButton")
        self.server_button.pack(fill="x", pady=(10, 0))

    def _build_output(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Card.TFrame")
        top.pack(fill="x")
        title_block = ttk.Frame(top, style="Card.TFrame")
        title_block.pack(side="left")
        ttk.Label(title_block, text="Transcript", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(title_block, text="Your local words, ready to refine or export.",
                  style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Button(top, text="Save  (Ctrl+S)", command=self._save_output,
                   style="Ghost.TButton").pack(side="right")
        toolbar = ttk.Frame(parent, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(18, 12))
        ttk.Button(toolbar, text="Clear canvas  (Ctrl+K)", command=self._clear_output,
                   style="Tab.TButton").pack(side="left")
        ttk.Button(toolbar, text="Export ontology", command=self._export_ontology,
                   style="Tab.TButton").pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, text="  •  Results stay on this machine",
                  style="Muted.TLabel").pack(side="left", padx=(8, 0))
        self._signal_canvas = tk.Canvas(
            parent, height=68, bg="#0d1425", highlightthickness=0, bd=0
        )
        self._signal_canvas.pack(fill="x", pady=(0, 12))
        self._signal_canvas.create_text(
            14, 14, anchor="w", text="LIVE SIGNAL", fill="#7180a4",
            font=("Segoe UI", 8, "bold"), tags="signal-label"
        )
        text_frame = ttk.Frame(parent, style="Panel.TFrame", padding=2)
        text_frame.pack(fill="both", expand=True)
        self.output = tk.Text(
            text_frame, wrap="word", undo=True, bg="#0a1120", fg="#e6ecff",
            insertbackground="#8c80ff", selectbackground="#5147a8", relief="flat",
            padx=22, pady=20, font=("Cascadia Mono", 11), spacing1=4,
        )
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose audio file",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"), ("All files", "*.*")],
        )
        if path:
            self.file_path.set(path)
            self._stop_playback()

    def _transcribe_file(self) -> None:
        if not self.file_path.get().strip():
            messagebox.showinfo("Choose audio", "Select an audio file first.")
            return
        args = ["transcribe", self.file_path.get().strip()]
        if self.json_output.get():
            args.append("--json")
        if self.hotwords.get().strip():
            args.extend(["--hotwords", self.hotwords.get().strip()])
        self._run_background(args, "transcribe")

    def _toggle_playback(self) -> None:
        if self.playing:
            self._stop_playback()
            return
        path = Path(self.file_path.get().strip())
        if not path.exists():
            messagebox.showinfo("Choose audio", "Select a local audio file first.")
            return
        if sys.platform != "win32" or path.suffix.lower() != ".wav":
            messagebox.showinfo("WAV preview", "Playback preview currently supports WAV files on Windows.")
            return
        try:
            import winsound
            with wave.open(str(path), "rb") as audio_file:
                self.play_duration = audio_file.getnframes() / max(audio_file.getframerate(), 1)
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.play_started = time.monotonic()
            self.playing = True
            self.play_button.configure(text="Ⅱ  Pause preview")
            self.activity.set("Playing audio preview")
        except Exception as exc:
            messagebox.showerror("Playback unavailable", str(exc))

    def _stop_playback(self) -> None:
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self.playing = False
        self.play_progress["value"] = 0
        if hasattr(self, "play_button"):
            self.play_button.configure(text="▶  Play preview")
        if self.activity.get() == "Playing audio preview":
            self.activity.set("Ready for a new session")

    def _animate_playback(self) -> None:
        if not self.playing:
            return
        elapsed = time.monotonic() - self.play_started
        percent = min(100, (elapsed / max(self.play_duration, 0.1)) * 100)
        self.play_progress["value"] = percent
        if percent >= 100:
            self._stop_playback()

    def _animate_visuals(self) -> None:
        self.signal_level += (self.signal_target - self.signal_level) * 0.35
        if self._signal_canvas is not None:
            canvas = self._signal_canvas
            width = max(canvas.winfo_width(), 300)
            center = 45
            bar_count = max(12, min(70, width // 15))
            if bar_count != self._signal_bar_count:
                canvas.delete("bars")
                self._signal_bars = [
                    canvas.create_line(0, center, 0, center, width=3,
                                       capstyle=tk.ROUND, tags="bars")
                    for _ in range(bar_count)
                ]
                self._signal_bar_count = bar_count
                self._signal_color = ""
            now = time.monotonic()
            color = "#7c6cff" if self.signal_level > 0.12 else "#334264"
            for index, bar in enumerate(self._signal_bars):
                phase = index * 0.72 + now * 5.5
                wave_height = (math.sin(phase) + 1.0) * 0.5
                height = 4 + (self.signal_level * 30 * wave_height)
                x = 14 + index * ((width - 28) / max(bar_count - 1, 1))
                canvas.coords(bar, x, center - height, x, center + height)
                if color != self._signal_color:
                    canvas.itemconfigure(bar, fill=color)
            self._signal_color = color
        if self.playing:
            self._animate_playback()
        self.after(self.VISUAL_INTERVAL_MS, self._animate_visuals)

    def _toggle_listen(self) -> None:
        if self.live_thread is not None:
            self._stop_windows_live()
            return
        if self.process and self.process.poll() is None and getattr(self, "_mode", "") == "listen":
            self._stop_process()
            self.listen_button.configure(text="●  Start listening")
            return
        if sys.platform == "win32":
            self._start_windows_live()
        else:
            self._run_background(["listen"], "listen")
            self.listen_button.configure(text="■  Stop listening")

    def _update_noise_suppression(self) -> None:
        self._noise_suppression_enabled = self.noise_suppression.get()

    def _start_windows_live(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            messagebox.showerror(
                "Microphone unavailable",
                "Install the microphone capture dependency with:\n"
                ".phonon-venv\\Scripts\\python.exe -m pip install sounddevice",
            )
            return

        self._stop_process()
        self._start_live_server()
        audio_queue: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=self.AUDIO_QUEUE_SIZE)
        self.live_stop.clear()
        self.live_ready.clear()
        self.audio_started.clear()
        self.model_latched.clear()
        self.live_start_error = ""
        self._latest_audio_level = 0.04
        packet_number = 0
        noise_floor = 0.008
        noise_frames = 0
        previous_input = 0.0
        previous_output = 0.0

        def callback(indata, frames, time_info, status) -> None:
            nonlocal noise_floor, noise_frames, previous_input, previous_output, packet_number
            if status:
                self.events.put(("output", f"[microphone] {status}\n"))
            raw = bytes(indata)
            samples = array("h")
            samples.frombytes(raw)
            if self._noise_suppression_enabled and samples:
                filtered = array("h")
                sum_squares = 0.0
                for sample in samples:
                    normalized = sample / 32768.0
                    high_passed = normalized - previous_input + (0.995 * previous_output)
                    previous_input = normalized
                    previous_output = high_passed
                    filtered_value = max(-1.0, min(1.0, high_passed))
                    filtered.append(int(filtered_value * 32767))
                    sum_squares += high_passed * high_passed
                frame_rms = math.sqrt(sum_squares / len(filtered))
                if noise_frames < 18:
                    noise_floor = (noise_floor * 0.9) + (frame_rms * 0.1)
                    noise_frames += 1
                threshold = max(0.012, noise_floor * 2.4)
                if frame_rms < threshold:
                    gain = max(0.18, frame_rms / threshold)
                    for index, value in enumerate(filtered):
                        filtered[index] = int(value * gain)
                raw = filtered.tobytes()
                samples = filtered
            if samples:
                rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
                self._latest_audio_level = min(1.0, rms * 3.5)
            packet_number += 1
            packet = (packet_number, raw)
            try:
                audio_queue.put_nowait(packet)
            except queue.Full:
                try:
                    audio_queue.get_nowait()
                    audio_queue.put_nowait(packet)
                except (queue.Empty, queue.Full):
                    pass

        try:
            self._mode = "live"
            self.live_thread = threading.Thread(
                target=self._websocket_live_loop,
                args=(audio_queue,),
                daemon=True,
            )
            self.live_thread.start()
            if not self.live_ready.wait(self.LIVE_READY_TIMEOUT):
                self.live_stop.set()
                self._stop_live_server()
                self.live_thread = None
                raise RuntimeError("The local speech stream did not become ready.")
            if self.live_start_error:
                raise RuntimeError(self.live_start_error)
            self.recording_stream = sd.RawInputStream(
                samplerate=16000, blocksize=self.AUDIO_PACKET_BYTES // 2, channels=1,
                dtype="int16", callback=callback,
            )
            self.recording_stream.start()
            self.audio_started.set()
            if not self.model_latched.wait(self.MODEL_LATCH_TIMEOUT):
                raise RuntimeError("The model did not latch onto the microphone stream.")
        except Exception as exc:
            self.recording_stream = None
            self.live_stop.set()
            self._stop_live_server()
            self.live_thread = None
            messagebox.showerror("Microphone unavailable", str(exc))
            return

        self.live_text = ""
        with self._partial_lock:
            self._latest_partial = None
        self.live_partial_start = self.output.index("end-1c")
        self.listen_button.configure(text="■  Stop live transcription")
        self.status.set("Live transcription is listening locally")
        self.activity.set("Live transcription")
    def _websocket_live_loop(self, audio_queue: queue.Queue[tuple[int, bytes]]) -> None:
        ws = None
        sender_done = threading.Event()
        try:
            import websocket
            ws = websocket.create_connection(
                f"ws://127.0.0.1:{self.live_port}/v1/audio/stream",
                timeout=0.25,
            )
            ws.send(json.dumps({"sample_rate": 16000, "format": "pcm_s16le"}))
            self.live_ready.set()

            def send_audio() -> None:
                first_packet_sent = False
                try:
                    while not self.audio_started.wait(0.05):
                        if self.live_stop.is_set():
                            return
                    while not self.live_stop.is_set() or not audio_queue.empty():
                        try:
                            packet_number, frame = audio_queue.get(timeout=0.02)
                        except queue.Empty:
                            continue
                        ws.send(frame, opcode=websocket.ABNF.OPCODE_BINARY)
                        if not first_packet_sent:
                            first_packet_sent = True
                            self.model_latched.set()
                            self.events.put(("live_state", "Audio and model latched"))
                    ws.send(json.dumps({"type": "end"}))
                except Exception as exc:
                    self.events.put(("output", f"[live send] {exc}\n"))
                finally:
                    sender_done.set()

            def receive_transcripts() -> None:
                try:
                    while True:
                        try:
                            message = json.loads(ws.recv())
                        except websocket.WebSocketTimeoutException:
                            if sender_done.is_set():
                                continue
                            continue
                        event_type = message.get("type")
                        if event_type == "partial":
                            with self._partial_lock:
                                self._latest_partial = message.get("text", "")
                        elif event_type in ("final", "done"):
                            with self._partial_lock:
                                self._latest_partial = None
                            self.events.put((event_type, message.get("text", "")))
                        elif event_type == "error":
                            self.events.put(("output", f"[live] {message.get('message', 'Unknown error')}\n"))
                            break
                        if event_type == "done":
                            break
                except Exception as exc:
                    if not self.live_stop.is_set():
                        self.events.put(("output", f"[live receive] {exc}\n"))

            sender = threading.Thread(target=send_audio, daemon=True)
            receiver = threading.Thread(target=receive_transcripts, daemon=True)
            sender.start()
            receiver.start()
            sender.join()
            receiver.join(timeout=5)
        except Exception as exc:
            self.live_start_error = str(exc)
            self.live_ready.set()
            self.events.put(("output", f"[live] {exc}\n"))
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _live_transcription_loop(self, audio_queue: queue.Queue[tuple[int, bytes]]) -> None:
        # Phonon's Windows CPU engine is file-oriented, so emulate streaming
        # with short overlapping windows. The overlap preserves word context;
        # deduplication below prevents repeated words in the canvas.
        rolling: deque[bytes] = deque()
        bytes_per_second = 16000 * 2
        window_bytes = int(bytes_per_second * 1.6)
        step_seconds = 0.65
        next_decode = datetime.now().timestamp() + step_seconds
        rolling_bytes = 0
        while not self.live_stop.is_set() or not audio_queue.empty():
            try:
                _packet_number, frame = audio_queue.get(timeout=0.05)
                rolling.append(frame)
                rolling_bytes += len(frame)
            except queue.Empty:
                pass
            while rolling_bytes > window_bytes:
                rolling_bytes -= len(rolling.popleft())
            now = datetime.now().timestamp()
            if now >= next_decode and rolling_bytes >= window_bytes:
                self._transcribe_live_chunk(list(rolling))
                next_decode = now + step_seconds
        if rolling:
            self._transcribe_live_chunk(list(rolling))

    def _transcribe_live_chunk(self, frames: list[bytes]) -> None:
        temp = NamedTemporaryFile(prefix="phonon-live-", suffix=".wav", delete=False)
        temp.close()
        path = Path(temp.name)
        try:
            with wave.open(str(path), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(16000)
                audio_file.writeframes(b"".join(frames))
            boundary = "----PhononLiveBoundary"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="model"\r\n\r\n'
                "phonon-2\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="live.wav"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.live_port}/v1/audio/transcriptions",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8")
            text = payload.strip()
            if text.startswith("{"):
                try:
                    text = json.loads(text).get("text", "")
                except json.JSONDecodeError:
                    pass
            if text:
                self._append_live_text(text.strip())
        except Exception as exc:
            self.events.put(("output", f"[live] {exc}\n"))
        finally:
            path.unlink(missing_ok=True)

    def _start_live_server(self) -> None:
        self.live_server = subprocess.Popen(
            [
                str(PHONON), "serve",
                "--backend", "native",
                "--threads", str(self.live_threads),
                "--port", str(self.live_port),
            ],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        for _ in range(30):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.live_port}/v1/models", timeout=0.5
                ):
                    return
            except Exception:
                threading.Event().wait(0.2)

    def _stop_live_server(self) -> None:
        if self.live_server and self.live_server.poll() is None:
            self.live_server.terminate()
            try:
                self.live_server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.live_server.kill()
        self.live_server = None

    def _append_live_text(self, text: str) -> None:
        words = text.split()
        previous = self.live_text.split()
        previous_lower = [word.lower() for word in previous]
        words_lower = [word.lower() for word in words]
        overlap = 0
        for size in range(min(len(previous), len(words)), 0, -1):
            if previous_lower[-size:] == words_lower[:size]:
                overlap = size
                break
        fresh = words[overlap:]
        if not fresh:
            return
        addition = " ".join(fresh)
        self.live_text = f"{self.live_text} {addition}".strip()
        self.events.put(("output", addition + " "))

    def _stop_windows_live(self) -> None:
        stream = self.recording_stream
        self.recording_stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.live_stop.set()
        with self._partial_lock:
            self._latest_partial = None
        self._latest_audio_level = 0.04
        self.signal_target = 0.04
        if self.live_thread:
            self.live_thread.join(timeout=65)
            self.live_thread = None
        self._stop_live_server()
        self.listen_button.configure(text="●  Start listening")
        self.status.set("Ready")
        self.activity.set("Ready for a new session")

    def _toggle_server(self) -> None:
        if self.process and self.process.poll() is None and getattr(self, "_mode", "") == "serve":
            self._stop_process()
            self.server_button.configure(text="Start API server")
            return
        self._run_background(["serve", "--port", str(self.port.get())], "serve")
        self.server_button.configure(text="Stop API server")

    def _read_process(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self.events.put(("output", line))
        code = process.wait()
        self.events.put(("process_done", str(code)))

    def _drain_events(self) -> None:
        try:
            self.signal_target = max(0.04, self._latest_audio_level)
            processed = 0
            with self._partial_lock:
                partial = self._latest_partial
                self._latest_partial = None
            if partial is not None:
                self._render_partial(partial)
            while processed < self.MAX_EVENTS_PER_TICK:
                kind, value = self.events.get_nowait()
                processed += 1
                if kind == "output":
                    self.output.insert("end", value)
                    self.output.see("end")
                elif kind == "level":
                    self.signal_target = max(0.04, float(value))
                    if self.live_thread is not None:
                        self.activity.set("Speaking" if self.signal_target > 0.12 else "Listening")
                elif kind in ("final", "done"):
                    self.activity.set("Listening" if self.live_thread is not None else "Ready for a new session")
                    self.output.delete(self.live_partial_start, "end")
                    if value:
                        final_text = value.strip()
                        self.output.insert("end", final_text + " ")
                        self.ontology.ingest(final_text)
                    self.live_partial_start = self.output.index("end-1c")
                    self.output.see("end")
                elif kind == "process_done":
                    self.status.set("Ready" if value == "0" else f"Process exited with code {value}")
                    self.activity.set("Ready for a new session")
                    if getattr(self, "_mode", "") in ("listen", "live"):
                        self.listen_button.configure(text="●  Start listening")
                    if getattr(self, "_mode", "") == "serve":
                        self.server_button.configure(text="Start API server")
                elif kind == "live_state":
                    self.status.set(value)
        except queue.Empty:
            pass
        self.after(self.EVENT_INTERVAL_MS, self._drain_events)

    def _render_partial(self, value: str) -> None:
        self.activity.set("Transcribing live audio")
        self.signal_target = max(self.signal_target, 0.18)
        self.output.delete(self.live_partial_start, "end")
        if value:
            self.output.insert("end", value)
        self.output.see("end")

    def _export_ontology(self) -> None:
        if not self.ontology.turns:
            messagebox.showinfo("Nothing to export", "Finish a transcript turn first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export ontology", defaultextension=".json",
            initialfile=f"phonon-ontology-{datetime.now():%Y%m%d-%H%M%S}.json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(
                json.dumps(self.ontology.snapshot(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self.status.set(f"Exported ontology to {path}")

    def _run_background(self, args: list[str], mode: str) -> None:
        self._stop_process()
        self._mode = mode
        command = [str(PHONON), *args] if isinstance(PHONON, Path) else [PHONON, *args]
        self.status.set(f"Running: {' '.join(args)}")
        self.activity.set({
            "transcribe": "Transcribing audio",
            "listen": "Listening to microphone",
            "serve": f"API on localhost:{self.port.get()}",
            "describe": "Checking engine",
        }.get(mode, "Working"))
        self.process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._read_process, args=(self.process,), daemon=True).start()

    def _stop_process(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _clear_output(self) -> None:
        self.output.delete("1.0", "end")
        self.live_text = ""
        self.ontology.reset()

    def _save_output(self) -> None:
        content = self.output.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("Nothing to save", "The transcript panel is empty.")
            return
        path = filedialog.asksaveasfilename(
            title="Save transcript", defaultextension=".txt",
            initialfile=f"phonon-transcript-{datetime.now():%Y%m%d-%H%M%S}.txt",
            filetypes=[("Text", "*.txt"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self.status.set(f"Saved transcript to {path}")

    def _close(self) -> None:
        if self.live_thread is not None:
            self._stop_windows_live()
        self._stop_live_server()
        self._stop_process()
        self.destroy()


if __name__ == "__main__":
    PhononDesktop().mainloop()
