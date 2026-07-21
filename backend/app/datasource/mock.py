"""MockDataSource — deliberately pathological (CLAUDE §4: a clean mock is a trap).

Injected pathologies, per tick and per source:
  - missing ticks   -> the reading is simply not written (age grows -> STALE -> ABSENT)
  - late data       -> last_update_ts pushed into the past (real, visible staleness)
  - NaN             -> written as NaN, classified ABSENT downstream, never rendered as 0
  - contradictions  -> two sources disagree on DXY beyond tolerance -> flagged
  - clock desync    -> a source stamps readings with a skewed clock
Sources can be cut via API (Redis `source:{name}:up=0`): everything they feed must
visibly decay to STALE then ABSENT (TASKS 2.4).
"""
from __future__ import annotations

import math
import random
import time
from collections import deque

from ..redis_state import RedisState
from . import scenarios
from .base import MarketDataSource

# Simulated upstream sources -> the fields they own.
SOURCES = {
    "sierra_chart": ["svs_score", "cvd", "absorption", "aggressor_ratio",
                     "vpoc", "vah", "val", "lvn", "chop", "order_book", "tape"],
    "cboe": ["vix", "vvix", "vol_term_structure"],
    "cme": ["nq_es", "zn", "dxy_alt"],
    "fx_feed": ["eurusd", "dx", "dxy"],
    "greeks_engine": ["gex", "options_chain"],
    "macro_feed": ["real_rates", "bridgewater_matrix",
                   # Simulated N1/N2A outputs feeding the REAL Youssef pipeline formulas
                   # (reference/youssef/*, D-021): momentum axes, D-scores, arb deltas.
                   "g_momentum", "pi_momentum", "d1", "d2", "d3", "d4", "d5",
                   "taylor_ois_delta", "phillips_tips_delta", "beer_z", "carry_net",
                   "cycle_div_delta", "leading_turn", "rr_zscore", "spot_momentum"],
    "rms_engine": ["rms"],
    "econ_feed": ["econ_calendar"],   # systemic macro/geo schedule (D-027)
}


