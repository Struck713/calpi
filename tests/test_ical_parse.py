import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from calpi.sync.ical_parse import parse_resources

FX = Path(__file__).parent / "fixtures" / "ics"
BER = ZoneInfo("Europe/Berlin")
WINDOW = (datetime(2026, 3, 1, tzinfo=BER).astimezone(timezone.utc),
          datetime(2026, 5, 1, tzinfo=BER).astimezone(timezone.utc))


def U(*a):
    return datetime(*a, tzinfo=timezone.utc)


def parse(*names, window=WINDOW, cap=5000):
    return parse_resources([(FX / f"{n}.ics").read_bytes() for n in names], "cal", window, BER, cap)


def summarize(evs):
    return [(e.summary, e.start, e.end) for e in sorted(evs, key=lambda e: (e.start.isoformat(), e.summary))]


def test_01_tzid():
    evs, _ = parse("01_tzid")
    assert summarize(evs) == [("tzid", U(2026, 3, 10, 13), U(2026, 3, 10, 14))]
    assert evs[0].tzid == "Europe/Berlin" and not evs[0].all_day and evs[0].recurrence_id == ""


def test_02_utc():
    evs, _ = parse("02_utc")
    assert summarize(evs) == [("utc", U(2026, 3, 10, 13), U(2026, 3, 10, 14))]


def test_03_floating_uses_display_zone():
    evs, st = parse("03_floating")
    assert summarize(evs) == [("floating", U(2026, 3, 10, 13), U(2026, 3, 10, 14))]
    assert st.unknown_tz == 0


def test_04_05_06_all_day():
    evs, _ = parse("04_allday_1", "05_allday_3", "06_allday_noend")
    got = {e.summary: (e.all_day, e.start, e.end) for e in evs}
    assert got == {"allday1": (True, date(2026, 3, 10), date(2026, 3, 11)),
                   "allday3": (True, date(2026, 3, 10), date(2026, 3, 13)),
                   "allday-noend": (True, date(2026, 3, 10), date(2026, 3, 11))}
    assert not any(isinstance(e.start, datetime) for e in evs)


def test_07_duration():
    evs, _ = parse("07_duration")
    assert summarize(evs) == [("duration", U(2026, 3, 10, 10), U(2026, 3, 10, 11, 30))]


def test_08_zero_length():
    evs, _ = parse("08_zero")
    assert evs[0].start == evs[0].end == U(2026, 3, 10, 10)


def test_09_weekly_keeps_local_time_across_dst():
    evs, _ = parse("09_dst")
    starts = sorted(e.start for e in evs)
    assert starts == [U(2026, 3, 16, 8), U(2026, 3, 23, 8), U(2026, 3, 30, 7), U(2026, 4, 6, 7)]
    assert {e.start.astimezone(BER).hour for e in evs} == {9}
    assert all(e.recurrence_id == e.start.isoformat() for e in evs)


def test_10_exdate():
    evs, _ = parse("10_exdate")
    assert [e.start for e in sorted(evs, key=lambda e: e.start)] == [
        U(2026, 3, 2, 8), U(2026, 3, 16, 8), U(2026, 3, 23, 8)]


def test_11_moved_instance():
    evs, _ = parse("11_moved")
    assert summarize(evs) == [("series", U(2026, 3, 2, 8), U(2026, 3, 2, 9)),
                              ("moved", U(2026, 3, 11, 14, 30), U(2026, 3, 11, 15, 30)),
                              ("series", U(2026, 3, 16, 8), U(2026, 3, 16, 9))]
    moved = [e for e in evs if e.summary == "moved"][0]
    assert moved.recurrence_id == "2026-03-09T08:00:00+00:00"       # RECURRENCE-ID, not the new start


def test_12_moved_in_from_outside_window():
    evs, _ = parse("12_moved_in")
    assert "moved-in" in [e.summary for e in evs]
    assert [e.start for e in evs if e.summary == "moved-in"] == [U(2026, 3, 15, 10)]


def test_13_moved_out_of_window():
    evs, _ = parse("13_moved_out")
    assert [e.start for e in sorted(evs, key=lambda e: e.start)] == [U(2026, 4, 1, 10), U(2026, 4, 15, 10)]
    assert "moved-out" not in [e.summary for e in evs]


def test_14_cancelled_override():
    evs, st = parse("14_cancel_override")
    assert [e.start for e in sorted(evs, key=lambda e: e.start)] == [U(2026, 4, 1, 10), U(2026, 4, 3, 10)]
    assert st.cancelled == 1


