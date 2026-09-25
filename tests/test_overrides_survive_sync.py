"""Calendar overrides (name/colour/hidden) survive repeated syncs (US-26, acceptance 7)."""
from calpi.data.event_store import EventStore
from calpi.data.models import Calendar


def test_upsert_keeps_overrides(tmp_path):
    store = EventStore(tmp_path / "t.sqlite3")
    store.upsert_calendar(Calendar("a:1", "Home", account_id="a", remote_color="#4f9dff"))
    store.set_calendar_overrides("a:1", user_name="Family", user_color="#3ecf8e", hidden=True)
    # the sync process re-upserts with new remote values
    store.upsert_calendar(Calendar("a:1", "Home2", account_id="a", remote_color="#ff6b6b"))
    store.upsert_calendar(Calendar("a:1", "Home3", account_id="a", remote_color="#ff6b6b"))
    c = store.get_calendar("a:1")
    assert (c.name, c.color, c.hidden) == ("Family", "#3ecf8e", True)
    assert c.remote_name == "Home3"
    store.set_calendar_overrides("a:1", user_name=None, user_color=None)
    c = store.get_calendar("a:1")
    assert (c.name, c.color) == ("Home3", "#ff6b6b")
