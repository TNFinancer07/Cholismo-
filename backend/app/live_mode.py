"""Mode Live (cholismo_unified Phase B, D-023) — the plain-language analytical layer.

DETERMINISTIC BY DESIGN: the market reading and the dialogue are pure rule-based
functions over the live ContextSchema — sub-millisecond, zero LLM call, zero write.
This honors the hard constraints: Claude is never synchronous in the hot path
(CLAUDE §2.8) and the lock stays the deterministic engine — Mode Live is ADVISORY,
read-only over active scores (« Mode Live propose, le RMS dispose »).

Fail-closed language too: a missing datum yields an explicit « PAS DE DONNÉES »
message (CLAUDE §2.3), never a reassuring sentence built on absent values.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import config
from .meta import Freshness, MetaField
from .schema import ContextSchema, Phase0State
from .strategies.sony import MR_WINDOW, SVS_WINDOW

MTL = ZoneInfo("America/Montreal")

SUGGESTIONS = [
    "Qu'est-ce qui a changé ?",
    "Le contexte est-il favorable ?",
    "Explique-moi simplement.",
    "Pourquoi c'est bloqué ?",
]

_GLOSSARY = {
    "vix": "VIX — la « nervosité » du marché (volatilité implicite S&P 500)",
    "chop": "CHOP — mesure d'indécision du marché (≥ 61.8 = pas de direction)",
    "cvd": "CVD — delta cumulé des volumes : qui est agresseur, acheteur ou vendeur",
    "gex": "GEX — exposition gamma des dealers : négatif = la volatilité s'amplifie",
    "absorption": "Absorption — de gros acteurs tiennent un niveau malgré la pression",
}


def _num(meta: MetaField) -> Optional[float]:
    if meta.freshness == Freshness.ABSENT or meta.value is None:
        return None
    try:
        return float(meta.value)
    except (TypeError, ValueError):
        return None


def _fmt(v: Optional[float], digits: int = 1) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


class LiveCtx:
    """Flat snapshot used by the reading + responder (mirrors the injected schema)."""

    def __init__(self, schema: ContextSchema, extras: dict[str, Any], mode: str):
        self.mode = mode
        self.vix = _num(schema.s2_state.cascade.vix)
        self.chop = _num(schema.s1_state.chop)
        self.cvd = _num(schema.s1_state.order_flow.cvd)
        self.gex = _num(schema.bridge_variables.gex)
        self.svs_score = _num(schema.s1_state.svs_score)
        self.unified = schema.unified_signal_output.score
        self.degraded = schema.unified_signal_output.degraded
        self.phase0_blocked = schema.session_identity.phase0 == Phase0State.BLOCKED
        self.blockers = [b.label for b in schema.session_identity.phase0_blockers]
        self.rms = extras.get("rms")
        self.window = _current_window()
        self.absent = [name for name, v in
                       (("VIX", self.vix), ("CHOP", self.chop), ("CVD", self.cvd),
                        ("GEX", self.gex)) if v is None]


def _current_window(now: Optional[float] = None) -> str:
    """svs | mean_reversion | off_window — same deterministic Montréal clock as the
    Sony strategy gates (reference/sony); display context, never a lock."""
    local = datetime.fromtimestamp(now if now is not None else time.time(), tz=MTL)
    minutes = local.hour * 60 + local.minute
    for label, ((h1, m1), (h2, m2)) in (("svs", SVS_WINDOW), ("mean_reversion", MR_WINDOW)):
        if h1 * 60 + m1 <= minutes < h2 * 60 + m2:
            return label
    return "off_window"


def context_payload(schema: ContextSchema, extras: dict[str, Any], mode: str,
                    now: Optional[float] = None) -> dict[str, Any]:
    """The injected context of the mock, fed by the REAL schema (lecture seule)."""
    ctx = LiveCtx(schema, extras, mode)
    return {
        "timestamp": now if now is not None else time.time(),
        "session_window": ctx.window,
        "market": {"cvd": ctx.cvd, "chop": ctx.chop},
        "macro": {"vix": ctx.vix, "gex": ctx.gex},
        "active_scores": {"svs": ctx.svs_score, "unified": ctx.unified,
                          "degraded": ctx.degraded},  # lecture seule — jamais mutés ici
        "rms_state": {"level": ctx.rms},
        "phase0": {"blocked": ctx.phase0_blocked, "blockers": ctx.blockers},
        "absent_fields": ctx.absent,
    }


def market_reading(schema: ContextSchema, extras: dict[str, Any], mode: str) -> dict[str, Any]:
    """Three statuses, three languages (mock §B.VULG) — deterministic, fail-closed."""
    ctx = LiveCtx(schema, extras, mode)

    if ctx.absent:
        return {"level": "ROUGE", "title": "Pas de données",
                "message": f"Données absentes : {', '.join(ctx.absent)}. "
                           "Le système est fail-closed : aucune lecture n'est inventée "
                           "sur des valeurs manquantes."}
    if ctx.phase0_blocked:
        detail = " · ".join(ctx.blockers[:2]) or "règle Phase 0"
        return {"level": "ROUGE", "title": "Prudence",
                "message": f"Phase 0 est BLOQUÉ ({detail}). L'entrée est verrouillée par "
                           "l'architecture, pas par un avis — attendre le déblocage."}
    if ctx.vix is not None and ctx.vix > config.VIX_CRIT:
        return {"level": "ROUGE", "title": "Prudence",
                "message": f"VIX à {_fmt(ctx.vix)} — au-dessus du seuil {config.VIX_CRIT:.0f}. "
                           "La volatilité grimpe vite, les prix bougent fort dans les deux sens."}
    if ctx.chop is not None and ctx.chop >= config.CHOP_CRIT:
        return {"level": "ROUGE", "title": "Prudence",
                "message": f"CHOP à {_fmt(ctx.chop, 0)} — au-dessus de {config.CHOP_CRIT}. "
                           "Le marché est trop indécis pour un setup directionnel."}
    warn = ((ctx.vix is not None and ctx.vix > 22)
            or (ctx.chop is not None and ctx.chop > 55)
            or (ctx.rms is not None and ctx.rms >= config.RMS_WARN))
    if warn:
        return {"level": "AMBRE", "title": "Attention",
                "message": f"Le contexte se dégrade — VIX {_fmt(ctx.vix)}, CHOP "
                           f"{_fmt(ctx.chop, 0)}. J'attendrais un signal plus net avant de bouger."}
    flux = ("pression vendeuse à surveiller" if (ctx.cvd or 0) < -1500
            else "pression acheteuse à surveiller" if (ctx.cvd or 0) > 1500
            else "flux équilibré")
    return {"level": "VERT", "title": "Tout va bien",
            "message": f"Le marché est calme et lisible. CHOP {_fmt(ctx.chop, 0)}, VIX "
                       f"{_fmt(ctx.vix)}, {flux}. Rien d'inhabituel pour l'instant."}


def answer(question: str, schema: ContextSchema, extras: dict[str, Any],
           mode: str) -> dict[str, Any]:
    """Rule-based dialogue (port of the mock's respond()) over REAL values.

    Every factual sentence cites schema data; conflicts are exposed, never masked;
    out-of-scope questions are politely refused. Pure function — O(1), no I/O.
    """
    ctx = LiveCtx(schema, extras, mode)
    q = question.lower()
    glossary: Optional[str] = None

    def has(*words: str) -> bool:
        return any(w in q for w in words)

    # Out-of-scope refusal first — it does not depend on market data.
    if has("acheter", "apple", "action", "crypto", "bitcoin"):
        text = ("Je me concentre uniquement sur les futures ES/NQ et l'EUR/USD de cette "
                "séance — je ne donne pas d'avis sur des actifs individuels hors périmètre. "
                "Je peux expliquer le contexte général si ça aide.")
    elif ctx.absent and not has("pourquoi", "données", "absent"):
        text = (f"Je ne peux pas répondre proprement : données absentes "
                f"({', '.join(ctx.absent)}). Fail-closed — je ne lis pas un marché "
                "que je ne vois pas.")
    elif ctx.phase0_blocked and has("entrer", "bon moment", "go", "trade"):
        detail = " · ".join(ctx.blockers[:2]) or "règle Phase 0"
        text = (f"Non, pas maintenant. Phase 0 est BLOQUÉ ({detail}) — l'entrée est "
                "verrouillée par le moteur déterministe. Je propose, le verrou dispose.")
    elif has("pourquoi", "bloqué", "bloque"):
        if ctx.phase0_blocked:
            text = ("Phase 0 est BLOQUÉ : " + (" · ".join(ctx.blockers[:3]) or "règle active")
                    + ". Chaque blocage est une règle booléenne, pas un avis.")
        else:
            text = (f"Rien n'est bloqué : Phase 0 est OUVERT. Signal unifié "
                    f"{_fmt(ctx.unified, 0)}"
                    + (" (dégradé /80 — macro NON CALIBRÉ)" if ctx.degraded else "") + ".")
    elif has("entrer", "bon moment"):
        if ctx.vix is not None and ctx.vix > config.VIX_CRIT:
            text = (f"Non. VIX à {_fmt(ctx.vix)} > {config.VIX_CRIT:.0f} — Phase 0 "
                    "suspend la session, l'entrée est bloquée par l'architecture.")
        elif ctx.chop is not None and ctx.chop >= config.CHOP_CRIT:
            text = (f"Non. CHOP à {_fmt(ctx.chop, 0)} ≥ {config.CHOP_CRIT} — marché trop "
                    "indécis pour un setup directionnel.")
        else:
            flux = ("une pression vendeuse à surveiller" if (ctx.cvd or 0) < -1500
                    else "un flux équilibré")
            text = (f"Le contexte est ouvert (VIX {_fmt(ctx.vix)}, CHOP {_fmt(ctx.chop, 0)}). "
                    f"Le signal unifié est à {_fmt(ctx.unified, 0)} — c'est lui et la fenêtre "
                    f"C3 qui décident, pas moi. Pour l'instant je vois {flux}.")
    elif has("changé", "change"):
        gex_note = ("GEX négatif — la volatilité peut s'amplifier."
                    if (ctx.gex or 0) < 0 else "GEX positif — volatilité contenue.")
        text = (f"Depuis le dernier cycle : CVD à {_fmt(ctx.cvd, 0)}, "
                f"{'absorption sur le bid' if (ctx.cvd or 0) < -1500 else 'flux symétrique'}. "
                f"{gex_note}")
        glossary = _GLOSSARY["gex"]
    elif has("absorption"):
        text = ("ES absorbe le bid agressivement — de gros acheteurs tiennent le prix "
                "malgré la pression vendeuse." if (ctx.cvd or 0) < -1500 else
                "Pas d'absorption marquée pour l'instant — le flux est symétrique.")
        glossary = _GLOSSARY["absorption"]
    elif has("contexte", "favorable"):
        verdict = ("Défavorable" if ctx.phase0_blocked
                   else "Mitigé" if (ctx.chop or 0) > 55 or (ctx.vix or 0) > 22
                   else "Favorable")
        text = (f"{verdict}. VIX {_fmt(ctx.vix)}, CHOP {_fmt(ctx.chop, 0)}, GEX "
                f"{_fmt(ctx.gex)}B. "
                + ("Phase 0 bloque l'entrée." if ctx.phase0_blocked
                   else "Les filtres Phase 0 sont passés."))
    elif has("simplement", "explique"):
        if ctx.phase0_blocked:
            text = ("Le marché n'est pas dans des conditions où notre système accepte de "
                    "trader — il se met en sécurité tout seul. Ce n'est pas une panne, "
                    "c'est une protection.")
        else:
            text = (f"Le marché est {'calme et lisible' if (ctx.chop or 99) < 50 else 'plus hésitant'} "
                    "en ce moment. "
                    + ("On voit beaucoup de ventes mais les prix tiennent — quelqu'un de "
                       "gros achète ce qui se présente." if (ctx.cvd or 0) < -2000
                       else "Le flux d'ordre est équilibré."))
    elif has("chop"):
        text = (f"CHOP à {_fmt(ctx.chop, 0)}. "
                + ("Il est au-dessus de 55 — le marché devient moins directionnel."
                   if (ctx.chop or 0) > 55 else
                   f"Bien sous le seuil {config.CHOP_CRIT} — marché lisible."))
        glossary = _GLOSSARY["chop"]
    elif has("vix"):
        text = (f"VIX à {_fmt(ctx.vix)}. "
                + ("Élevé — le sizing VIX-tier réduit la taille." if (ctx.vix or 0) > 20
                   else "Stable — pas d'impact sur le sizing."))
        glossary = _GLOSSARY["vix"]
    elif has("risque", "rms"):
        text = ("Donnée RMS absente — fail-closed." if ctx.rms is None else
                f"RMS à {ctx.rms:.1f} (surveillance ≥ {config.RMS_WARN:.0f}, critique ≥ "
                f"{config.RMS_CRIT:.0f}). Le RMS dispose : je ne peux ni l'armer ni le couper.")
    elif has("score", "svs"):
        conflict = (ctx.svs_score is not None and ctx.svs_score >= 50
                    and (ctx.cvd or 0) < -2500)
        text = (f"SVS à {_fmt(ctx.svs_score, 0)}, signal unifié {_fmt(ctx.unified, 0)}"
                + (" (dégradé /80 — macro NON CALIBRÉ)" if ctx.degraded else "") + ". "
                + ("⚠ Conflit exposé : le score tient mais le flux montre une absorption "
                   "opposée — la décision reste au trader, jamais d'override silencieux."
                   if conflict else "Pas de conflit entre score et flux pour l'instant."))
    else:
        text = (f"État courant : VIX {_fmt(ctx.vix)} · CHOP {_fmt(ctx.chop, 0)} · CVD "
                f"{_fmt(ctx.cvd, 0)} · GEX {_fmt(ctx.gex)}B · fenêtre {ctx.window}. "
                "Reformule si tu veux un angle précis (contexte, flux, risque, score…).")

    return {"answer": text, "glossary": glossary, "advisory": True,
            "engine": "rules_deterministic", "ts": time.time()}