class MockDataSource(MarketDataSource):
    def __init__(self):
        self._rng = random.Random(42)
        self._gex_next_compute = 0.0
        self._walk: dict[str, float] = {}
        self._tape: deque = deque(maxlen=40)   # rolling window of observed prints (D-026)
        self._tape_seq = 0
        self._econ: list[dict] = []            # scheduled macro/geo events (D-027)

    # -- helpers --

    def _drift(self, key: str, base: float, vol: float, scale: float = 1.0) -> float:
        """Mean-reverting random walk around the scenario base."""
        current = self._walk.get(key, base)
        current += (base - current) * 0.08 + self._rng.gauss(0, vol * scale)
        self._walk[key] = current
        return current

    async def _emit(self, state: RedisState, source: str, field: str, value,
                    pathologies: dict, flags: list[str] | None = None) -> None:
        """Write one reading through the pathology gauntlet."""
        if not await state.source_up(source):
            return  # source cut -> nothing written -> ages into STALE/ABSENT for real
        rng = self._rng
        if rng.random() < pathologies["drop_p"]:
            return  # missing tick
        ts = time.time()
        emitted_flags = list(flags or [])
        if rng.random() < pathologies["late_p"]:
            ts -= rng.uniform(*pathologies["late_range"])  # late data: honest old timestamp
            emitted_flags.append("LATE_FEED")
        if rng.random() < pathologies["desync_p"]:
            ts += rng.uniform(*pathologies["desync_range"])  # clock desync: skewed stamp
            emitted_flags.append("CLOCK_DESYNC")
        if isinstance(value, float) and rng.random() < pathologies["nan_p"]:
            value = math.nan  # NaN -> ABSENT downstream, never a fabricated number
        await state.write_raw(field, value, source, ts=ts, flags=emitted_flags)

    # -- fast channel: microstructure + bridge (sub-second) --

    async def tick_fast(self, state: RedisState) -> None:
        sc = scenarios.resolve(await state.scenario())
        base, vol, patho = sc["base"], sc["vol"], sc["pathologies"]
        rng = self._rng

        svs = self._drift("svs", base["svs"], vol, 1.5)
        cvd = self._drift("cvd", base["cvd"], vol, 60.0)
        chop = max(0.0, min(100.0, self._drift("chop", base["chop"], vol, 1.2)))
        aggressor = max(0.0, min(1.0, self._drift("aggr", base["aggressor"], vol, 0.02)))
        es = self._drift("es", base["es"], vol, 2.0)

        await self._emit(state, "sierra_chart", "svs_score", round(svs, 1), patho)
        await self._emit(state, "sierra_chart", "cvd", round(cvd, 0), patho)
        await self._emit(state, "sierra_chart", "absorption", rng.random() < 0.3, patho)
        await self._emit(state, "sierra_chart", "aggressor_ratio", round(aggressor, 3), patho)
        await self._emit(state, "sierra_chart", "chop", round(chop, 1), patho)
        vpoc = self._drift("vpoc_offset", 0.0, vol, 3.0)
        await self._emit(state, "sierra_chart", "vpoc", round(es + vpoc, 2), patho)
        await self._emit(state, "sierra_chart", "vah", round(es + 12 + vol, 2), patho)
        await self._emit(state, "sierra_chart", "val", round(es - 12 - vol, 2), patho)
        await self._emit(state, "sierra_chart", "lvn",
                         [round(es - 20 - 6 * k, 2) for k in range(3)], patho)

        # Order book ES — 10 niveaux autour du mid, tick 0.25 (D-025). Pathologies :
        # profondeur partielle, spread élargi, carnet CROISÉ (contradiction) que le
        # moteur détecte et flagge — le mock reste volontairement sale (CLAUDE §4).
        mid = round(es * 4) / 4
        depth = 10 if rng.random() > patho["drop_p"] * 2 else rng.randint(3, 9)
        half_spread = 0.25 if rng.random() > 0.15 else 0.50
        cross_shift = 0.75 if rng.random() < patho["contradict_p"] else 0.0
        bids = [[round(mid - half_spread - 0.25 * k + cross_shift, 2),
                 max(1, int(rng.gauss(60, 35)))] for k in range(depth)]
        asks = [[round(mid + half_spread + 0.25 * k, 2),
                 max(1, int(rng.gauss(60, 35)))] for k in range(depth)]
        await self._emit(state, "sierra_chart", "order_book",
                         {"bids": bids, "asks": asks}, patho)

        # Tape / Time & Sales — 1 à 4 prints par tick autour du mid, sens agresseur biaisé
        # par l'aggressor_ratio (>0.5 = acheteurs à l'offre). Fenêtre glissante côté source
        # (le tape EST le champ). NaN/taille≤0 injectés = pathologies, écartés par le moteur.
        for _ in range(rng.randint(1, 4)):
            self._tape_seq += 1
            side = "BUY" if rng.random() < aggressor else "SELL"
            price = mid + (half_spread if side == "BUY" else -half_spread) \
                + 0.25 * rng.randint(0, 2) * (1 if side == "BUY" else -1)
            size = max(1, int(rng.lognormvariate(1.4, 0.9)))
            if rng.random() < patho["nan_p"]:
                price = math.nan  # pathologie : écartée en aval (jamais un prix inventé)
            self._tape.append({"ts": time.time(), "price": round(price, 2),
                               "size": size, "side": side, "seq": self._tape_seq})
        await self._emit(state, "sierra_chart", "tape", list(self._tape), patho)

        vix = max(9.0, self._drift("vix", base["vix"], vol, 0.5))
        vvix = max(60.0, self._drift("vvix", base["vvix"], vol, 1.5))
        await self._emit(state, "cboe", "vix", round(vix, 2), patho)
        await self._emit(state, "cboe", "vvix", round(vvix, 1), patho)

        # DXY from two sources — contradiction pathology makes them diverge visibly.
        dxy = self._drift("dxy", base["dxy"], vol, 0.06)
        contradiction = rng.random() < patho["contradict_p"]
        dxy_alt = dxy + (rng.uniform(0.8, 2.0) * rng.choice((-1, 1)) if contradiction else rng.gauss(0, 0.02))
        await self._emit(state, "fx_feed", "dxy", round(dxy, 3), patho)
        await self._emit(state, "cme", "dxy_alt", round(dxy_alt, 3), patho)

        eurusd = self._drift("eurusd", base["eurusd"], vol, 0.0008)
        await self._emit(state, "fx_feed", "eurusd", round(eurusd, 5), patho)
        await self._emit(state, "fx_feed", "dx", round(self._drift("dx", 0.0, vol, 0.15), 3), patho)

        # GEX: the Greeks engine recomputes at its own unknown pace (PRD §B2) — the age
        # of the last compute is the ONLY honest freshness signal (sometimes > 180 s).
        now = time.time()
        if now >= self._gex_next_compute:
            gex = self._drift("gex", base["gex"], vol, 0.05e9)
            await self._emit(state, "greeks_engine", "gex", round(gex, 0), patho)
            self._gex_next_compute = now + rng.uniform(20.0, 260.0)

        rms = max(0.0, min(5.0, self._drift("rms", base["rms"], vol, 0.15)))
        await self._emit(state, "rms_engine", "rms", round(rms, 2), patho)

    # -- slow channel: macro cascade + Bridgewater matrix (minutes+) --

    async def tick_slow(self, state: RedisState) -> None:
        sc = scenarios.resolve(await state.scenario())
        base, vol, patho = sc["base"], sc["vol"], sc["pathologies"]
        rng = self._rng

        await self._emit(state, "cme", "nq_es",
                         round(self._drift("nq_es", 0.2, vol, 0.3), 3), patho)
        await self._emit(state, "cme", "zn",
                         round(self._drift("zn", -0.1, vol, 0.2), 3), patho)
        await self._emit(state, "macro_feed", "real_rates",
                         round(self._drift("rr", base["real_rates"], vol, 0.05), 3), patho)

        # 5 dims x 6 axes signed intensity matrix (growth, inflation, policy, credit, fx).
        matrix = [[round(max(-1.0, min(1.0, rng.gauss(0, 0.45))), 2) for _ in range(6)]
                  for _ in range(5)]
        await self._emit(state, "macro_feed", "bridgewater_matrix", matrix, patho)

        # --- Simulated N1/N2A outputs for the Youssef pipeline (bases derived from the
        # scenario regime; the downstream FORMULAS are the canonical ones, D-021) ---
        def clamp(x: float) -> float:
            return max(-1.0, min(1.0, x))
        g = clamp(self._drift("g_mom", (base["svs"] - 50.0) / 40.0, vol, 0.04))
        pi = clamp(self._drift("pi_mom", (base["vix"] - 18.0) / 20.0, vol, 0.04))
        await self._emit(state, "macro_feed", "g_momentum", round(g, 3), patho)
        await self._emit(state, "macro_feed", "pi_momentum", round(pi, 3), patho)
        d_scores = {
            "d1": clamp(self._drift("d1", g * 0.8, vol, 0.05)),
            "d2": clamp(self._drift("d2", -pi * 0.5 - 0.1, vol, 0.05)),
            "d3": clamp(self._drift("d3", pi * 0.6, vol, 0.05)),
            "d4": clamp(self._drift("d4", (15.0 - base["vix"]) / 20.0, vol, 0.05)),
            "d5": clamp(self._drift("d5", -0.2, vol, 0.04)),
        }
        for key, value in d_scores.items():
            await self._emit(state, "macro_feed", key, round(value, 3), patho)
        for key, base_value, scale in (
            ("taylor_ois_delta", 0.15, 0.08),      # Arb1 — seuil 0.30 %
            ("phillips_tips_delta", -0.2, 0.10),   # Arb2 — seuil 0.25 %
            ("beer_z", -1.2, 0.15),                # Arb3 — seuil |z| 1.5
            ("carry_net", 3.0, 0.4),               # Arb4 — seuil 2.0 après gate
            ("cycle_div_delta", 0.4, 0.10),        # Arb5 — seuil 0.5
            ("leading_turn", 0.4, 0.08),
            ("rr_zscore", -(base["vix"] - 18.0) / 6.0, 0.15),  # Arb6 — seuil |z| 1.5
            ("spot_momentum", 0.6, 0.10),
        ):
            await self._emit(state, "macro_feed", key,
                             round(self._drift(key, base_value, vol, scale), 3), patho)

        # --- Economic/geo calendar (D-027): a rolling schedule of scheduled events, each
        # with a KNOWN ts (honest client countdown) and a liquidity-impact tier. Reseeded
        # when empty or fully elapsed. Events are OBSERVED/announced, never orders (§2.1). ---
        now = time.time()
        if not self._econ or all(e["ts"] < now - 120 for e in self._econ):
            self._econ = self._seed_econ(now)
        emitted = [dict(e) for e in self._econ]
        # Pathologie §4 : rarement, un événement structurellement cassé se glisse dans le
        # flux — le moteur doit l'écarter SEUL (jamais un calendrier inventé).
        if rng.random() < patho.get("nan_p", 0.0) + 0.03:
            emitted.append(rng.choice([
                {"ts": math.nan, "name": "Corrompu", "tier": 1, "region": "US"},
                {"name": "SansTs", "tier": 2, "region": "EU"},
                {"ts": now + 600, "name": "TierInvalide", "tier": 7, "region": "US"},
            ]))
        await self._emit(state, "econ_feed", "econ_calendar", emitted, patho)

        # --- Surface de volatilité (D-039) : chaîne d'options synthétique (smile equity +
        # grecques) + structure de vol VIX. Pathologies §4 : IV/grecque NaN rares, patte
        # manquante → le moteur doit les écarter SEUL (fail-closed §3, jamais un chiffre inventé). ---
        await self._emit(state, "greeks_engine", "options_chain",
                         self._gen_options_chain(base, vol, patho), patho)
        await self._emit(state, "cboe", "vol_term_structure",
                         self._gen_term_structure(base, vol), patho)

    def _gen_options_chain(self, base: dict, vol: float, patho: dict) -> dict:
        """Chaîne synthétique : smile actions (IV↑ pour puts OTM), grecques plausibles (delta
        logistique, gamma pic ATM, vanna/charm petits). PLACEHOLDER de démo — pas arbitrage-free."""
        rng = self._rng
        underlying = self._drift("es_underlying", 5000.0, vol, 3.0)
        atm = round(underlying / 25.0) * 25.0
        base_iv = max(0.05, base["vix"] / 100.0)
        expirations = []
        for label, dte in (("W1", 7), ("W2", 14), ("M1", 30), ("M2", 60)):
            strikes = []
            for k in range(-6, 7):
                strike = atm + k * 25.0
                m = (strike - underlying) / underlying          # fraction de moneyness
                iv = max(0.03, base_iv - 0.6 * m + 2.5 * m * m + 0.02 * (dte / 30.0) ** 0.5)
                cdelta = 1.0 / (1.0 + math.exp(-(underlying - strike) / (underlying * 0.01)))
                gamma = math.exp(-((strike - underlying) / (underlying * 0.02)) ** 2) * 0.02
                vanna = -1.5 * m * gamma * 100.0
                charm = -0.3 * cdelta * (1.0 - cdelta) / max(1.0, dte)
                call = {"iv": round(iv, 4), "delta": round(cdelta, 3), "gamma": round(gamma, 5),
                        "vanna": round(vanna, 4), "charm": round(charm, 5)}
                put = {"iv": round(iv + 0.006, 4), "delta": round(cdelta - 1.0, 3),
                       "gamma": round(gamma, 5), "vanna": round(-vanna, 4), "charm": round(charm, 5)}
                # pathologie : IV/grecque NaN rare, ou patte call absente
                if rng.random() < patho.get("nan_p", 0.0) + 0.01:
                    rng.choice([call, put])[rng.choice(("iv", "gamma", "vanna"))] = math.nan
                strikes.append({"strike": strike, "call": call, "put": put})
            expirations.append({"expiry": label, "dte": dte, "strikes": strikes})
        return {"underlying": round(underlying, 2), "expirations": expirations}

    def _gen_term_structure(self, base: dict, vol: float) -> dict:
        """Structure VIX9D/VIX/VIX3M/VIX6M : contango normal (prime de terme), bascule en
        backwardation quand le régime de vol monte (base VIX élevée)."""
        v = base["vix"]
        stress = max(0.0, (v - 22.0) / 8.0)                     # régime tendu → aplatit/inverse
        points = []
        for tenor, days, prem in (("VIX9D", 9, -1.6), ("VIX", 30, 0.0), ("VIX3M", 93, 2.2), ("VIX6M", 186, 3.2)):
            val = max(9.0, self._drift(f"vts_{tenor}", v + prem * (1.0 - stress), vol, 0.4))
            points.append({"tenor": tenor, "days": days, "value": round(val, 2)})
        return {"points": points}

    @staticmethod
    def _seed_econ(now: float) -> list[dict]:
        """Rolling demo schedule spanning Tier 1/2/3, macro & geo, around `now`. Offsets in
        seconds; a Tier-1 inside ±30 min (blackout window) and one beyond, to exercise the
        Sony filter surfacing without wiring Phase 0 (D-027)."""
        plan = [
            (-95,       "IPC zone euro (final)",   2, "EU"),   # vient de passer
            (40,        "Ventes au détail US",     2, "US"),
            (12 * 60,   "NFP — emplois US",        1, "US"),   # T1 dans la fenêtre ±30 min
            (33 * 60,   "Décision Fed — taux",     1, "US"),   # T1 hors ±30 min
            (58 * 60,   "Stocks pétrole EIA",      3, "US"),
            (95 * 60,   "Discours BCE (Lagarde)",  2, "EU"),
            (150 * 60,  "Tensions géo — sommet",   3, "GEO"),
        ]
        return [{"ts": round(now + off, 0), "name": name, "tier": tier, "region": region}
                for off, name, tier, region in plan]
