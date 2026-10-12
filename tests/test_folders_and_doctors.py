"""Week folders, the doctor list and the PDF source of AUTO-WORK."""
from datetime import date

from billing_automation.auto_work import pdf_source
from billing_automation.auto_work.settings import fmt_sec
from billing_automation.doctors import load_doctors
from billing_automation.week_folders import WEEK_FOLDER_RE, create_week_folders, week_folder_name


def test_week_folder_name():
    name = week_folder_name(date(2026, 8, 24))
    assert name == "CAREPORTAL 08242026-08282026"
    assert WEEK_FOLDER_RE.match(name)


def test_create_week_folders(tmp_path):
    lines = []
    path = create_week_folders(str(tmp_path), ["SMITH"], date(2026, 8, 24), lines.append)
    days = sorted(p.name for p in (tmp_path / "CAREPORTAL 08242026-08282026" / "SMITH").iterdir())
    assert days == [f"SMITH 08{d}2026" for d in range(24, 29)]
    assert path.endswith("CAREPORTAL 08242026-08282026")


def test_load_doctors(tmp_path):
    (tmp_path / "doctors.txt").write_text("# comment\nsmith\n\n Jones \n", encoding="utf-8")
    assert load_doctors(str(tmp_path)) == ["SMITH", "JONES"]


def test_load_doctors_falls_back_to_example(tmp_path):
    (tmp_path / "doctors.example.txt").write_text("BROWN\n", encoding="utf-8")
    assert load_doctors(str(tmp_path)) == ["BROWN"]
    assert load_doctors(str(tmp_path / "missing")) == []


def test_ticket_pdfs_are_sorted_by_number(tmp_path):
    for name in ("doc10.pdf", "SMITH_doc2.pdf", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    found = [(n, p.rsplit("\\", 1)[-1]) for n, p in pdf_source.list_ticket_pdfs(str(tmp_path))]
    assert found == [(2, "SMITH_doc2.pdf"), (10, "doc10.pdf")]
    assert pdf_source.pdf_doctor("SMITH_doc2.pdf") == "SMITH"


def test_doctor_from_physician(monkeypatch):
    monkeypatch.setattr(pdf_source, "SAVE_DOCTORS", ["SMITH", "JONES"])
    assert pdf_source.doctor_from_physician("Smi h, John") == "SMITH"
    assert pdf_source.doctor_from_physician("Q") == ""


def test_fmt_sec():
    assert fmt_sec(5.0) == "5"
    assert fmt_sec(6.5) == "6.5"