def test_15_cancelled_event():
    evs, st = parse("15_cancelled")
    assert evs == [] and st.cancelled == 1


def test_16_tentative():
    evs, _ = parse("16_tentative")
    assert evs[0].status == "TENTATIVE"


def test_17_daily_forever_only_window():
    evs, _ = parse("17_daily_forever")
    assert len(evs) == 61 and all(e.recurrence_id for e in evs)
    assert min(e.start for e in evs) == U(2026, 3, 1, 8) and max(e.start for e in evs) == U(2026, 4, 30, 8)


def test_18_count():
    assert len(parse("18_count")[0]) == 5


def test_19_until():
    evs, _ = parse("19_until")
    assert len(evs) == 7 and max(e.start for e in evs) == U(2026, 3, 7, 8)


def test_20_rdate():
    evs, _ = parse("20_rdate")
    assert [e.start for e in sorted(evs, key=lambda e: e.start)] == [
        U(2026, 3, 2, 8), U(2026, 3, 20, 8), U(2026, 3, 21, 8)]
    assert all(e.recurrence_id for e in evs)


def test_21_custom_vtimezone():
    evs, st = parse("21_custom_vtimezone")
    assert evs[0].start == U(2026, 4, 1, 7)          # 09:00 at +02:00 from the VTIMEZONE rules
    assert st.unknown_tz == 0


def test_22_unknown_tzid_is_floating():
    evs, st = parse("22_unknown_tzid")
    assert evs[0].start == U(2026, 3, 10, 13)         # 14:00 Berlin
    assert st.unknown_tz == 1


def test_23_windows_tzid_installed_library_maps_it():
    evs, _ = parse("23_windows_tzid")
    # icalendar 6 maps Windows names; either mapping or floating in Berlin gives the same UTC here
    assert evs[0].start == U(2026, 3, 10, 13)


def test_24_monthly_all_day_never_shifts():
    evs, _ = parse("24_monthly_allday")
    assert [(e.start, e.end) for e in sorted(evs, key=lambda e: e.start)] == [
        (date(2026, 3, 15), date(2026, 3, 16)), (date(2026, 4, 15), date(2026, 4, 16))]


def test_25_crosses_midnight():
    evs, _ = parse("25_midnight")
    e = evs[0]
    assert e.start.astimezone(BER).date() != e.end.astimezone(BER).date()
    assert e.end - e.start == timedelta(hours=2)


def test_26_malformed_alongside_good(caplog):
    with caplog.at_level(logging.WARNING):
        evs, st = parse("26_malformed", "02_utc")
    assert [e.summary for e in evs] == ["utc"]
    assert st.parse_errors == 1 and st.resources == 2
    assert "bad1" in caplog.text


def test_27_two_uids():
    evs, _ = parse("27_two_uids")
    assert sorted(e.uid for e in evs) == ["c27a", "c27b"]


def test_28_long_summary_truncated():
    evs, _ = parse("28_long_summary")
    assert len(evs[0].summary) == 500


def test_29_outside_window():
    assert parse("29_outside")[0] == []


def test_30_mixed_date_datetime_is_all_day():
    evs, _ = parse("30_mixed")
    e = evs[0]
    assert e.all_day and e.start == date(2026, 3, 10) and e.end == date(2026, 3, 12)


def test_all_day_end_not_after_start_is_one_day():
    evs, _ = parse("31_allday_bad_end")
    assert (evs[0].start, evs[0].end) == (date(2026, 3, 10), date(2026, 3, 11))


def test_text_unescaped():
    e = parse("32_escaped")[0][0]
    assert e.summary == "Lunch, with ; friends" and e.location == "Cafe\nRoom 2"


def test_cap(caplog):
    with caplog.at_level(logging.WARNING):
        evs, st = parse("17_daily_forever", cap=10)
    assert len(evs) == 10 and st.capped and "cap" in caplog.text


def test_window_edges_are_exact():
    # all-day event on the first day after the window is excluded; on the last day included
    ics = (b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:a\nSUMMARY:in\n"
           b"DTSTART;VALUE=DATE:20260430\nEND:VEVENT\nBEGIN:VEVENT\nUID:b\nSUMMARY:out\n"
           b"DTSTART;VALUE=DATE:20260501\nEND:VEVENT\nEND:VCALENDAR\n")
    evs, _ = parse_resources([ics], "c", WINDOW, BER)
    assert [e.summary for e in evs] == ["in"]
