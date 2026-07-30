"""Feature — bloc `account_state` du ContextSchema (Zone C HUD, D-051).

Comportement figé AVANT implémentation (Loop 1 étape 3) :
- `account_view(account, reference_stop_ticks, instrument)` PURE : projette l'état de compte en
  bloc d'affichage — équité, day_start, floor, buffer, **buffer_initial** (= buffer À L'OUVERTURE
  du jour : `min(day_start − floor, DLL)`, dénominateur honnête et SANS état de la jauge),
  `day_pnl`, `is_stale`, `status`, et le **ticket de référence** pré-calculé (stop de 3 ticks MES) ;
- `account is None` → `status=DISCONNECTED`, `is_stale=True`, **toutes les valeurs None** : le port
  D-047 rend None pour périmé ET déconnecté — on n'invente pas une distinction qu'il ne porte pas,
  et on n'affiche JAMAIS de fausse valeur (§3) ;
- statut = celui du RiskSizer sur le stop de référence (`APPROVED`/`INSUFFICIENT_BUFFER`/
  `INVALID_INPUT`/`SIZE_SANITY_CAP`) — `contracts` n'existe que sur APPROVED ;
- publié sur le canal FAST par l'engine à chaque tick (`get_state`-like : pur, O(1)).
"""
import math
import time

from app import config
from app.account_provider import MockAccountProvider
from app.datasource.mock import MockDataSource
from app.engine import Engine
from app.redis_state import RedisState
from app.risk_sizer import APEX_EOD_50K, AccountState, account_view, apex_eod_account

FLOOR = APEX_EOD_50K.initial_capital - APEX_EOD_50K.max_drawdown        # 47 500
DLL = APEX_EOD_50K.daily_loss_limit                                     # 1 000


def _acc(equity=50_000.0, day_start=50_000.0) -> AccountState:
    return apex_eod_account(APEX_EOD_50K, current_equity=equity, day_start_equity=day_start)


# --- Projection nominale --------------------------------------------------------------------

def test_vue_nominale_jour_neuf():
    v = account_view(_acc())
    assert v["status"] == "APPROVED" and v["is_stale"] is False
    assert v["current_equity"] == 50_000.0 and v["day_start_equity"] == 50_000.0
    assert v["drawdown_floor"] == FLOOR and v["daily_loss_limit"] == DLL
    assert v["buffer"] == 1_000.0                          # min(2500, DLL 1000)
    assert v["buffer_initial"] == 1_000.0                  # à l'ouverture : identique
    assert v["day_pnl"] == 0.0
    # ticket de référence : stop 3 ticks MES → 3.75 $/contrat ; risque 200 → 53 contrats
    t = v["next_ticket"]
    assert t["instrument"] == "MES" and t["stop_ticks"] == config.RISK_REFERENCE_STOP_TICKS
    assert t["contracts"] == 53 and t["status"] == "APPROVED"
    assert t["risk_allowed"] == 200.0


def test_buffer_initial_est_le_buffer_a_l_ouverture_pas_l_actuel():
    """La jauge se mesure contre le buffer DU JOUR OUVERT — pas contre une constante ni contre
    l'actuel (qui donnerait toujours 100 %)."""
    v = account_view(_acc(equity=49_500.0, day_start=50_000.0))
    assert v["buffer"] == 500.0                            # min(2000, 500)
    assert v["buffer_initial"] == 1_000.0                  # min(2500, 1000) au day_start
    assert v["day_pnl"] == -500.0


def test_buffer_initial_quand_le_floor_contraint_des_l_ouverture():
    """Lendemain difficile : day_start 48 200 → à l'ouverture min(700, 1000) = 700."""
    v = account_view(_acc(equity=47_900.0, day_start=48_200.0))
    assert v["buffer_initial"] == 700.0
    assert v["buffer"] == 400.0                            # min(400, 700)


def test_pnl_du_jour_positif():
    v = account_view(_acc(equity=50_600.0, day_start=50_000.0))
    assert v["day_pnl"] == 600.0
    assert v["buffer"] == 1_600.0                          # min(3100, 1600) — DLL contraint encore


# --- Statuts de rejet : le ticket dit POURQUOI ----------------------------------------------

