"""Point-in-time index reconstruction.

Skipped when data/sp500_history.json has not been generated, so CI stays
hermetic; run scripts/build_index_history.py to populate it.
"""
import pytest
from fastapi.testclient import TestClient

from data import index_history, members_on, survivorship_gap
from main import app

pytestmark = pytest.mark.skipif(
    not index_history(), reason="run scripts/build_index_history.py first"
)

client = TestClient(app)


def test_changes_are_sorted_and_dated():
    changes = index_history()["changes"]
    dates = [c["date"] for c in changes]
    assert dates == sorted(dates)
    assert all(c["added"] or c["removed"] for c in changes)


def test_current_and_departed_never_overlap():
    hist = index_history()
    assert not set(hist["current"]) & set(hist["departed"])


def test_membership_shrinks_back_toward_today_as_date_advances():
    # Undoing fewer changes should leave a membership closer to today's list.
    now = set(index_history()["current"])
    gap_2010 = len(set(members_on("2010-01-01")) - now)
    gap_2020 = len(set(members_on("2020-01-01")) - now)
    assert gap_2010 > gap_2020 > 0


def test_index_size_stays_plausible():
    # The S&P 500 holds ~500 names; dual share classes push the ticker count a
    # little above that. Anything far outside this band means the replay drifted.
    for as_of in ("2010-01-01", "2015-01-01", "2020-01-01", "2025-01-01"):
        assert 480 <= len(members_on(as_of)) <= 520, as_of


def test_known_departed_companies_are_recovered():
    # Companies that left the index and are absent from today's list.
    members_2010 = set(members_on("2010-01-01"))
    assert "LEH" in set(index_history()["departed"])   # Lehman, bankrupt 2008
    assert "SHLD" in members_2010                       # Sears, in the index in 2010
    assert "SHLD" not in set(index_history()["current"])


def test_survivorship_gap_is_material():
    gap = survivorship_gap("2010-01-01")
    assert gap["departed"] > 100
    assert 20 < gap["departed_pct"] < 70


def test_endpoint_returns_membership_and_gap():
    body = client.get("/api/index-history?as_of=2010-01-01").json()
    assert body["changes"] > 300
    assert body["survivorship"]["departed"] > 100
    assert len(body["members"]) == body["survivorship"]["members_then"]


def test_endpoint_rejects_malformed_date():
    assert client.get("/api/index-history?as_of=not-a-date").status_code == 422
