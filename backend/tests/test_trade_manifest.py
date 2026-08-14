"""Tests du TradeManifest et de l'émetteur semi-automatique LSR (D-045)."""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.trade_manifest import (
    DEFAULT_TTL_MS,
    EntryPlan,
    RiskPlan,
    TradeManifest,
    manifest_from_lsr_plan,
)


def _plan(**over) -> dict:
    """Plan LSR APPROVED cohérent (LONG MES) — base des variations."""
    exec_plan: object = {"entryType": "LIMIT", "entryPrice": 5000.0, "stopLoss": 4998.0,
                         "takeProfit": 5004.0, "contracts": 2}
    patch = over.pop("executionPlan", {})
    if isinstance(patch, dict):
        exec_plan.update(patch)          # type: ignore[union-attr]  (surcharge champ à champ)
    else:
        exec_plan = patch                # remplacement du bloc entier (cas mal formé)
    plan = {"status": "APPROVED", "instrument": "MES", "direction": "LONG",
            "reason": "LSR — sweep bas réintégré, B1-B4 verts", "executionPlan": exec_plan}
    plan.update(over)
    return plan


def _manifest(**over) -> TradeManifest:
    base = {"id": "m1", "timestamp": 1_700_000_000_000, "instrument": "MES", "direction": "BUY",
            "reason": "test", "entry": EntryPlan(type="LIMIT", price=5000.0),
            "risk": RiskPlan(stopLoss=4998.0, takeProfit=5004.0, positionSize=2)}
    base.update(over)
    return TradeManifest(**base)


# --- Modèle : contrat de fil ---------------------------------------------------------------

def test_ttl_par_defaut_est_3000_ms():
    assert _manifest().timeToLiveMs == 3000
    assert DEFAULT_TTL_MS == 3000


def test_serialisation_conserve_exactement_les_cles_du_contrat():
    d = _manifest().model_dump()
    assert set(d) == {"id", "timestamp", "instrument", "direction", "reason", "entry", "risk",
                      "timeToLiveMs"}
    assert set(d["entry"]) == {"type", "price"}
    assert set(d["risk"]) == {"stopLoss", "takeProfit", "positionSize"}


def test_direction_hors_contrat_rejetee():
    with pytest.raises(ValidationError):
        _manifest(direction="ACHAT")


def test_type_d_entree_hors_contrat_rejete():
    with pytest.raises(ValidationError):
        EntryPlan(type="STOP", price=5000.0)


def test_valeurs_non_finies_rejetees_par_le_modele():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            EntryPlan(type="LIMIT", price=bad)
        with pytest.raises(ValidationError):
            RiskPlan(stopLoss=bad, takeProfit=5004.0, positionSize=2)


def test_taille_de_position_non_strictement_positive_rejetee():
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            RiskPlan(stopLoss=4998.0, takeProfit=5004.0, positionSize=bad)


def test_ttl_non_strictement_positif_rejete():
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            _manifest(timeToLiveMs=bad)


# --- Péremption : horloge INJECTÉE, jamais lue ---------------------------------------------

def test_peremption_deterministe_sur_horloge_injectee():
    m = _manifest(timestamp=1_000_000, timeToLiveMs=3000)
    assert m.expires_at_ms == 1_003_000
    assert not m.is_expired(1_000_000)          # à l'émission
    assert not m.is_expired(1_002_999)          # dernière ms utile
    assert m.is_expired(1_003_000)              # borne INCLUSE = périmé (fail-closed)
    assert m.is_expired(1_009_999)


def test_temps_restant_borne_a_zero_jamais_negatif():
    m = _manifest(timestamp=1_000_000, timeToLiveMs=3000)
    assert m.remaining_ms(1_000_000) == 3000
    assert m.remaining_ms(1_001_500) == 1500
    assert m.remaining_ms(1_003_000) == 0
    assert m.remaining_ms(9_999_999) == 0       # jamais un compte à rebours négatif


def test_horloge_non_finie_est_traitee_comme_perimee():
    m = _manifest(timestamp=1_000_000, timeToLiveMs=3000)
    for bad in (math.nan, math.inf, -math.inf):
        assert m.is_expired(bad) is True        # doute sur l'horloge → fail-closed
        assert m.remaining_ms(bad) == 0


# --- Émetteur : ne relaie QUE ce que LSR a validé -------------------------------------------

def test_plan_approuve_produit_un_manifeste_mappe():
    m = manifest_from_lsr_plan(_plan(), now_ms=1_700_000_000_000)
    assert m is not None
    assert m.instrument == "MES" and m.direction == "BUY"
    assert m.entry.type == "LIMIT" and m.entry.price == 5000.0
    assert m.risk.stopLoss == 4998.0 and m.risk.takeProfit == 5004.0 and m.risk.positionSize == 2
    assert m.timestamp == 1_700_000_000_000 and m.timeToLiveMs == DEFAULT_TTL_MS
    assert "LSR" in m.reason


