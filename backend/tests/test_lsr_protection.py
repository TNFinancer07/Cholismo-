"""F6 / F7 / A5b et l'état d'exécution en projection (D-094).

Deux choses sont vérifiées ici, et la seconde compte autant que la première :
1. les règles refusent ce qu'elles doivent refuser ;
2. l'état n'est **stocké nulle part** — il se recalcule depuis le journal append-only (§2.5).
"""
from __future__ import annotations

import re
import time

import pytest

from app import config
from app.event_store import EventStore
from app.lsr_protection import (
    A5B_FIRST_TRADE_CONFLUENCE,
    F6_COOLDOWN_ACTIVE,
    F7_FOMO_TIMEOUT,
    LsrRuntimeState,
    a5b_first_trade_confluence,
    f6_cooldown,
    f7_fomo,
    f7_resubmit,
    project_runtime_state,
    session_date,
    ts_engine_source,
)

MINUTE_MS = 60_000.0


@pytest.fixture()
def store(tmp_path):
    return EventStore(str(tmp_path / "events.db"))


def _decision(store: EventStore, *, decision: str, ts: float) -> str:
    ev = store.append("DecisionEvent", {"operator": "SONY", "decision": decision}, ts=ts)
    return ev["id"]


def _outcome(store: EventStore, decision_id: str, outcome: str, ts: float) -> None:
    store.append("OutcomeEvent", {"decision_id": decision_id, "outcome": outcome}, ts=ts)


# ---------------------------------------------------------------- projection

def test_l_etat_se_RECALCULE_et_n_est_stocke_nulle_part(store):
    """Le cœur de §2.5. Deux projections successives sur le MÊME journal donnent le même état,
    et aucune écriture n'a lieu — la projection lit, elle ne persiste rien."""
    now = time.time()
    d = _decision(store, decision="GO", ts=now - 600)
    _outcome(store, d, "LOSS", ts=now - 300)

    avant = len(store.events())
    a = project_runtime_state(store, now_ms=now * 1000.0)
    b = project_runtime_state(store, now_ms=now * 1000.0)

    assert a == b, "deux lectures du même journal doivent donner le même état"
    assert len(store.events()) == avant, "une projection qui écrit n'est pas une projection"


def test_une_issue_ULTERIEURE_change_l_etat_sans_toucher_la_decision(store):
    """La grammaire event-sourced : la décision reste immuable, l'issue arrive après et
    la projection bouge."""
    now = time.time()
    d1 = _decision(store, decision="GO", ts=now - 900)
    d2 = _decision(store, decision="GO", ts=now - 600)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.consecutive_losses == 0 and etat.lockout_until_ms is None

    _outcome(store, d1, "LOSS", ts=now - 800)
    _outcome(store, d2, "LOSS", ts=now - 500)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.consecutive_losses == 2
    assert etat.lockout_until_ms is not None


def test_une_serie_se_CASSE_sur_une_non_perte(store):
    now = time.time()
    d1 = _decision(store, decision="GO", ts=now - 900)
    d2 = _decision(store, decision="GO", ts=now - 800)
    d3 = _decision(store, decision="GO", ts=now - 700)
    _outcome(store, d1, "LOSS", ts=now - 850)
    _outcome(store, d2, "LOSS", ts=now - 750)
    _outcome(store, d3, "WIN", ts=now - 650)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.consecutive_losses == 0, "une victoire remet le compteur à zéro"
    assert etat.lockout_until_ms is None


def test_une_issue_ORPHELINE_ne_verrouille_rien(store):
    """Une issue dont la décision est inconnue (import partiel, réconciliation bancale) ne doit
    ni verrouiller ni déverrouiller — elle est ignorée, pas interprétée."""
    now = time.time()
    _outcome(store, "decision-inexistante", "LOSS", ts=now - 100)
    _outcome(store, "autre-fantome", "LOSS", ts=now - 50)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.consecutive_losses == 0
    assert f6_cooldown(etat, now * 1000.0) is None