def test_buffer_mort_status_insufficient_buffer_sans_contrats():
    # stop de référence 3 ticks = 3.75 $/contrat → il faut buffer/5 ≥ 3.75, donc buffer ≥ 18.75
    assert account_view(_acc(equity=49_020.0))["next_ticket"]["contracts"] == 1   # buffer 20 : 1 lot
    v = account_view(_acc(equity=49_010.0))                # buffer 10 → risque 2 $ → < 1 contrat
    assert v["status"] == "INSUFFICIENT_BUFFER"
    assert v["next_ticket"]["contracts"] is None           # jamais un 0 déguisé en taille
    assert v["buffer"] == 10.0                             # la valeur RESTE affichable (vraie)


def test_buffer_negatif_status_insufficient_buffer():
    v = account_view(_acc(equity=48_900.0))
    assert v["status"] == "INSUFFICIENT_BUFFER" and v["buffer"] < 0


def test_etat_corrompu_status_invalid_input():
    v = account_view(AccountState(account_type="EOD_TRAILING", current_equity=50_000.0,
                                  day_start_equity=50_000.0, drawdown_floor=-500.0,
                                  daily_loss_limit=DLL))
    assert v["status"] == "INVALID_INPUT"
    assert v["next_ticket"]["contracts"] is None


def test_taille_implausible_status_size_sanity_cap():
    v = account_view(AccountState(account_type="EOD_TRAILING", current_equity=10_000_000.0,
                                  day_start_equity=10_000_000.0, drawdown_floor=FLOOR,
                                  daily_loss_limit=1_000_000.0))
    assert v["status"] == "SIZE_SANITY_CAP"
    assert v["next_ticket"]["contracts"] is None


def test_equite_non_finie_invalid_input_sans_valeurs_affichables():
    v = account_view(AccountState(account_type="EOD_TRAILING", current_equity=math.nan,
                                  day_start_equity=50_000.0, drawdown_floor=FLOOR,
                                  daily_loss_limit=DLL))
    assert v["status"] == "INVALID_INPUT"
    assert v["current_equity"] is None                      # non finie → JAMAIS affichée (§3)
    assert v["buffer"] is None and v["buffer_initial"] is None


# --- Fail-closed : pas de compte = pas de valeurs -------------------------------------------

def test_sans_compte_disconnected_et_aucune_valeur():
    v = account_view(None)
    assert v["status"] == "DISCONNECTED" and v["is_stale"] is True
    for k in ("current_equity", "day_start_equity", "drawdown_floor", "daily_loss_limit",
              "buffer", "buffer_initial", "day_pnl"):
        assert v[k] is None, k
    assert v["next_ticket"]["contracts"] is None
    assert v["next_ticket"]["status"] == "DISCONNECTED"


def test_purete_et_non_mutation():
    acc = _acc(equity=49_300.0)
    a, b = account_view(acc), account_view(acc)
    assert a == b
    assert acc.current_equity == 49_300.0


# --- Publication SSE sur le canal fast ------------------------------------------------------

def test_engine_publie_account_state_sur_le_canal_fast():
    import asyncio
    import json

    from app.sse import broadcaster

    async def scenario(provider):
        eng = Engine(MockDataSource(), RedisState(), account_provider=provider)
        q = broadcaster.subscribe("fast")
        while not q.empty():
            q.get_nowait()
        await eng._assemble_fast(time.time())
        blocks = {}
        while not q.empty():
            e = q.get_nowait()
            blocks[e["event"]] = json.loads(e["data"])
        broadcaster.unsubscribe("fast", q)
        return blocks

    live = MockAccountProvider(state=_acc(equity=49_500.0), always_fresh=True)
    blocks = asyncio.run(scenario(live))
    assert "account_state" in blocks                        # le bloc EXISTE sur le canal fast
    assert blocks["account_state"]["current_equity"] == 49_500.0
    assert blocks["account_state"]["next_ticket"]["contracts"] == 26   # buffer 500 → 100/3.75

    absent = asyncio.run(scenario(None))                    # pas de source
    assert absent["account_state"]["status"] == "DISCONNECTED"
    assert absent["account_state"]["current_equity"] is None
