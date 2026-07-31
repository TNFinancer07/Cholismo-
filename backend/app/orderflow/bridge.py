"""Pont ContextSchema → OrderFlowSnapshot (D-056).

Le calculateur (D-055) prend des **ticks bruts** ; le moteur, lui, vit sur le **ContextSchema**.
Ce module fait la jonction, et rien d'autre : il n'évalue aucune porte, n'applique aucun seuil.

Deux points sont délicats, et c'est pour eux que ce pont existe séparément :

1. **De quel côté est le mur ?** Un `BID_SWEEP` signifie qu'une agression VENDEUSE a balayé le
   bid : le mur attaqué est donc un mur ACHETEUR, situé au plus-BAS de la fenêtre. Le chercher à
   l'ask mesurerait la défense du camp adverse — un contresens complet, invisible dans un nombre
   qui aurait l'air correct. Sans sweep orienté, **aucun mur n'est désigné** : en choisir un « au
   hasard » (le meilleur bid, par exemple) mesurerait une défense que personne n'a attaquée.

2. **L'historique de carnet n'existe nulle part.** Le schéma ne porte que le carnet COURANT (la
   heatmap, elle, accumule côté frontend), or le rechargement d'un mur est par nature une mesure
   dans le TEMPS. `book_history_push` maintient donc un tampon BORNÉ, détenu par l'Engine —
   sans lui, B1 in-house ne serait jamais calculable et le câblage serait fictif.

Fraîcheur : mêmes règles que `build_lsr_inputs` — **FRESH uniquement**. Un tape périmé produirait
des mesures d'order flow parfaitement calculées sur un marché qui n'existe plus (§3).

Le pont est **PUR** : `now` est injecté, aucune horloge lue, aucun état retenu (le tampon
appartient à l'appelant).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from .. import config
from .calculator import OrderFlowSnapshot, compute_snapshot


def _fresh(meta: Any) -> Any:
    """Valeur d'un MetaField si et seulement si elle est FRESH (§3)."""
    if meta is None:
        return None
    freshness = getattr(meta, "freshness", None)
    value = getattr(meta, "value", None)
    return value if str(getattr(freshness, "value", freshness)) == "FRESH" else None


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def book_history_push(history: list, order_book_meta: Any, ts: float,
                      max_len: Optional[int] = None) -> None:
    """Ajoute le carnet COURANT à l'historique, en place. N'accepte que du FRESH et bien formé —
    un carnet périmé accumulé donnerait un rechargement de mur mesuré sur des fossiles.

    Borné : sans plafond, une session de six heures à 4 Hz garderait 86 400 carnets en mémoire.
    """
    cap = max_len if max_len is not None else config.BOOK_HISTORY_MAX
    book = _fresh(order_book_meta)
    if not isinstance(book, dict) or not _finite(ts):
        return
    if not isinstance(book.get("bids"), list) or not isinstance(book.get("asks"), list):
        return
    history.append({"ts": float(ts), "bids": book["bids"], "asks": book["asks"]})
    if len(history) > cap:
        del history[:len(history) - cap]        # on garde les plus RÉCENTS