def test_les_pertes_d_HIER_ne_verrouillent_pas_ce_matin(store):
    """F6 protège d'un enchaînement à chaud, pas d'une mauvaise semaine. L'horizon long est F8,
    qui n'est pas porté — le confondre donnerait un verrou qu'on ne saurait plus lever."""
    now = time.time()
    hier = now - 36 * 3600
    d1 = _decision(store, decision="GO", ts=hier - 200)
    d2 = _decision(store, decision="GO", ts=hier - 100)
    _outcome(store, d1, "LOSS", ts=hier - 150)
    _outcome(store, d2, "LOSS", ts=hier - 50)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert session_date(now * 1000.0) != session_date(hier * 1000.0), "fixture mal datée"
    assert etat.consecutive_losses == 0
    assert f6_cooldown(etat, now * 1000.0) is None


def test_trades_today_ne_compte_que_les_GO(store):
    now = time.time()
    _decision(store, decision="GO", ts=now - 300)
    _decision(store, decision="NO_GO", ts=now - 200)
    _decision(store, decision="NO_GO", ts=now - 100)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.trades_today == 1, "un NO_GO n'est pas un trade"


# ---------------------------------------------------------------- F6

def test_F6_verrouille_pendant_la_duree_puis_relache(store):
    now = time.time()
    d1 = _decision(store, decision="GO", ts=now - 600)
    d2 = _decision(store, decision="GO", ts=now - 400)
    _outcome(store, d1, "LOSS", ts=now - 500)
    _outcome(store, d2, "LOSS", ts=now - 300)
    now_ms = now * 1000.0

    etat = project_runtime_state(store, now_ms=now_ms)
    assert f6_cooldown(etat, now_ms) == F6_COOLDOWN_ACTIVE

    # Le verrou court depuis la DERNIÈRE perte, pas depuis maintenant.
    apres = etat.lockout_until_ms + 1.0
    assert f6_cooldown(etat, apres) is None


def test_F6_ne_mord_pas_a_UNE_seule_perte(store):
    now = time.time()
    d = _decision(store, decision="GO", ts=now - 300)
    _outcome(store, d, "LOSS", ts=now - 200)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.consecutive_losses == 1
    assert f6_cooldown(etat, now * 1000.0) is None


# ---------------------------------------------------------------- F7

def test_F7_refuse_un_sweep_trop_vieux():
    now_ms = 1_000_000.0
    frais = now_ms - config.LSR_F7_FOMO_WINDOW_MS + 1_000
    vieux = now_ms - config.LSR_F7_FOMO_WINDOW_MS - 1_000

    assert f7_fomo(frais, now_ms) is None
    assert f7_fomo(vieux, now_ms) == F7_FOMO_TIMEOUT


def test_F7_sans_horodatage_de_sweep_REFUSE():
    """Fail-closed §3 : ne pas savoir depuis quand le setup existe n'est pas savoir qu'il est
    frais. Un `None` traité comme « âge zéro » ouvrirait la porte la plus large possible."""
    assert f7_fomo(None, 1_000_000.0) == F7_FOMO_TIMEOUT


def test_F7_resubmit_a_desormais_sa_SOURCE(store):
    """Ce test disait l'inverse en D-094 : la règle était inerte faute d'events. D-095 a fermé la
    boucle — le garde journalise ses refus, la projection les relit. On vérifie donc les deux
    états du drapeau, parce que « aucun refus » et « refus non suivis » ne doivent jamais se
    confondre."""
    etat = project_runtime_state(store, now_ms=time.time() * 1000.0)
    assert etat.resubmit_tracking_available is True, "la source d'events existe (D-095)"
    assert etat.rejected_setup_ids == (), "journal vide = aucun refus, pas « non suivi »"
    assert f7_resubmit("setup-42", etat) is None

    arme = LsrRuntimeState(session_date=etat.session_date, consecutive_losses=0, trades_today=0,
                           lockout_until_ms=None, rejected_setup_ids=("setup-42",),
                           resubmit_tracking_available=True)
    assert f7_resubmit("setup-42", arme) == "F7_RESUBMIT_LOCKOUT"
    assert f7_resubmit("setup-7", arme) is None

    # Le drapeau à faux neutralise la règle : un état construit sans source ne doit pas refuser
    # sur une liste dont il ne garantit pas la complétude.
    aveugle = LsrRuntimeState(session_date=etat.session_date, consecutive_losses=0, trades_today=0,
                              lockout_until_ms=None, rejected_setup_ids=("setup-42",))
    assert f7_resubmit("setup-42", aveugle) is None


# ---------------------------------------------------------------- A5b

def _etat(trades_today: int) -> LsrRuntimeState:
    return LsrRuntimeState(session_date="2026-08-14", consecutive_losses=0,
                           trades_today=trades_today, lockout_until_ms=None)


