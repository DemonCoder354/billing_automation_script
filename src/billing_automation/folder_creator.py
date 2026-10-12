"""Week Folders: creates the CarePortal week folder structure on the desktop.

Enter the Monday date in MMDDYYYY format and press Create. This creates:
    <Desktop>\\CAREPORTAL {monday}-{friday}\\
        {DOCTOR}\\
            {DOCTOR} {monday} ... {DOCTOR} {friday}

Doctor names are read from doctors.txt in the root folder (one per line).
"""
from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .doctors import load_doctors
from .paths import DESKTOP_DIR, ROOT_DIR
from .week_folders import DATE_FORMAT, create_week_folders

BASE_PATH = DESKTOP_DIR


class App:
    def __init__(self):
        self.doctors = load_doctors()
        self.root = tk.Tk()
        self.root.title("Create CarePortal folders")
        self.root.geometry("620x460")
        self.root.minsize(520, 380)

        f = ttk.Frame(self.root, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text=self._instruction(), justify="left").pack(anchor="w")

        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Monday date:").pack(side="left")
        self.date_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.date_var, width=14)
        self.entry.pack(side="left", padx=8)
        self.entry.bind("<Return>", lambda e: self.on_create())
        self.btn = ttk.Button(row, text="Create", command=self.on_create)
        self.btn.pack(side="left")

        box = ttk.LabelFrame(f, text="Result", padding=4)
        box.pack(fill="both", expand=True, pady=(12, 0))
        self.out = tk.Text(box, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(box, command=self.out.yview)
        self.out.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True)

        self.entry.focus_set()

    def _instruction(self) -> str:
        return (
            "Instructions:\n"
            "1. Enter the MONDAY date in MMDDYYYY format (e.g. 08242026).\n"
            "2. Press Create (or Enter).\n"
            f"3. A week folder CAREPORTAL <mon>-<fri> will appear in {BASE_PATH},\n"
            "    containing the doctors' folders (" + ", ".join(self.doctors) + ")\n"
            "    with a subfolder for each day from Monday to Friday."
        )

    def log(self, text: str) -> None:
        self.out.config(state="normal")
        self.out.insert("end", text + "\n")
        self.out.see("end")
        self.out.config(state="disabled")

    def clear_log(self) -> None:
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.config(state="disabled")

    def on_create(self) -> None:
        if not self.doctors:
            messagebox.showerror("No doctors", f"No doctor names found.\nAdd them to {os.path.join(ROOT_DIR, 'doctors.txt')}.")
            return
        raw = self.date_var.get().strip()
        try:
            date = datetime.strptime(raw, DATE_FORMAT)
        except ValueError:
            messagebox.showerror("Invalid date", "Invalid date format.\nExample: 08242026 (MMDDYYYY).")
            return

        if date.weekday() != 0:  # 0 = Monday
            if not messagebox.askyesno(
                    "Not a Monday",
                    f"{raw} is a {date.strftime('%A')}, not a Monday.\n\nContinue anyway?"):
                return

        self.clear_log()
        try:
            path = create_week_folders(BASE_PATH, self.doctors, date, self.log)
        except Exception as e:
            self.log(f"[ERROR] {e}")
            messagebox.showerror("Error", f"Could not create the folders:\n{e}")
            return
        messagebox.showinfo("Done", f"The structure was created:\n{path}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
