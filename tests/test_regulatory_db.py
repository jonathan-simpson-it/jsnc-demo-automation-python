"""Tests for the Regulatory Radar feed repository.

Sandbox note: requires the project venv/CI (pytest).
"""

from pathlib import Path

import pytest

from src.core import database as db


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield tmp_path / "test.db"


def _seed(isolated_db):
    return db.upsert_regulatory_item(
        source_key="sfc_circulars",
        external_id="circ-2026-001",
        regulator="SFC",
        kind="circular",
        title="Licensing of virtual asset platforms",
        url="https://www.sfc.hk/en/circ-2026-001",
        issued_at="2026-01-15",
    )


def test_upsert_is_idempotent(isolated_db):
    first = _seed(isolated_db)
    second = db.upsert_regulatory_item(
        source_key="sfc_circulars",
        external_id="circ-2026-001",
        regulator="SFC",
        kind="circular",
        title="Licensing of virtual asset platforms",
        url="https://www.sfc.hk/en/circ-2026-001",
        issued_at="2026-01-15",
    )
    assert first["id"] == second["id"]
    assert db.list_regulatory_items() == [second]


def test_list_and_get(isolated_db):
    item = _seed(isolated_db)
    assert db.get_regulatory_item("sfc_circulars", "circ-2026-001")["id"] == item["id"]
    assert db.get_regulatory_item("sfc_circulars", "missing") is None
    assert db.list_regulatory_items()[0]["regulator"] == "SFC"


def test_status_update(isolated_db):
    item = _seed(isolated_db)
    assert item["status"] == "pending"
    assert db.update_regulatory_item_status(item["id"], "ingested", chunks=42,
                                            summary="Impact summary.") is True
    fetched = db.get_regulatory_item("sfc_circulars", "circ-2026-001")
    assert fetched["status"] == "ingested"
    assert fetched["chunks"] == 42
    assert fetched["summary"] == "Impact summary."
    assert db.update_regulatory_item_status(99999, "error") is False
