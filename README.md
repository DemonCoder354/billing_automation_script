# Billing Automation Script

A set of Windows desktop tools that automate a weekly medical-billing routine: printed **NextGen** fee tickets are turned into searchable PDFs, and for every ticket the matching patient records are found and downloaded from a patient-records web portal (called **CarePortal** here) into a dated folder structure.

The tools were built for a real clinic workflow and replace hours of manual clicking per week.

> **Privacy notice.** The programs process protected health information (names, dates of birth, SSN fragments). The repository contains **code only**. Tickets, logs, indexes and local settings are excluded by `.gitignore` — never commit them.

---

## How it works

```
NextGen ──print──▶ PDF24 printer ──▶ pdf\inbox
                                        │
                     PDF Tickets
                       1. Saving  ─▶ pdf\<DOCTOR>\docN.pdf  +  pdf\pdf_all\<DOCTOR>_docN.pdf
                       2. Check   ─▶ report of missing / duplicate tickets
                       3. OCR     ─▶ pdf\pdf_text  (PDFs with an invisible text layer)
                                        │
                     AUTO-WORK
                       for each ticket: read name + DOB ─▶ search CarePortal by DOB
                       ─▶ open matching patients ─▶ save records to
                       Desktop\CAREPORTAL <Mon>-<Fri>\<DOCTOR>\<DOCTOR> <MMDDYYYY>
                                        │
                     Reconciliation ─▶ records of unknown people, records in the
                                       wrong folder, tickets without records
```

## Programs

| Program | Executable | What it does |
|---|---|---|
| **PDF Tickets** | `PDFTickets.exe` | One window with tabs: **Saving** (sorts printed tickets from the inbox into the doctor's folder with running numbers, removes reprinted duplicates and blank pages), **Check** (finds lost tickets by SEQ NO gaps and print pauses, tells which `Fee Tickets N of M` to reprint), **OCR** (adds an invisible text layer to the ticket header using Windows OCR in parallel processes, with Tesseract as a fallback), **CarePortal reconciliation**, **Cleanup** (moves everything to the Recycle Bin before a new week). |
| **AUTO-WORK** | `AutoWork.exe` | Screen automation of the portal: for each ticket it searches the patient by date of birth, picks the matching names in the results with OCR + fuzzy matching, opens each patient, checks for the red-dot marker, saves the record and moves the file into the right doctor/day folder. Includes a calibration wizard, adjustable timings, F6/F9/F10 hotkeys, a page check that pauses the run if the site navigates away, and resume-from-last-ticket logging. |
| **Week Folders** | `WeekFolders.exe` | Creates `Desktop\CAREPORTAL <Mon>-<Fri>\<DOCTOR>\<DOCTOR> <MMDDYYYY>` folders for the week. |

### Notable techniques

- **Cell-by-cell header OCR.** The ticket header table is split into cells by its grid lines; each cell is recognized separately and the label is taken from the cell position (`HEADER_LAYOUT`), so neighbouring fields are never mixed up.
- **Field-aware corrections** for amounts, dates, times, ICD-10 codes and SSN (`###-##-NNNN`); long last names that run over the cell border are read across the line.
- **Multi-pass voting OCR** for dates (per-digit majority vote over several image preprocessings and Tesseract configs) and confidence-weighted fuzzy grouping for names.
- **HSV color filtering** to read blue patient names from the portal's search results.
- **Staging-folder saving**: files are saved into an empty staging folder first, so Windows never asks “replace?”, and then moved into place.
- **Nothing is deleted permanently** — every removal goes through the Windows Recycle Bin.

## Installation (release)

1. Download `BillingAutomation-<version>-win64.zip` from the **Releases** page and unpack it into any folder.
2. Copy `doctors.example.txt` to `doctors.txt` and list the rendering physicians' last names (one per line, upper case).
3. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) into `C:\Program Files\Tesseract-OCR` and make sure a Windows OCR language pack is installed (Polish, English or Russian).
4. Configure your PDF printer (e.g. **PDF24**) to auto-save into `<folder>\pdf\inbox`.

All three programs keep their data next to the executables:

```
<folder>/
├── PDFTickets.exe, AutoWork.exe, WeekFolders.exe
├── doctors.txt
├── pdf/                 tickets: inbox, <DOCTOR>, pdf_all, pdf_text, blank
└── data/
    ├── auto_work/       settings, calibration_data.json, logs, done_pdfs.txt
    └── pdf_tickets/     settings, number log, ticket index, logs
```

