"""PDF Tickets: ticket keys, missing ticket analysis and reconciliation helpers."""
from billing_automation.pdf_tickets import reconcile
from billing_automation.pdf_tickets.analysis import analyze
from billing_automation.pdf_tickets.ticket import ticket_key


def _ticket(seq, name, time="9:00AM", date="10/13/26", dob="01/01/1980"):
    return {"seq": seq, "date": date, "time": time, "name": name, "dob": dob, "created": date}


def test_ticket_key():
    assert ticket_key(_ticket(5, "Doe  John")) == "10/13/26|5|01/01/1980|DOE JOHN"
    assert ticket_key({"blank": True}) is None
    assert ticket_key(_ticket(5, "?")) is None


def test_ticket_key_without_seq_uses_creation_date_and_time():
    t = _ticket(None, "DOE JOHN")
    t["date"] = "?"
    assert ticket_key(t) == "10/13/26|noseq|9:00AM|01/01/1980|DOE JOHN"


def test_all_tickets_present():
    tickets = [_ticket(1, "A"), _ticket(2, "B"), _ticket(3, "C")]
    report = analyze(["a", "b", "c"], tickets, [0, 8, 16], 3)
    assert "The count matches: all tickets are in place." in report


def test_missing_ticket_between_files():
    tickets = [_ticket(1, "A"), _ticket(2, "B"), _ticket(4, "D"), _ticket(5, "E")]
    # a print pause of 18 s instead of the usual 8 s before file 3 (about one lost ticket)
    report = analyze(["a", "b", "d", "e"], tickets, [0, 8, 26, 34], 5)
    assert "MISSING 1 ticket(s)." in report
    assert "[CERTAIN] Fee Tickets 3 of 5" in report
    assert "missing SEQ 3" in report


def test_reprinted_ticket_is_counted_once():
    tickets = [_ticket(1, "A"), _ticket(1, "A"), _ticket(2, "B")]
    report = analyze(["a", "a2", "b"], tickets, [0, 8, 16], 2)
    assert "Duplicates of the same ticket" in report
    assert "The count matches" in report


def test_name_score_ignores_order_and_commas():
    assert reconcile._name_score("DOE, JOHN MICHAE", "DOE JOHN MICHAEL") >= 90
    assert reconcile._name_score("DOE, JOHN", "SMITH, ANNA") < 70


def test_doctor_from_physician(monkeypatch):
    monkeypatch.setattr(reconcile, "SAVE_DOCTORS", ["SMITH", "JONES"])
    assert reconcile._doctor_of("Smi h, John") == "SMITH"
    assert reconcile._doctor_of("", "jones") == "JONES"
    assert reconcile._doctor_of("Xyz, Q", "nobody") == ""