def _wall(prints: list, direction: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """Niveau et côté du mur attaqué, déduits du sweep. `BID_SWEEP` → mur acheteur au plus-bas
    des prints de la fenêtre ; `ASK_SWEEP` → mur vendeur au plus-haut. Le prix est aligné sur la
    grille : un niveau hors grille n'existe pas dans le carnet."""
    if direction not in ("BID_SWEEP", "ASK_SWEEP"):
        return None, None
    prices = [p["price"] for p in prints
              if isinstance(p, dict) and _finite(p.get("price")) and p["price"] > 0]
    if not prices:
        return None, None
    extreme = min(prices) if direction == "BID_SWEEP" else max(prices)
    grid = round(round(extreme / config.PRICE_TICK) * config.PRICE_TICK, 10)
    return grid, ("BID" if direction == "BID_SWEEP" else "ASK")


def snapshot_for_lsr(schema: Any, book_history: list, *, now: float,
                     sweep_ts: Optional[float], sweep_direction: Optional[str],
                     bars: Any = ()) -> OrderFlowSnapshot:
    """Assemble les entrées du calculateur depuis le schéma et rend le snapshot. Ne lève jamais :
    une entrée absente dégrade la mesure concernée, avec son motif (§3)."""
    s1 = getattr(schema, "s1_state", None)
    tape = _fresh(getattr(s1, "tape", None)) if s1 is not None else None
    prints = tape if isinstance(tape, list) else []
    wall_price, wall_side = _wall(prints, sweep_direction)
    sweep = {"ts": sweep_ts} if _finite(sweep_ts) else None
    return compute_snapshot(now=now, prints=prints, books=book_history, bars=bars,
                            sweep=sweep, tick=config.PRICE_TICK,
                            wall_price=wall_price, wall_side=wall_side)


def orderflow_shadow(schema: Any, snapshot: OrderFlowSnapshot) -> dict:
    """Comparaison OMBRE proxys ↔ mesures maison, calculée à chaque tick sweep **dans les deux
    modes**. Elle ne décide rien : c'est la PREUVE qu'on accumule avant d'oser basculer la source
    de vérité du chemin d'émission (§10 — on ne construit pas la phase N+1 avant que N tourne).

    Ce qu'elle expose, et pourquoi : les deux valeurs brutes (pour voir l'écart), les deux
    VERDICTS de porte (pour voir si l'écart change une décision — c'est ça qui compte), et les
    motifs du calculateur (pour savoir pourquoi la mesure maison manque, le cas échéant).

    Ne lève jamais : un défaut d'observation ne doit pas casser la boucle qu'il observe.
    """
    try:
        s1 = getattr(schema, "s1_state", None)
        of = getattr(s1, "order_flow", None) if s1 is not None else None
        absorption = _fresh(getattr(of, "absorption", None))
        ratio = _fresh(getattr(of, "aggressor_ratio", None))
        sweep = getattr(schema, "liquidity_sweep", None)
        alert = getattr(sweep, "alert", None) if getattr(sweep, "triggered", False) else None
        direction = getattr(alert, "direction", None)

        refill = snapshot.wall_refill_ratio
        flip = snapshot.tape_aggressor_buy_fraction
        v1_src = absorption is True if absorption is not None else None
        v1_ih = (refill >= config.LSR_B1_REFILL_MIN) if _finite(refill) else None

        def _b2_verdict(value: Any) -> Optional[bool]:
            """Même règle que la porte B2 du moteur — sinon la comparaison ne dirait rien de la
            décision réelle. Sans direction de sweep, il n'y a pas de verdict à rendre."""
            if not _finite(value) or not (0.0 <= value <= 1.0) or direction is None:
                return None
            return (value >= config.LSR_B2_FLIP if direction == "BID_SWEEP"
                    else value <= 1.0 - config.LSR_B2_FLIP)

        v2_src, v2_ih = _b2_verdict(ratio), _b2_verdict(flip)
        return {
            "source": config.LSR_ORDERFLOW_SOURCE,
            "b1": {"source": absorption, "inhouse": refill,
                   "verdict_source": v1_src, "verdict_inhouse": v1_ih,
                   "agree": None if v1_src is None or v1_ih is None else v1_src == v1_ih},
            "b2": {"source": ratio, "inhouse": flip,
                   "delta": abs(ratio - flip) if _finite(ratio) and _finite(flip) else None,
                   "verdict_source": v2_src, "verdict_inhouse": v2_ih,
                   "agree": None if v2_src is None or v2_ih is None else v2_src == v2_ih},
            # Mesurés, JAMAIS gatants dans cette tranche (seuils non calibrés) — exposés pour
            # que la décision de les faire gater se prenne sur des observations, pas sur une idée.
            "b3": snapshot.rejection_delta_ratio,
            "b4": snapshot.post_sweep_aggression_ratio,
            "missing": list(snapshot.missing),
        }
    except Exception:                                  # noqa: BLE001 — observation, pas décision
        return {"source": config.LSR_ORDERFLOW_SOURCE, "error": "comparaison indisponible"}
