"""LSR v1.2 — calibration PAR INSTRUMENT et spécifications d'échange (D-069).

Port Python de `lsr-engine/src/config.ts`. Ce module est la **source unique** des grandeurs
microstructure du moteur LSR : plus aucune n'existe en double dans `config.py`.

**Pourquoi une table par instrument et non des scalaires.** MES et MNQ n'ont ni la même densité
de carnet, ni la même vitesse : exiger 150 contrats de profondeur top-3 sur MNQ (carnet plus fin)
bloquerait tout, et tolérer 2 ticks de spread sur MES (carnet dense, 1 tick la quasi-totalité du
temps) laisserait passer des marchés disloqués. Un scalaire unique force à choisir la valeur
*fausse pour un des deux*. Le moteur de référence tranche par instrument ; ce port aussi.

**Pas de variable d'environnement ici — c'est délibéré.** Ces valeurs mirroitent `config.ts`
ligne à ligne et sont verrouillées par `tests/test_parite_lsr_config.py`, qui PARSE le fichier
TypeScript et échoue sur toute divergence. Un override d'environnement contournerait le verrou
en silence : le Python jurerait 0.40 pendant que la prod tournerait à 0.55, et le test resterait
vert. Recalibrer = éditer les DEUX fichiers, et le test le prouve.

**`v1 provisional`** (§11 / doc LSR) : ces nombres sont une « 1re passe », à figer sur 60 trades
réels. Ce qui est figé, c'est qu'ils soient les MÊMES des deux côtés — pas qu'ils soient justes.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel


class InstrumentSpec(BaseModel):
    """Spécifications contractuelles CME — constantes d'échange, JAMAIS calibrables."""
    tick_size: float
    tick_value: float


class InstrumentTuning(BaseModel):
    """Grandeurs calibrables d'un instrument. Noms = snake_case exact des champs de
    `InstrumentTuning` côté TypeScript — c'est ce qui rend la comparaison mécanique."""
    # F4 — fenêtre de liquidité
    f4_max_spread_ticks: float
    f4_min_cumulative_depth: float
    # A2 — TP borné VPOC
    tp_max_ticks: int
    tp_min_ticks: int
    tp_vpoc_margin_ticks: int
    # A1 — zone d'entrée
    entry_offset_ticks: int
    entry_cancel_distance_ticks: int
    # A3 — buffer bruit du stop (borne basse ET borne haute : le buffer est DYNAMIQUE, D-070)
    sl_noise_buffer_min_ticks: int
    sl_noise_buffer_max_ticks: int
    # B1-B4 — gates order flow
    b1_min_wall_refill_ratio: float
    b2_tape_flip_threshold: float
    b3_min_delta_ratio: float
    b4_max_post_sweep_aggression: float
    # UI — distance de déclenchement d'alerte. PAS ENCORE CONSOMMÉE côté Python (le panneau
    # d'alerte de proximité n'existe pas) ; portée ici parce que la table doit être complète
    # pour que le verrou de parité ait un sens — une table à trous ne prouve rien.
    alert_distance_ticks: int


INSTRUMENT_SPECS: dict[str, InstrumentSpec] = {
    "MES": InstrumentSpec(tick_size=0.25, tick_value=1.25),
    "MNQ": InstrumentSpec(tick_size=0.25, tick_value=0.5),
}

#: MES — Micro E-mini S&P 500. Carnet dense, mouvement plus lent.
MES_TUNING = InstrumentTuning(
    f4_max_spread_ticks=1,
    f4_min_cumulative_depth=150,
    tp_max_ticks=5,
    tp_min_ticks=3,
    tp_vpoc_margin_ticks=1,
    entry_offset_ticks=1,
    entry_cancel_distance_ticks=3,
    sl_noise_buffer_min_ticks=1,
    sl_noise_buffer_max_ticks=2,
    b1_min_wall_refill_ratio=0.4,
    b2_tape_flip_threshold=0.6,
    b3_min_delta_ratio=0.3,
    b4_max_post_sweep_aggression=0.3,
    alert_distance_ticks=6,
)

