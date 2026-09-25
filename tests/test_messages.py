import re
from datetime import datetime, timezone

import pytest

from calpi.data import messages as m
from calpi.data.sync_status import AccountStatus
from calpi.sync.errors import ErrorCode

REQUIRED = [c.value for c in ErrorCode] + [
    "AUTH_REVOKED", "CLOCK_UNSYNCED", "NO_ACCOUNTS", "SAFE_MODE", "DB_RESET", "CREDENTIALS_UNREADABLE",
    "POWER_UNDERVOLTAGE", "POWER_THROTTLED_PAST", "TEMP_HIGH", "DISK_LOW", "WIFI_WRONG_PASSWORD",
    "WIFI_NOT_REACHABLE", "WIFI_UNSUPPORTED", "WIFI_FAILED", "OFFLINE"]
JARGON = re.compile(r"HTTP|PROPFIND|DNS|TLS|SSL|\b401\b|\b403\b|\b500\b|exception|errno|NetworkManager|CalDAV",
                    re.I)
SAMPLE = dict(account="me@icloud.com", ssid="HomeWiFi", last_update="Today 14:05")


def test_every_code_in_catalogue_and_every_context_works():
    for code in REQUIRED:
        assert code in m.CATALOGUE, code
        e = m.CATALOGUE[code]
        assert e.severity in ("info", "warning", "error") and e.detail and e.banner_title
        for ctx in m.CONTEXTS:
            msg = m.describe(code, context=ctx, **SAMPLE)
            assert msg.title, (code, ctx)
        if e.fix_label:
            assert e.fix_target


def test_error_severity_has_header_text():
    for code, e in m.CATALOGUE.items():
        if e.severity == "error":
            assert e.header, code


def test_length_limits():
    for code in m.CATALOGUE:
        assert len(m.CATALOGUE[code].header or "") <= 32, code
        b = m.describe(code, context="banner", **SAMPLE)
        assert len(b.title) <= 60 and len(b.detail) <= 160, (code, len(b.title), len(b.detail))
        assert len(m.describe(code, context="toast", **SAMPLE).title) <= 60, code


def test_no_jargon_and_no_leftover_placeholders():
    for code in m.CATALOGUE:
        for ctx in m.CONTEXTS:
            msg = m.describe(code, context=ctx, **SAMPLE)
            for text in (msg.title, msg.detail or ""):
                assert not JARGON.search(text), (code, ctx, text)
                assert "{" not in text and "}" not in text, (code, ctx, text)
                assert "!" not in text


def test_provider_names_substituted():
    assert "Fastmail" in m.describe("AUTH_REVOKED", context="banner", provider="Fastmail").title
    assert "iCloud" not in m.describe("SERVER_ERROR", context="status", provider="Fastmail").detail


def test_form_texts_provider_specific_and_unknown_code():
    assert m.describe("AUTH_FAILED", context="form").title.startswith("Apple didn't accept")
    assert "app password" in m.describe("AUTH_FAILED", context="form", provider="CalDAV",
                                        provider_key="caldav").title
    assert m.describe("NOPE", context="toast").title == "Couldn't update"


def test_revoked_text_and_fix():
    d = m.describe("AUTH_REVOKED", context="status", account="me@icloud.com")
    assert "me@icloud.com" in d.detail and "app-specific password" in d.detail
    assert d.fix_target == "update_password" and d.fix_label == "Update password"
    assert d.fix_section == "update_password"


def _st(code, ok):
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return AccountStatus("a", t, t if ok else None, code, None, t, 1)


def test_classify_account_problem():
    assert m.classify_account_problem(_st("AUTH_FAILED", True)) == "AUTH_REVOKED"
    assert m.classify_account_problem(_st("AUTH_FAILED", False)) == "AUTH_FAILED"
    assert m.classify_account_problem(_st("TIMEOUT", True)) == "TIMEOUT"
    assert m.classify_account_problem(_st(None, True)) is None


def test_toast_for_result():
    r = lambda *codes: {"accounts": [{"account_id": f"a{i}", "error": c} for i, c in enumerate(codes)]}
    assert m.toast_for_result(r("NETWORK_DOWN")) == "Couldn't update: offline"
    assert m.toast_for_result(r("AUTH_FAILED")) == "Couldn't update: sign-in problem"
    assert m.toast_for_result(r("TIMEOUT"), {"a0": "iCloud"}) == "Couldn't update: iCloud not responding"
    assert m.toast_for_result(r("PARSE_ERROR")) == "Couldn't update"


def test_review_prints_all_codes():
    text = m.review_markdown()
    assert all(f"## {c}" in text for c in REQUIRED)