def test_A5b_exige_la_confluence_au_PREMIER_trade():
    sans = a5b_first_trade_confluence(_etat(0), coincides_with_vpoc=True,
                                      secondary_reference="NONE")
    assert sans == A5B_FIRST_TRADE_CONFLUENCE

    avec = a5b_first_trade_confluence(_etat(0), coincides_with_vpoc=True,
                                      secondary_reference="VWAP")
    assert avec is None


def test_A5b_ne_mord_plus_apres_le_premier_trade():
    assert a5b_first_trade_confluence(_etat(1), coincides_with_vpoc=False,
                                      secondary_reference="NONE") is None


def test_A5b_exige_les_DEUX_conditions():
    """`coincidesWithVpoc && secondaryReference !== 'NONE'` — un ET, pas un OU."""
    assert a5b_first_trade_confluence(_etat(0), coincides_with_vpoc=False,
                                      secondary_reference="VWAP") == A5B_FIRST_TRADE_CONFLUENCE
    assert a5b_first_trade_confluence(_etat(0), coincides_with_vpoc=True,
                                      secondary_reference=None) == A5B_FIRST_TRADE_CONFLUENCE


# ---------------------------------------------------------------- parité (D-072)

def test_les_seuils_PYTHON_correspondent_au_TS_qui_fait_autorite():
    """Le verrou qui MORD : il lit `lsr-engine/src/config.ts` et échoue si un nombre diverge.
    Recopier quatre constantes sans verrou, c'est se garantir une divergence silencieuse."""
    ts = ts_engine_source("config.ts")

    def valeur(cle: str) -> float:
        m = re.search(rf"{cle}:\s*([0-9_*\s]+),", ts)
        assert m, f"{cle} introuvable dans config.ts — le moteur de référence a bougé"
        return float(eval(m.group(1).replace("_", "").strip()))  # noqa: S307 — littéral numérique

    assert config.LSR_F6_COOLDOWN_MS == valeur("f6CooldownMs")
    assert config.LSR_F6_CONSECUTIVE_LOSS_TRIGGER == valeur("f6ConsecutiveLossTrigger")
    assert config.LSR_F7_FOMO_WINDOW_MS == valeur("f7FomoWindowMs")
    assert config.LSR_F7_RESUBMIT_LOCKOUT_MS == valeur("f7ResubmitLockoutMs")


def test_les_motifs_de_refus_portent_les_MEMES_chaines_que_le_TS():
    ts = ts_engine_source("types.ts")
    for motif in (F6_COOLDOWN_ACTIVE, F7_FOMO_TIMEOUT, A5B_FIRST_TRADE_CONFLUENCE,
                  "F7_RESUBMIT_LOCKOUT"):
        assert f"'{motif}'" in ts, f"{motif} absent de RejectReason — les journaux divergeraient"


def test_aucune_regle_ne_rend_un_BOOLEEN():
    """Un refus sans motif n'est pas actionnable, et le journal en a besoin. Le garde
    structurel : chaque règle rend `None` ou une chaîne."""
    etat = _etat(0)
    rendus = [f6_cooldown(etat, 0.0), f7_fomo(None, 0.0), f7_resubmit("x", etat),
              a5b_first_trade_confluence(etat, coincides_with_vpoc=False,
                                         secondary_reference="NONE")]
    for r in rendus:
        assert r is None or isinstance(r, str), f"règle rendant un {type(r).__name__}"
        assert not isinstance(r, bool)


# ---------------------------------------------------------------- le garde (D-095)

class _Payload:
    """Minimal — le garde ne lit que `now` et `state`."""

    def __init__(self, now: float, state: object = "ETAT") -> None:
        self.now = now
        self.state = state


def _plan(setup_id: str = "MES:BID_SWEEP:1000", sweep_ts: float | None = None) -> dict:
    return {"status": "APPROVED", "instrument": "MES", "direction": "LONG",
            "protection": {"setup_id": setup_id, "sweep_ts": sweep_ts}}


def test_le_garde_LAISSE_PASSER_un_plan_sain(store):
    from app.lsr_protection import guard_evaluator
    now = time.time()
    plan = _plan(sweep_ts=now - 5)                      # sweep frais
    garde = guard_evaluator(lambda p: (plan, "ETAT_SUIVANT"), store=store)

    rendu, etat = garde(_Payload(now))
    assert rendu is plan and etat == "ETAT_SUIVANT"
    assert store.events("SetupRejectedEvent") == []