def test_short_est_mappe_sur_sell():
    m = manifest_from_lsr_plan(
        _plan(direction="SHORT",
              executionPlan={"stopLoss": 5002.0, "takeProfit": 4996.0}), now_ms=1)
    assert m is not None and m.direction == "SELL"


@pytest.mark.parametrize("status", ["REJECTED", "BLOCKED", "INVALID_INPUT", "PENDING", "", None])
def test_plan_non_approuve_ne_produit_jamais_de_manifeste(status):
    assert manifest_from_lsr_plan(_plan(status=status), now_ms=1) is None


def test_direction_inconnue_fail_closed():
    assert manifest_from_lsr_plan(_plan(direction="FLAT"), now_ms=1) is None
    assert manifest_from_lsr_plan(_plan(direction=None), now_ms=1) is None


@pytest.mark.parametrize("field", ["entryPrice", "stopLoss", "takeProfit"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, None, "5000", True])
def test_prix_non_fini_ou_mal_type_fail_closed(field, bad):
    assert manifest_from_lsr_plan(_plan(executionPlan={field: bad}), now_ms=1) is None


@pytest.mark.parametrize("bad", [0, -2, 2.5, math.nan, None, "2", True])
def test_contrats_invalides_fail_closed(bad):
    assert manifest_from_lsr_plan(_plan(executionPlan={"contracts": bad}), now_ms=1) is None


def test_stop_du_mauvais_cote_fail_closed():
    # LONG : le stop DOIT être sous l'entrée, le TP au-dessus
    assert manifest_from_lsr_plan(_plan(executionPlan={"stopLoss": 5002.0}), now_ms=1) is None
    assert manifest_from_lsr_plan(_plan(executionPlan={"takeProfit": 4996.0}), now_ms=1) is None
    # SHORT : symétrique — un plan SHORT avec la géométrie LONG est incohérent
    assert manifest_from_lsr_plan(_plan(direction="SHORT"), now_ms=1) is None


def test_stop_ou_tp_colle_a_l_entree_fail_closed():
    assert manifest_from_lsr_plan(_plan(executionPlan={"stopLoss": 5000.0}), now_ms=1) is None
    assert manifest_from_lsr_plan(_plan(executionPlan={"takeProfit": 5000.0}), now_ms=1) is None


def test_plan_d_execution_absent_ou_mal_forme_fail_closed():
    assert manifest_from_lsr_plan({"status": "APPROVED", "direction": "LONG"}, now_ms=1) is None
    assert manifest_from_lsr_plan(_plan(executionPlan=None), now_ms=1) is None


@pytest.mark.parametrize("bad", [None, "APPROVED", 42, [], 3.14])
def test_plan_non_dict_ne_crashe_jamais(bad):
    assert manifest_from_lsr_plan(bad, now_ms=1) is None


def test_instrument_absent_fail_closed():
    assert manifest_from_lsr_plan(_plan(instrument=None), now_ms=1) is None
    assert manifest_from_lsr_plan(_plan(instrument=""), now_ms=1) is None


def test_horloge_non_finie_ne_produit_pas_de_manifeste():
    for bad in (math.nan, math.inf, None, "0"):
        assert manifest_from_lsr_plan(_plan(), now_ms=bad) is None


def test_ttl_surchargeable_mais_valide():
    m = manifest_from_lsr_plan(_plan(), now_ms=1, ttl_ms=8000)
    assert m is not None and m.timeToLiveMs == 8000
    assert manifest_from_lsr_plan(_plan(), now_ms=1, ttl_ms=0) is None
    assert manifest_from_lsr_plan(_plan(), now_ms=1, ttl_ms=-5) is None


def test_identifiant_deterministe_et_discriminant():
    a = manifest_from_lsr_plan(_plan(), now_ms=1_700_000_000_000)
    b = manifest_from_lsr_plan(_plan(), now_ms=1_700_000_000_000)
    c = manifest_from_lsr_plan(_plan(), now_ms=1_700_000_000_001)
    d = manifest_from_lsr_plan(_plan(executionPlan={"contracts": 3}), now_ms=1_700_000_000_000)
    assert a.id == b.id                          # rejeu du MÊME plan → même id (idempotence)
    assert a.id != c.id and a.id != d.id          # ts ou contenu différent → id différent


def test_raison_absente_reste_explicite_jamais_inventee():
    m = manifest_from_lsr_plan(_plan(reason=None), now_ms=1)
    assert m is not None and m.reason == "LSR — motif non fourni par le moteur"