#: MNQ — Micro E-mini Nasdaq-100. Plus rapide, plus volatil, carnet plus fin : buffers et TP
#: plus larges, exigence de profondeur plus basse.
MNQ_TUNING = InstrumentTuning(
    f4_max_spread_ticks=2,
    f4_min_cumulative_depth=60,
    tp_max_ticks=8,
    tp_min_ticks=4,
    tp_vpoc_margin_ticks=1,
    entry_offset_ticks=1,
    entry_cancel_distance_ticks=4,
    sl_noise_buffer_min_ticks=2,
    sl_noise_buffer_max_ticks=4,
    b1_min_wall_refill_ratio=0.4,
    b2_tape_flip_threshold=0.6,
    b3_min_delta_ratio=0.3,
    b4_max_post_sweep_aggression=0.3,
    alert_distance_ticks=10,
)

PER_INSTRUMENT: dict[str, InstrumentTuning] = {"MES": MES_TUNING, "MNQ": MNQ_TUNING}


def tuning(instrument: Optional[str]) -> Optional[InstrumentTuning]:
    """Calibration d'un instrument, ou `None` s'il est inconnu.

    FAIL-CLOSED (§3) : pas de repli sur MES. Un instrument non calibré n'est pas « MES avec un
    autre nom » — MNQ évalué aux seuils MES exigerait 150 de profondeur sur un carnet qui en
    porte 60 et n'émettrait jamais ; l'inverse (MES aux seuils MNQ) accepterait 2 ticks de
    spread sur un instrument qui en cote 1. Un défaut silencieux transformerait une erreur de
    configuration en trades mal dimensionnés — l'appelant doit refuser, pas deviner."""
    return PER_INSTRUMENT.get(instrument) if instrument else None


def spec(instrument: Optional[str]) -> Optional[InstrumentSpec]:
    """Spécification d'échange d'un instrument, ou `None` s'il est inconnu (même doctrine)."""
    return INSTRUMENT_SPECS.get(instrument) if instrument else None


def vix_multiplier(vix: Any, hard_block: Optional[float] = None) -> float:
    """Modificateur de sizing selon le régime VIX — port exact de `config.ts::vixMultiplier`.

        [0, 15) → 1.00 · [15, 20) → 0.75 · [20, 30] → 0.50 · (30, ∞) → 0 (suspendu, F3)

    **La borne de 20.00 est EXCLUSIVE en haut du palier 0.75** : à VIX exactement 20.00 le
    multiplicateur vaut 0.50. Le doc de référence écrit « 15-20 » puis « 20-30 » — 20 appartient
    aux deux, la borne est donc ambiguë dans la source, pas dans le code. On tranche pour la
    lecture la plus SERRÉE (§2.4, fail-closed par défaut), et le moteur TypeScript fait pareil.

    FAIL-CLOSED (§3) : un VIX absent, non fini ou d'un mauvais type rend **0.0**, pas 1.0. Un VIX
    qu'on ne voit pas n'est pas un VIX calme ; le repli inverse donnerait la taille MAXIMALE
    précisément au moment où on est le plus aveugle."""
    if isinstance(vix, bool) or not isinstance(vix, (int, float)) or not math.isfinite(vix):
        return 0.0
    limite = hard_block if hard_block is not None else _hard_block()
    if vix > limite:
        return 0.0
    if vix < 15:
        return 1.0
    if vix < 20:
        return 0.75
    return 0.5


def _hard_block() -> float:
    """`VIX_CRIT` lu À L'APPEL : le blocage dur F3 est une frontière de RISQUE, pas une
    calibration d'instrument — il vit dans `config` et doit rester réglable au runtime."""
    from . import config
    return float(config.VIX_CRIT)