def test_un_refus_F6_N_EVALUE_MEME_PAS_et_laisse_l_etat_INTACT(store):
    """Le contrat avec le driver : rendre `(None, payload.state)` fait que `_dispatch_plan`
    reste silencieux et que `_advance_state` ne persiste rien."""
    from app.lsr_protection import guard_evaluator
    now = time.time()
    d1 = _decision(store, decision="GO", ts=now - 600)
    d2 = _decision(store, decision="GO", ts=now - 400)
    _outcome(store, d1, "LOSS", ts=now - 500)
    _outcome(store, d2, "LOSS", ts=now - 300)

    appels = []
    garde = guard_evaluator(lambda p: (appels.append(p) or _plan(), "AUTRE"), store=store)

    plan, etat = garde(_Payload(now, state="ETAT_COURANT"))
    assert plan is None, "un refus n'émet rien"
    assert etat == "ETAT_COURANT", "un refus ne fait pas avancer l'état"
    assert appels == [], "F6 court-circuite : verrouillé, on n'évalue même pas"

    refus = store.events("SetupRejectedEvent")
    assert len(refus) == 1 and refus[0]["reason"] == F6_COOLDOWN_ACTIVE
    assert refus[0]["setup_id"] is None, "le verrou F6 porte sur le compte, pas sur un setup"


def test_le_garde_REFUSE_un_sweep_perime(store):
    from app.lsr_protection import guard_evaluator
    now = time.time()
    vieux = now - (config.LSR_F7_FOMO_WINDOW_MS / 1000.0) - 10
    garde = guard_evaluator(lambda p: (_plan(sweep_ts=vieux), "AUTRE"), store=store)

    plan, etat = garde(_Payload(now, state="ETAT_COURANT"))
    assert plan is None and etat == "ETAT_COURANT"
    assert store.events("SetupRejectedEvent")[0]["reason"] == F7_FOMO_TIMEOUT


def test_un_plan_SANS_provenance_est_refuse(store):
    """Fail-closed : un plan qui ne dit pas de quel sweep il vient ne peut pas être daté, donc
    pas être jugé frais."""
    from app.lsr_protection import guard_evaluator
    now = time.time()
    garde = guard_evaluator(lambda p: ({"status": "APPROVED"}, "AUTRE"), store=store)

    plan, _ = garde(_Payload(now))
    assert plan is None
    assert store.events("SetupRejectedEvent")[0]["reason"] == F7_FOMO_TIMEOUT


def test_la_BOUCLE_de_F7_resubmit_est_fermee(store):
    """Le refus journalisé alimente la projection, qui verrouille la re-soumission du MÊME setup.
    C'est la moitié qui manquait en D-094."""
    from app.lsr_protection import guard_evaluator
    now = time.time()
    vieux = now - (config.LSR_F7_FOMO_WINDOW_MS / 1000.0) - 10

    # 1er passage : refusé pour FOMO, et journalisé.
    garde = guard_evaluator(lambda p: (_plan("MES:BID_SWEEP:42", sweep_ts=vieux), "X"), store=store)
    garde(_Payload(now))

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.resubmit_tracking_available is True
    assert "MES:BID_SWEEP:42" in etat.rejected_setup_ids

    # 2e passage : le MÊME setup, cette fois avec un sweep frais → c'est le verrou qui mord.
    garde2 = guard_evaluator(lambda p: (_plan("MES:BID_SWEEP:42", sweep_ts=now - 1), "X"),
                             store=store)
    plan, _ = garde2(_Payload(now))
    assert plan is None
    assert store.events("SetupRejectedEvent")[-1]["reason"] == "F7_RESUBMIT_LOCKOUT"


def test_un_verrou_de_resubmit_EXPIRE(store):
    """« Lockout », pas « bannissement » : passé la fenêtre, le setup redevient proposable."""
    from app.lsr_protection import guard_evaluator
    now = time.time()
    store.append("SetupRejectedEvent", {"setup_id": "MES:BID_SWEEP:7", "reason": "F7_FOMO_TIMEOUT"},
                 ts=now - (config.LSR_F7_RESUBMIT_LOCKOUT_MS / 1000.0) - 60)

    etat = project_runtime_state(store, now_ms=now * 1000.0)
    assert etat.rejected_setup_ids == ()

    garde = guard_evaluator(lambda p: (_plan("MES:BID_SWEEP:7", sweep_ts=now - 1), "X"), store=store)
    plan, _ = garde(_Payload(now))
    assert plan is not None, "le verrou doit expirer"


