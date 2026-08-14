"""Feature — Snapshot Déterministe (D-030).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- capture INSTANTANÉE des 4 blocs (carnet, CVD par niveau, calendrier éco, alertes IA) depuis
  le ContextSchema courant → objet `Snapshot` ;
- DÉTERMINISTE : même schéma + mêmes id/ts → contenu identique (aucun LLM, aucun hasard) ;
- FAIL-CLOSED : bloc absent/périmé capturé tel quel (freshness ABSENT, value None) — jamais
  un carnet/CVD inventé (§3) ;
- écriture ASYNC NON-BLOQUANTE (JSON + Markdown) dans un dossier local — I/O offloadée
  (asyncio.to_thread), jamais le hot path (§7) ;
- OBSERVATION, jamais un ordre (§2.1).
"""
import asyncio
import json
import os
import time

from app import config
from app.meta import Freshness, MetaField
from app.schema import (ContextSchema, CvdLevel, CvdState, LiquiditySweep,
                        LiquiditySweepAlert)
from app.snapshot import (build_snapshot, capture_snapshot, list_snapshots,
                          read_snapshot, render_markdown, write_snapshot)


def _wired(now: float) -> ContextSchema:
    s = ContextSchema()
    s.s1_state.order_book = MetaField(
        value={"bids": [[5000.0, 40.0]], "asks": [[5000.5, 30.0]]},
        last_update_ts=now, source=config.MICROSTRUCTURE_SOURCE, freshness=Freshness.FRESH)
    s.s1_state.cvd_by_level = CvdState(
        levels=[CvdLevel(price=5000.0, delta=12.0, buy=20.0, sell=8.0)],
        total_delta=12.0, since_ts=now, reset_reason="NFP — emplois US")
    s.econ_calendar.events = MetaField(
        value=[{"ts": now + 300, "name": "NFP — emplois US", "tier": 1, "region": "US"}],
        last_update_ts=now, source="econ_feed", freshness=Freshness.FRESH)
    s.liquidity_sweep = LiquiditySweep(
        assessable=True, triggered=True, reason="sweep : WIDE_SPREAD",
        alert=LiquiditySweepAlert(ts=now, trigger="WIDE_SPREAD", direction="ASK_SWEEP",
                                  news_context="NFP — emplois US"))
    return s


def test_build_snapshot_captures_four_blocks_deterministically():
    now = 1000.0
    s = _wired(now)
    a = build_snapshot(s, "snap_x", now, "SONY", "OVERLAP_NY")
    b = build_snapshot(s, "snap_x", now, "SONY", "OVERLAP_NY")
    assert a.model_dump() == b.model_dump()                 # déterministe, bit-à-bit
    assert a.order_book["value"]["asks"][0][0] == 5000.5
    assert a.cvd_by_level["total_delta"] == 12.0
    assert a.econ_calendar["events"]["value"][0]["name"] == "NFP — emplois US"
    assert a.liquidity_sweep["alert"]["trigger"] == "WIDE_SPREAD"
    assert a.operator == "SONY" and a.session_marker == "OVERLAP_NY"


def test_snapshot_fail_closed_captures_absent_not_invented():
    snap = build_snapshot(ContextSchema(), "s", 1.0, "SONY", "HORS_SESSION")
    assert snap.order_book["freshness"] == "ABSENT" and snap.order_book["value"] is None
    assert snap.liquidity_sweep["triggered"] is False       # rien d'inventé
    assert snap.cvd_by_level["levels"] == []


def test_render_markdown_has_sections_and_is_honest_about_absent():
    md = render_markdown(build_snapshot(ContextSchema(), "s", 1.0, "YOUSSEF", "HORS_SESSION"))
    assert md.startswith("# Snapshot")
    for section in ("Carnet", "CVD", "Calendrier", "Alertes IA"):
        assert section in md, f"section manquante : {section}"
    assert "YOUSSEF" in md
    assert "PAS DE DONNÉES" in md                           # blocs absents signalés honnêtement


def test_render_markdown_renders_wired_values():
    md = render_markdown(build_snapshot(_wired(1000.0), "s", 1000.0, "SONY", "OVERLAP_NY"))
    assert "5000.5" in md                                   # meilleur ask
    assert "2.0 ticks" in md                                # spread (5000.5 − 5000.0)/0.25
    assert "NFP" in md and "WIDE_SPREAD" in md
    assert "SWEEP ACTIF" in md


