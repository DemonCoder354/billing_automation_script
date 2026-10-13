"""AUTO-WORK main window: calibration, ticket source, start/pause, timings and the program output."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..paths import PDF_ROOT, PDF_TEXT_DIR
from . import calibration, state
from .applog import LOG_DIR, _path_from_name, setup_main_log
from .calibration import CALIBRATION_STEPS, load_calibration, missing_calibration_fields, run_calibration, save_calibration
from .pdf_source import (AUTO_START, DONE_LOG, clear_done_log, done_pdfs, list_ticket_pdfs, pdf_run,
                         pdf_start_index)
from .runner import main
from .settings import (SETTINGS, TIMING_DEFAULTS, TIMING_GROUPS, TIMING_MAX_SEC, T, fmt_sec, load_settings,
                       load_timings, save_timings, settings_lock, timings, update_settings)
from .state import console_queue, ui_queue


VK_O = 79   # O key code (Ctrl+O) - by code so that it works in any keyboard layout
VK_N = 78   # N key code (Ctrl+N)
VK_K = 75   # K key code (Ctrl+K - calibration)
VK_T = 84   # T key code (Ctrl+T - timings)


class AutoWorkApp:
    def __init__(self):
        settings = load_settings()      # logs/settings.json: calibration, logs, timings
        calibration.CALIBRATION_FILE = settings["calibration_file"]
        self.active_log = None           # path to the current log file
        self.root = tk.Tk()
        self.root.title("AUTO-WORK")
        _w, _h = 600, 860
        _x = (self.root.winfo_screenwidth() - _w) // 2
        _y = max(0, (self.root.winfo_screenheight() - _h) // 2)
        self.root.geometry(f"{_w}x{_h}+{_x}+{_y}")
        self.root.minsize(560, 700)

        self.worker_started = False
        self.start_pending = False
        self.resume_pending = False
        self.current_view = "main"       # 'main' | 'pause' | 'timings'
        self.overlay = None              # small window with calibration hints
        self.calib_active = False
        self.calib_lines = []
        self.calibrating = False         # standalone calibration is running ('Calibration' button)

        style = ttk.Style(self.root)
        style.configure("Big.TButton", padding=8)

        load_timings()
        self._build_main()
        self._build_pause()
        self._build_timings()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # last selected log (if the file still exists)
        name = settings.get("logs", {}).get("main", "")
        p = _path_from_name(name)
        if p and os.path.exists(p):
            self.log_var.set(name)

        self.apply_logs()
        self._update_cal_info()
        self._update_source()
        self.show_main()
        self.root.after(100, self._poll)

    # Building the screens
    def _build_main(self):
        f = self.main_frame = ttk.Frame(self.root, padding=12)

        cal = ttk.LabelFrame(f, text="Calibration file", padding=8)
        cal.pack(fill="x")
        row = ttk.Frame(cal)
        row.pack(fill="x")
        self.cal_var = tk.StringVar(value=calibration.CALIBRATION_FILE)
        self.cal_entry = ttk.Entry(row, textvariable=self.cal_var)
        self.cal_entry.pack(side="left", fill="x", expand=True)
        self.browse_btn = ttk.Button(row, text="Browse… (Ctrl+O)", command=self.browse_calibration)
        self.browse_btn.pack(side="left", padx=(6, 0))
        self.cal_info = ttk.Label(cal, text="")
        self.cal_info.pack(anchor="w", pady=(4, 0))
        self.calib_btn = ttk.Button(cal, text="Calibration (Ctrl+K)", style="Big.TButton",
                                    command=self.on_calibrate)
        self.calib_btn.pack(fill="x", pady=(6, 0))
        self.cal_var.trace_add("write", lambda *_: self._update_cal_info())

        # where to take tickets from: PDF files from the "PDF Tickets" program or the MedLedger screen
        src = ttk.LabelFrame(f, text="Ticket source", padding=8)
        src.pack(fill="x", pady=(10, 0))
        self.source_var = tk.StringVar(value=SETTINGS.get("ticket_source", "pdf"))
        self.source_radios = [
            ttk.Radiobutton(src, text="From PDF files (pdf_text - after the 'PDF Tickets' program)",
                            variable=self.source_var, value="pdf", command=self._update_source),
            ttk.Radiobutton(src, text="From the MedLedger screen (legacy: ► arrow and counter)",
                            variable=self.source_var, value="medledger", command=self._update_source),
        ]
        for r in self.source_radios:
            r.pack(anchor="w")
        prow = ttk.Frame(src)
        prow.pack(fill="x", pady=(4, 0))
        ttk.Label(prow, text="Folder:").pack(side="left")
        saved_folder = SETTINGS.get("pdf_folder", "")
        if not saved_folder or os.path.basename(os.path.normpath(saved_folder)).lower() != "pdf_text":
            saved_folder = PDF_TEXT_DIR   # this used to be the doctor's folder - now pdf_text by default
        self.pdf_folder_var = tk.StringVar(value=saved_folder)
        self.pdf_folder_entry = ttk.Entry(prow, textvariable=self.pdf_folder_var)
        self.pdf_folder_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.pdf_browse_btn = ttk.Button(prow, text="Browse…", command=self.browse_pdf_folder)
        self.pdf_browse_btn.pack(side="left", padx=(6, 0))
        strow = ttk.Frame(src)
        strow.pack(fill="x", pady=(4, 0))
        ttk.Label(strow, text="Start from:").pack(side="left")
        self.pdf_start_var = tk.StringVar(value=AUTO_START)
        self.pdf_start_combo = ttk.Combobox(strow, textvariable=self.pdf_start_var, state="readonly",
                                            width=34, postcommand=self._fill_start_files)
        self.pdf_start_combo.pack(side="left", padx=(4, 0))
        self.pdf_start_combo.bind("<<ComboboxSelected>>", lambda e: self._update_source())
        srow = ttk.Frame(src)
        srow.pack(fill="x", pady=(4, 0))
        self.pdf_info = ttk.Label(srow, text="", foreground="#555", wraplength=330, justify="left")
        self.pdf_info.pack(side="left")
        self.clear_done_btn = ttk.Button(srow, text="Clear log", command=self.on_clear_done_log)
        self.clear_done_btn.pack(side="right")
        ttk.Button(srow, text="Finished log", command=self.open_done_log).pack(side="right", padx=(0, 6))
        self.pdf_folder_var.trace_add("write", lambda *_: self._update_source())

        ctl = ttk.Frame(f)
        ctl.pack(fill="x", pady=10)
        self.start_btn = ttk.Button(ctl, text="Start (F6)", style="Big.TButton", command=self.on_start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.pause_btn = ttk.Button(ctl, text="Pause (F9)", style="Big.TButton", command=self.on_pause_button)
        self.pause_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.menu_btn = ttk.Button(ctl, text="Menu (F10)", style="Big.TButton", command=self.show_pause_menu)
        self.menu_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.state_var = tk.StringVar()
        ttk.Label(f, textvariable=self.state_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.msg_var = tk.StringVar()
        ttk.Label(f, textvariable=self.msg_var, wraplength=530, foreground="#a00").pack(anchor="w")

        ttk.Separator(f).pack(fill="x", pady=10)

        self.timings_btn = ttk.Button(f, text="Timings and delays (Ctrl+T)",
                                      style="Big.TButton", command=self.show_timings)
        self.timings_btn.pack(fill="x", pady=(0, 6))

        self.new_session_btn = ttk.Button(f, text="New session (Ctrl+N)",
                                          style="Big.TButton", command=self.on_new_session)
        self.new_session_btn.pack(fill="x")

        logs = ttk.LabelFrame(
            f, text="Log name (without extension). Empty = use the latest log", padding=8)
        logs.pack(fill="x", pady=(10, 0))
        logs.columnconfigure(1, weight=1)
        ttk.Label(logs, text="Log:").grid(row=0, column=0, sticky="w", pady=2, padx=(0, 8))
        self.log_var = tk.StringVar()
        ttk.Entry(logs, textvariable=self.log_var).grid(row=0, column=1, sticky="ew", pady=2)

        self.active_var = tk.StringVar()
        ttk.Label(f, textvariable=self.active_var, justify="left").pack(anchor="w", pady=(10, 0))

        box = ttk.LabelFrame(f, text="Program output", padding=4)
        box.pack(fill="both", expand=True, pady=(10, 0))
        self.console = tk.Text(box, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(box, command=self.console.yview)
        self.console.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)

    def _build_timings(self):
        f = self.timing_frame = ttk.Frame(self.root, padding=12)
        ttk.Label(f, text="TIMINGS AND DELAYS", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(f, text="Values in seconds (fractions allowed, e.g. 0.5). After 'Save' "
                          "they apply immediately, including while the program is running.",
                  wraplength=540).pack(anchor="w", pady=(2, 8))

        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True)
        canvas = self.timing_canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.timing_vars = {}
        for title, items in TIMING_GROUPS:
            box = ttk.LabelFrame(inner, text=title, padding=8)
            box.pack(fill="x", pady=(0, 8), padx=(0, 6))
            box.columnconfigure(0, weight=1)
            for i, (key, default, label) in enumerate(items):
                ttk.Label(box, text=label).grid(row=i, column=0, sticky="w", pady=2)
                var = tk.StringVar()
                self.timing_vars[key] = var
                ttk.Entry(box, textvariable=var, width=8, justify="right").grid(row=i, column=1, padx=6)
                ttk.Label(box, text=f"(default {fmt_sec(default)})", foreground="#666").grid(
                    row=i, column=2, sticky="w")

        self.timing_msg = tk.StringVar()
        ttk.Label(f, textvariable=self.timing_msg, wraplength=540, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(6, 0))
        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Save", style="Big.TButton", command=self.save_timings_clicked).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(btns, text="Defaults", style="Big.TButton", command=self.reset_timings_fields).pack(
            side="left", expand=True, fill="x", padx=4)
        ttk.Button(btns, text="← Back (Esc)", style="Big.TButton", command=self.show_main).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

    def _build_pause(self):
        f = self.pause_frame = ttk.Frame(self.root, padding=12)
        ttk.Label(f, text="PAUSE MENU (F10)", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(f, text="The program is paused.").pack(anchor="w", pady=(2, 10))
        ttk.Button(f, text="Continue (after the start delay) [1]", style="Big.TButton",
                   command=self.continue_work).pack(fill="x", pady=3)
        ttk.Button(f, text="← Main menu (Esc)", command=self.show_main).pack(fill="x", pady=(14, 0))

    # Keyboard (button equivalents). F6/F9/F10 are global (they work while the window is minimized),
    # the rest work when the window has focus.
    def _bind_keys(self):
        self.root.bind_all("<Key>", self._on_key)
        self.root.bind_all("<Escape>", self._on_escape)
        self.root.bind_all("<Control-Key>", self._on_ctrl_key)
        self.root.bind_all("<MouseWheel>", self._on_wheel)

    def _focus_in_entry(self):
        try:
            return isinstance(self.root.focus_get(), tk.Entry)
        except Exception:
            return False

    def _on_key(self, event):
        if self.current_view != "pause" or self._focus_in_entry():
            return
        if event.char == "1":
            self.continue_work()

    def _on_ctrl_key(self, event):
        if self.current_view != "main":
            return
        if event.keycode == VK_O:
            self.browse_calibration()
        elif event.keycode == VK_N:
            self.on_new_session()
        elif event.keycode == VK_K:
            self.on_calibrate()
        elif event.keycode == VK_T:
            self.show_timings()

    def _on_wheel(self, event):
        if self.current_view == "timings":
            self.timing_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_escape(self, event=None):
        if self.current_view == "timings":
            self.show_main()
            return
        if self.current_view == "pause":
            self.show_main()

    # Switching screens
    def show_main(self):
        self.pause_frame.pack_forget()
        self.timing_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True)
        self.current_view = "main"
        self.root.focus_set()

    def show_pause(self):
        self.main_frame.pack_forget()
        self.timing_frame.pack_forget()
        self.pause_frame.pack(fill="both", expand=True)
        self.current_view = "pause"
        self.root.focus_set()

    def show_timings(self):
        """'Timings and delays' button (Ctrl+T): pause settings screen."""
        for key, var in self.timing_vars.items():
            var.set(fmt_sec(T(key)))
        self.timing_msg.set("")
        self.main_frame.pack_forget()
        self.pause_frame.pack_forget()
        self.timing_frame.pack(fill="both", expand=True)
        self.current_view = "timings"
        self.timing_canvas.yview_moveto(0)
        self.root.focus_set()

    def reset_timings_fields(self):
        for key, var in self.timing_vars.items():
            var.set(fmt_sec(TIMING_DEFAULTS[key]))
        self.timing_msg.set("Default values filled in - press 'Save' to apply them.")

    def save_timings_clicked(self):
        labels = {key: label for _t, items in TIMING_GROUPS for key, _d, label in items}
        new_values = {}
        for key, var in self.timing_vars.items():
            text = var.get().strip().replace(",", ".")
            try:
                value = float(text)
                if not (0 <= value <= TIMING_MAX_SEC) or value != value:
                    raise ValueError
            except ValueError:
                self.timing_msg.set(f"Invalid value: '{labels[key]}'. Must be a number from 0 to {TIMING_MAX_SEC}.")
                return
            new_values[key] = value
        timings.update(new_values)
        if save_timings():
            self.timing_msg.set("Saved and applied.")
        else:
            self.timing_msg.set("Applied, but the settings file could not be saved (see 'Program output').")

    def show_pause_menu(self):
        """F10 / 'Menu' button: pauses the program and shows the pause menu."""
        if self.worker_started:
            state.is_paused = True
        if self.current_view != "pause":
            print("\n" + "#" * 50)
            print("[F10] PAUSE MENU")
            print("#" * 50)
            self.show_pause()
        self.restore_window()

    def restore_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(400, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    # Main menu: calibration, start, pause, sessions
    def _update_cal_info(self):
        path = self.cal_var.get().strip()
        if not path:
            self.cal_info.config(text="No path specified.")
        elif os.path.exists(path):
            self.cal_info.config(text="File found - calibration will be loaded from it.")
        else:
            self.cal_info.config(text="File not found - press 'Calibration', the result will be saved to this path.")

    def browse_calibration(self):
        if self.worker_started or self.calibrating:
            return
        current = self.cal_var.get().strip()
        initial_dir = os.path.dirname(os.path.abspath(current)) if current else os.getcwd()
        path = filedialog.askopenfilename(
            title="Calibration file", initialdir=initial_dir,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self.cal_var.set(path)

    def apply_logs(self, new_session=False):
        path = setup_main_log(self.log_var.get(), new_session)
        self.active_log = path
        self.log_var.set(os.path.splitext(os.path.basename(path))[0])  # the field shows the actual log
        self.active_var.set(f"Current log: {os.path.basename(path)}")
        self._save_settings()

    def _save_settings(self):
        """Saves the calibration path, log and ticket source to logs/settings.json."""
        try:
            update_settings(
                calibration_file=self.cal_var.get().strip() or calibration.CALIBRATION_FILE,
                logs={"main": self.log_var.get().strip()},
                ticket_source=self.source_var.get(),
                pdf_folder=self.pdf_folder_var.get().strip())
        except Exception as e:
            print(f"[SETTINGS] [ERROR] {e}")

    # Ticket source (PDF / MedLedger screen)
    def _update_source(self):
        """Enables the folder fields only in PDF mode and shows how many tickets there are and where the run will start."""
        pdf = self.source_var.get() == "pdf"
        busy = self.worker_started
        for w in (self.pdf_folder_entry, self.pdf_browse_btn, self.clear_done_btn):
            w.config(state="normal" if pdf and not busy else "disabled")
        self.pdf_start_combo.config(state="readonly" if pdf and not busy else "disabled")
        if not pdf:
            self.pdf_info.config(text="")
            return
        folder = self.pdf_folder_var.get().strip()
        tickets = list_ticket_pdfs(folder) if folder else []
        if not folder or not os.path.isdir(folder):
            self.pdf_info.config(text="folder not found")
        elif not tickets:
            self.pdf_info.config(text="no PDF tickets in the folder (run 'OCR' in 'PDF Tickets')")
        else:
            start = pdf_start_index(tickets)
            names = [os.path.basename(p) for _n, p in tickets]
            chosen = self.pdf_start_var.get()
            if chosen != AUTO_START and chosen in names:
                self.pdf_info.config(text=f"tickets: {len(tickets)} - will start from the selected {chosen}")
                return
            if chosen != AUTO_START:
                self.pdf_start_var.set(AUTO_START)
            if done_pdfs() and any(os.path.basename(p).lower() in {n.lower() for n in done_pdfs()}
                                   for _n, p in tickets):
                last = os.path.basename(tickets[start][1])
                text = (f"tickets: {len(tickets)}, last in the log {last} - will start from it "
                        f"({len(tickets) - start} left)")
            else:
                text = f"tickets: {len(tickets)} - will start from the first one ({os.path.basename(tickets[0][1])})"
            self.pdf_info.config(text=text)

    def _fill_start_files(self):
        """'Start from' list: auto + all PDFs of the folder in order."""
        files = [os.path.basename(p) for _n, p in list_ticket_pdfs(self.pdf_folder_var.get().strip())]
        self.pdf_start_combo.config(values=[AUTO_START] + files)

    def on_clear_done_log(self):
        n = len(done_pdfs())
        if not messagebox.askyesno("Clear finished log",
                                   f"Finished PDFs in the log: {n}.\n\nClear it? The file goes to the Recycle Bin, "
                                   "the next run will start from the first PDF."):
            return
        err = clear_done_log()
        if err:
            messagebox.showerror("Clear finished log", f"Failed: {err}")
        else:
            print("[PDF] Finished PDF log cleared (the file is in the Recycle Bin).")
        self._update_source()

    def open_done_log(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        if not os.path.exists(DONE_LOG):
            open(DONE_LOG, "a", encoding="utf-8").close()
        os.startfile(DONE_LOG)

    def browse_pdf_folder(self):
        path = filedialog.askdirectory(title="Folder with PDF tickets (pdf_text)",
                                       initialdir=self.pdf_folder_var.get().strip() or PDF_ROOT)
        if path:
            self.pdf_folder_var.set(os.path.normpath(path))

    def _check_pdf_source(self):
        """Before starting in PDF mode: the folder exists and contains tickets."""
        folder = self.pdf_folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            return "Specify the folder with PDF tickets (pdf_text)."
        tickets = list_ticket_pdfs(folder)
        if not tickets:
            return f"No PDF tickets in the folder:\n{folder}\n\nRun 'OCR' in the 'PDF Tickets' program first."
        names = [os.path.basename(p) for _n, p in tickets]
        chosen = self.pdf_start_var.get()
        pdf_run["start_name"] = chosen if chosen in names else ""
        pdf_run["folder"] = folder
        return None

    def on_new_session(self):
        self.log_var.set("")
        self.apply_logs(new_session=True)
        self.msg_var.set("")
        print("[SESSION] New session created - writing to a new log file from now on.")

    def on_start(self):
        """Start / F6: applies the settings, minimizes the window and starts (or resumes) work after the start delay."""
        if self.start_pending:
            return
        if self.calibrating:
            self.msg_var.set("Calibration is running - wait for it to finish.")
            return
        if not self.worker_started:
            cal_path = self.cal_var.get().strip()
            if not cal_path:
                self.msg_var.set("Specify the path to the calibration file.")
                self.show_main()
                self.restore_window()
                return
            calibration.CALIBRATION_FILE = cal_path
            if not os.path.exists(cal_path):
                self.show_main()
                self.restore_window()
                messagebox.showwarning(
                    "Calibration file not found",
                    f"Calibration file not found:\n{cal_path}\n\n"
                    "Choose another file via 'Browse' or press 'Calibration' to create it.")
                return
            if load_calibration() is None:
                self.show_main()
                self.restore_window()
                messagebox.showwarning(
                    "Calibration file is not valid",
                    f"The calibration file is corrupted or some steps are missing:\n{cal_path}\n\n"
                    "Press 'Calibration' - if only new steps are missing, "
                    "you can calibrate just those.")
                return
            if self.source_var.get() == "pdf":
                problem = self._check_pdf_source()
                if problem:
                    self.show_main()
                    self.restore_window()
                    messagebox.showwarning("Tickets from PDF", problem)
                    return
            with settings_lock:
                SETTINGS["ticket_source"] = self.source_var.get()
        self.msg_var.set("")
        self.apply_logs()
        self.start_pending = True
        print(f"[START] Window minimized. Work will start in {fmt_sec(T('start_delay'))} sec...")
        self.root.iconify()
        self.root.after(int(T("start_delay") * 1000), self._finish_start)

    def _finish_start(self):
        self.start_pending = False
        if not self.worker_started:
            state.is_paused = False
            self.worker_started = True
            self.cal_entry.config(state="disabled")
            self.browse_btn.config(state="disabled")
            self.calib_btn.config(state="disabled")
            for r in self.source_radios:
                r.config(state="disabled")
            self._update_source()
            threading.Thread(target=self._run_main, daemon=True).start()
        elif state.is_paused:
            state.is_paused = False
            print("[RESUMED]")

    def on_calibrate(self):
        """'Calibration' button: minimizes the window, goes through the calibration steps after the start delay and saves the file."""
        if self.worker_started or self.start_pending or self.calibrating:
            return
        cal_path = self.cal_var.get().strip()
        if not cal_path:
            self.msg_var.set("Specify where to save the calibration file.")
            return
        calibration.CALIBRATION_FILE = cal_path
        raw, missing = missing_calibration_fields() if os.path.exists(cal_path) else (None, None)
        if raw is None:
            self._start_calibration(None, None)   # no file - full calibration
        else:
            self._calibration_menu(raw, missing)

    def _calibration_menu(self, raw, missing):
        """Calibration menu: which steps to redo (the rest stay as in the file)."""
        win = tk.Toplevel(self.root)
        win.title("Calibration")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        tk.Label(win, text="Check the steps that need to be recalibrated.\n"
                           "The rest will stay as in the file.", justify="left").pack(anchor="w", padx=12, pady=(10, 6))
        frame = tk.Frame(win)
        frame.pack(fill="x", padx=12)
        checks = []
        for i, (name, kind, title, _hint) in enumerate(CALIBRATION_STEPS, 1):
            var = tk.BooleanVar(value=name in missing)
            presence = "MISSING - needs calibration" if name in missing else "present"
            kind_text = "point" if kind == "point" else "region"
            tk.Checkbutton(frame, variable=var, anchor="w",
                           text=f"{i}. {title} ({kind_text}) - {presence}").pack(fill="x", anchor="w")
            checks.append((name, var))

        def set_all(value):
            for _n, v in checks:
                v.set(value)

        def start():
            only = [n for n, v in checks if v.get()]
            if not only:
                messagebox.showinfo("Calibration", "No steps are checked.", parent=win)
                return
            win.destroy()
            self._start_calibration(only, raw)

        row = tk.Frame(win)
        row.pack(fill="x", padx=12, pady=(6, 0))
        tk.Button(row, text="Check all", command=lambda: set_all(True)).pack(side="left")
        tk.Button(row, text="Uncheck all", command=lambda: set_all(False)).pack(side="left", padx=6)
        row = tk.Frame(win)
        row.pack(fill="x", padx=12, pady=10)
        tk.Button(row, text="Calibrate checked", command=start).pack(side="left")
        tk.Button(row, text="Cancel", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())

    def _start_calibration(self, only, base):
        """Minimizes the window and goes through the calibration steps after start_delay (only=None - all)."""
        self.calib_only, self.calib_base = only, base
        self._save_settings()
        self.msg_var.set("")
        self.calibrating = True
        for w in (self.calib_btn, self.cal_entry, self.browse_btn):
            w.config(state="disabled")
        print(f"[CALIBRATION] Window minimized. Calibration will start in {fmt_sec(T('start_delay'))} sec...")
        self.root.iconify()
        self.root.after(int(T("start_delay") * 1000),
                        lambda: threading.Thread(target=self._run_calibration, daemon=True).start())

    def _run_calibration(self):
        try:
            data = run_calibration(getattr(self, "calib_only", None), getattr(self, "calib_base", None))
            save_calibration(data)
        except Exception as e:
            print(f"[CALIBRATION] [ERROR] {e}")
        ui_queue.put("calibration_done")

    def _finish_calibration(self):
        self.calibrating = False
        for w in (self.calib_btn, self.cal_entry, self.browse_btn):
            w.config(state="normal")
        self.calib_active = False
        self._refresh_overlay()
        self._update_cal_info()
        self.show_main()
        self.restore_window()
        if os.path.exists(calibration.CALIBRATION_FILE) and load_calibration() is not None:
            messagebox.showinfo("Calibration", f"Calibration saved:\n{calibration.CALIBRATION_FILE}\n\nYou can press Start now.")
        else:
            messagebox.showerror("Calibration", "Failed to save the calibration. See the 'Program output' panel for details.")

    def _run_main(self):
        try:
            main()
        except Exception as e:
            print(f"\n[ERROR] The program stopped: {e}")

    def on_pause_button(self):
        if not self.worker_started:
            self.msg_var.set("The program is not running yet - press Start.")
            return
        state.toggle_pause()

    # F10 menu: continue work
    def continue_work(self):
        """'Continue': minimize the window and unpause after the start delay."""
        if not self.worker_started:
            self.on_start()
            return
        if self.resume_pending:
            return
        self.resume_pending = True
        print(f"\n[MENU] Continuing in {fmt_sec(T('start_delay'))} seconds...")
        self.root.iconify()
        self.root.after(int(T("start_delay") * 1000), self._finish_resume)

    def _finish_resume(self):
        self.resume_pending = False
        state.is_paused = False
        print("[RESUMED]")

    # Helpers
    def _drain_console(self):
        """Moves the accumulated program output lines to the 'Program output' panel."""
        lines = []
        try:
            while True:
                lines.append(console_queue.get_nowait())
        except queue.Empty:
            pass
        if not lines:
            return
        self.console.config(state="normal")
        self.console.insert("end", "\n".join(lines) + "\n")
        total = int(self.console.index("end-1c").split(".")[0])
        if total > 1500:
            self.console.delete("1.0", f"{total - 1000}.0")
        self.console.see("end")
        self.console.config(state="disabled")
        for line in lines:
            self._track_calibration(line)
        self._refresh_overlay()

    def _track_calibration(self, line):
        """Watches the calibration output to show hints in a small always-on-top window."""
        if "CALIBRATION MODE" in line or "Found saved file" in line:
            self.calib_active = True
            self.calib_lines = []
        if self.calib_active and line.strip() and "DEBUG" not in line:
            self.calib_lines = (self.calib_lines + [line.strip()])[-6:]
        if ("CALIBRATION COMPLETE" in line or "Using saved coordinates" in line
                or "Saved to file" in line or "Failed to save calibration file" in line):
            self.calib_active = False

    def _refresh_overlay(self):
        if self.calib_active:
            if self.overlay is None:
                self._create_overlay()
            self.overlay_label.config(text="\n".join(self.calib_lines))
            self.overlay.lift()
        elif self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None

    def _create_overlay(self):
        ov = self.overlay = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.92)
        sw, sh = ov.winfo_screenwidth(), ov.winfo_screenheight()
        ov.geometry(f"520x160+{sw - 540}+{sh - 260}")
        self.overlay_label = tk.Label(ov, text="", justify="left", anchor="nw", bg="#202020", fg="#ffffff",
                                      wraplength=500, font=("Segoe UI", 10), padx=10, pady=8)
        self.overlay_label.pack(fill="both", expand=True)
        for w in (ov, self.overlay_label):   # the window can be dragged with the mouse if it covers a needed element
            w.bind("<ButtonPress-1>", self._overlay_press)
            w.bind("<B1-Motion>", self._overlay_drag)
        ov.deiconify()

    def _overlay_press(self, event):
        self._ov_dx = event.x_root - self.overlay.winfo_x()
        self._ov_dy = event.y_root - self.overlay.winfo_y()

    def _overlay_drag(self, event):
        self.overlay.geometry(f"+{event.x_root - self._ov_dx}+{event.y_root - self._ov_dy}")

    def _poll(self):
        self._drain_console()
        try:
            while True:
                cmd = ui_queue.get_nowait()
                if cmd == "start":
                    self.on_start()
                elif cmd == "pause_menu":
                    self.show_pause_menu()
                elif cmd == "calibration_done":
                    self._finish_calibration()
                elif cmd == "page_lost":
                    self.restore_window()
                    self.msg_var.set("PAUSED: the website page changed (kicked out?). Return to the working page and "
                                     "press F9 - the current ticket will be repeated.")
                elif cmd == "file_not_saved":
                    self.restore_window()
                    self.msg_var.set("PAUSED: the file was not saved (see 'Program output'). "
                                     "Check the save dialog and press F9.")
                elif cmd == "pdf_done":
                    self.restore_window()
                    self.msg_var.set("All PDF tickets processed. Restart the program to process another folder.")
        except queue.Empty:
            pass

        if self.start_pending:
            status = f"Status: starting in {fmt_sec(T('start_delay'))} sec…"
        elif not self.worker_started:
            status = "Status: not started"
        elif state.is_paused:
            status = "Status: PAUSED"
        else:
            status = "Status: running"
        self.state_var.set(status)
        self.pause_btn.config(text="Continue (F9)" if state.is_paused else "Pause (F9)")
        self.root.after(100, self._poll)

    def on_close(self):
        self._save_settings()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