def test_le_garde_ne_touche_PAS_aux_ALERT(store):
    """Une ALERT n'est pas une entrée : la garder serait étendre le périmètre des règles."""
    from app.lsr_protection import guard_evaluator
    alerte = {"status": "ALERT", "reason": "niveau approché"}
    garde = guard_evaluator(lambda p: (alerte, "AUTRE"), store=store)

    plan, etat = garde(_Payload(time.time()))
    assert plan is alerte and etat == "AUTRE"
    assert store.events("SetupRejectedEvent") == []


def test_A5b_n_est_PAS_branche_et_la_raison_est_verrouillee():
    """Ce test tombera le jour où `secondary_reference` aura un producteur — il rappellera alors
    de brancher A5b. Un refus qui s'auto-annule quand sa cause disparaît (même patron que la
    gate ATR)."""
    from app.lsr_protection import guard_evaluator
    import inspect
    source = inspect.getsource(guard_evaluator)
    assert "a5b_first_trade_confluence" not in source, "A5b branché — vérifier sa source de donnée"

    ts = ts_engine_source("scanner.ts")
    assert "secondaryReference" in ts
    # La preuve du blocage : le champ est LU, jamais CALCULÉ, dans tout le moteur de référence.
    for fichier in ("scanner.ts", "planner.ts", "geometry.ts", "orderflow.ts"):
        assert "secondaryReference =" not in ts_engine_source(fichier), (
            f"{fichier} calcule secondaryReference — A5b devient branchable")


# ---------------------------------------------------------------- branchement réel (D-096)

def _redis_ok() -> bool:
    import asyncio

    from app.redis_state import RedisState

    async def probe() -> bool:
        st = RedisState()
        try:
            return await st.ping()
        finally:
            await st.close()
    try:
        return asyncio.run(probe())
    except Exception:
        return False


@pytest.mark.skipif(not _redis_ok(), reason="Redis indisponible — intégration sautée")
def test_le_MOTEUR_refuse_reellement_un_setup_sous_verrou_F6(tmp_path, monkeypatch):
    """La preuve que le garde est BRANCHÉ, pas seulement disponible : on passe par
    `Engine._maybe_emit_lsr`, le chemin où `evaluate_lsr` tourne pour de vrai."""
    import asyncio

    from app import engine as engine_mod
    from app.datasource.mock import MockDataSource
    from app.engine import Engine
    from app.redis_state import RedisState
    from app.schema import LiquiditySweep, LiquiditySweepAlert

    journal = EventStore(str(tmp_path / "events.db"))
    now = time.time()

    # Compte verrouillé : deux pertes consécutives dans la séance.
    d1 = _decision(journal, decision="GO", ts=now - 600)
    d2 = _decision(journal, decision="GO", ts=now - 400)
    _outcome(journal, d1, "LOSS", ts=now - 500)
    _outcome(journal, d2, "LOSS", ts=now - 300)

    monkeypatch.setattr(engine_mod, "get_store", lambda: journal)
    monkeypatch.setattr(engine_mod, "evaluate_lsr",
                        lambda i: {"status": "APPROVED", "instrument": "MES",
                                   "direction": "LONG",
                                   "protection": {"setup_id": "MES:BID_SWEEP:1", "sweep_ts": now}})
    emis = []

    async def scenario():
        state = RedisState()
        try:
            moteur = Engine(MockDataSource(), state)
            monkeypatch.setattr(moteur, "account_provider", None)   # au-delà du garde
            moteur.schema.liquidity_sweep = LiquiditySweep(
                assessable=True, triggered=True, reason="t",
                alert=LiquiditySweepAlert(ts=now, kind="LIQUIDITY_SWEEP",
                                          direction="BID_SWEEP", trigger="T", detail="t"))
            moteur._maybe_emit_lsr(now)
            emis.append(moteur._lsr_emitted_key)
        finally:
            await state.close()

    asyncio.run(scenario())

    refus = journal.events("SetupRejectedEvent")
    assert len(refus) == 1, "le moteur n'a pas consulté les règles de protection"
    assert refus[0]["reason"] == F6_COOLDOWN_ACTIVE