> The executables are not code-signed. Windows SmartScreen or Smart App Control may block them on first start; allow them in Windows Security or run the programs from source.

## Weekly workflow

1. **Week Folders** — enter Monday's date (`MMDDYYYY`).
2. **PDF Tickets → Saving** — set the doctor folders to `<folder>\pdf\<DOCTOR>` (once), choose the doctor, press **Start (F9)** and print the doctor's fee tickets from NextGen. Repeat for every doctor.
3. **PDF Tickets → Check** — enter the ticket count from NextGen to verify that nothing was lost.
4. **PDF Tickets → OCR** — press **Start**; text PDFs appear in `pdf\pdf_text`.
5. **AUTO-WORK** — run **Calibration (Ctrl+K)** once (the wizard asks you to point at the website elements; `examples/calibration_data.example.json` shows the file format). Then choose "From PDF files" and press **Start (F6)**. **F9** pauses/resumes, **F10** opens the pause menu. The run resumes from the last finished ticket.
6. Check the **reconciliation** report at the end of the run (also on the **CarePortal reconciliation** tab).
7. **PDF Tickets → Cleanup** before the next week.

## Running from source

```bash
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Start the programs by double-clicking `scripts\pdf_tickets.pyw`, `scripts\auto_work.pyw` or `scripts\week_folders.pyw` (`.pyw` opens no console). When run from source, the repository root plays the role of the release folder (`pdf\`, `data\`, `doctors.txt`).

Tests and static checks:

```bash
.venv\Scripts\python -m pytest
```

```bash
.venv\Scripts\python -m pyflakes src tests
```

## Building the executables

```bash
powershell -ExecutionPolicy Bypass -File build.ps1
```

The script installs the dependencies into `.venv`, runs pyflakes and the tests, builds `PDFTickets.exe`, `AutoWork.exe` and `WeekFolders.exe` with PyInstaller (one file each, no console) into `dist\`, and packs `release\BillingAutomation-<version>-win64.zip` for a GitHub release. The version is taken from `src/billing_automation/__init__.py`.

## Project layout

```
billing_automation_script/
├── src/billing_automation/
│   ├── paths.py, doctors.py, week_folders.py, recycle_bin.py, tesseract.py   # shared
│   ├── folder_creator.py              # Week Folders (GUI)
│   ├── pdf_tickets/                   # PDF Tickets
│   │   ├── config.py, storage.py      # constants, settings, numbering, ticket index
│   │   ├── windows_ocr.py             # Windows.Media.Ocr wrapper
│   │   ├── text_fixes.py, header.py   # OCR corrections, cell-by-cell header reading
│   │   ├── ticket.py, text_layer.py   # ticket fields and keys, invisible text layer
│   │   ├── analysis.py, reconcile.py  # missing tickets, reconciliation report
│   │   ├── workers.py, cleanup.py     # inbox watcher, OCR process pool
│   │   ├── app.py                     # entry point
│   │   └── gui/                       # main window and one module per tab
│   ├── auto_work/                     # AUTO-WORK
│   │   ├── state.py, applog.py        # pause/queues shared by threads, log files
│   │   ├── settings.py, calibration.py
│   │   ├── screen_ocr.py, name_matching.py, screen_checks.py
│   │   ├── save_dialog.py, portal.py  # "Save As" handling, website actions
│   │   ├── pdf_source.py, runner.py   # ticket source, main loop
│   │   ├── gui.py                     # main window
│   │   └── app.py                     # entry point
│   └── resources/ticket_words.txt     # fee-ticket label vocabulary (override: ticket_words.txt in the root)
├── scripts/                           # .pyw launchers (also the PyInstaller entry points)
├── tests/                             # pytest
├── examples/calibration_data.example.json
├── build.ps1, pyproject.toml, requirements.txt, requirements-dev.txt
└── doctors.example.txt
```

## Limitations

- Built for one specific environment: the portal page layout, the NextGen fee ticket form and the screen coordinates are calibrated for a particular setup.
- The save step relies on the standard Windows “Save As” dialog (`Alt+N` focuses the *File name* field).
- Screen automation needs the browser window to stay in place and unobstructed while AUTO-WORK runs.

## Disclaimer

This software is provided as is. Use it only on systems and data you are authorized to access and in compliance with your organization's privacy policies (e.g. HIPAA).