def test_write_snapshot_writes_json_and_md(tmp_path):
    async def scenario():
        now = 1000.0
        snap = build_snapshot(_wired(now), "snap_w", now, "SONY", "OVERLAP_NY")
        res = await write_snapshot(snap, str(tmp_path))
        assert os.path.exists(res["json_path"]) and os.path.exists(res["md_path"])
        loaded = json.load(open(res["json_path"], encoding="utf-8"))
        assert loaded["snapshot_id"] == "snap_w"
        assert loaded["cvd_by_level"]["total_delta"] == 12.0
        assert "NFP" in open(res["md_path"], encoding="utf-8").read()
        assert res["snapshot_id"] == "snap_w"
    asyncio.run(scenario())


def test_capture_snapshot_no_collision_same_millisecond(tmp_path):
    """/devil (D-031) : deux fills capturés au MÊME horodatage (rafale) → deux fichiers
    DISTINCTS, aucun écrasement (id désambiguïsé par compteur monotone)."""
    async def scenario():
        engine = type("E", (), {"schema": _wired(1000.0)})()
        now = 1000.0
        r1 = await capture_snapshot(engine, now, directory=str(tmp_path))
        r2 = await capture_snapshot(engine, now, directory=str(tmp_path))
        assert r1["snapshot_id"] != r2["snapshot_id"]        # pas de collision
        assert os.path.exists(r1["json_path"]) and os.path.exists(r2["json_path"])
        assert r1["json_path"] != r2["json_path"]            # deux fichiers, rien d'écrasé
    asyncio.run(scenario())


# ---------- Journal de Bord — index + lecture (D-032) ----------

def _write(directory, snap_id, ts):
    import asyncio as _a
    snap = build_snapshot(_wired(ts), snap_id, ts, "SONY", "OVERLAP_NY")
    _a.run(write_snapshot(snap, directory))


def test_list_snapshots_indexes_newest_first(tmp_path):
    _write(str(tmp_path), "snap_1000000_sony", 1000.0)
    _write(str(tmp_path), "snap_3000000_sony", 3000.0)
    _write(str(tmp_path), "snap_2000000_sony", 2000.0)
    idx = list_snapshots(str(tmp_path))
    assert [e["snapshot_id"] for e in idx] == \
        ["snap_3000000_sony", "snap_2000000_sony", "snap_1000000_sony"]  # récent → ancien
    assert idx[0]["created_ts"] == 3000.0 and idx[0]["operator"] == "SONY"
    assert idx[0]["has_json"] and idx[0]["has_md"] and idx[0]["bytes"] > 0


def test_list_snapshots_absent_dir_is_empty_not_error(tmp_path):
    assert list_snapshots(str(tmp_path / "n_existe_pas")) == []   # fail-closed, pas d'erreur


def test_list_snapshots_respects_limit(tmp_path):
    for i in range(1, 6):
        _write(str(tmp_path), f"snap_{i}000000_sony", float(i * 1000))
    idx = list_snapshots(str(tmp_path), limit=2)
    assert len(idx) == 2
    assert [e["snapshot_id"] for e in idx] == ["snap_5000000_sony", "snap_4000000_sony"]


def test_read_snapshot_returns_json_and_markdown(tmp_path):
    _write(str(tmp_path), "snap_1000000_sony", 1000.0)
    r = read_snapshot(str(tmp_path), "snap_1000000_sony")
    assert r is not None
    assert r["json"]["snapshot_id"] == "snap_1000000_sony"
    assert r["json"]["cvd_by_level"]["total_delta"] == 12.0
    assert r["markdown"].startswith("# Snapshot")
    assert "NFP" in r["markdown"]


def test_read_snapshot_rejects_path_traversal_and_bad_ids(tmp_path):
    # jamais lire hors du dossier snapshots (§ sécurité / fail-closed)
    assert read_snapshot(str(tmp_path), "../../etc/passwd") is None
    assert read_snapshot(str(tmp_path), "snap_1_sony/../secret") is None
    assert read_snapshot(str(tmp_path), "not_a_snapshot") is None
    assert read_snapshot(str(tmp_path), "snap_1_sony") is None    # bien formé mais absent


def test_write_snapshot_is_non_blocking(tmp_path, monkeypatch):
    """L'I/O fichier est OFFLOADÉE (to_thread) : une écriture lente bloque un THREAD, jamais
    la boucle d'événements (§7)."""
    async def scenario():
        import app.snapshot as snap_mod

        def slow_write(directory, snapshot_id, payload, md):
            time.sleep(0.3)                                 # bloque un THREAD
            return os.path.join(directory, "x.json"), os.path.join(directory, "x.md")

        monkeypatch.setattr(snap_mod, "_write_files", slow_write)
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(40):
                await asyncio.sleep(0.01)
                ticks += 1

        snap = build_snapshot(_wired(1000.0), "s", 1000.0, "SONY", "OVERLAP_NY")
        await asyncio.gather(write_snapshot(snap, str(tmp_path)), ticker())
        assert ticks >= 30, f"boucle bloquée par l'écriture (ticks={ticks})"
    asyncio.run(scenario())
