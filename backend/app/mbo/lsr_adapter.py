"""Détecteur LSR branché sur le flux MBO (D-083, phase P2).

Le point d'armement lisait le `ContextSchema` alimenté par le moteur live ; le harnais de rejeu
(D-081), lui, reconstruit un carnet depuis un flux MBO. Ce module fait le pont — **dans le sens
qui ne duplique rien** : il projette l'état MBO dans un `ContextSchema` minimal, puis réutilise
la chaîne déterministe existante **telle quelle** :

    MboBook + prints  →  ContextSchema minimal  →  build_sweep_inputs → SWEEP_GRAPH
                                                →  build_lsr_inputs   → evaluate_lsr

Réimplémenter la détection pour le MBO aurait créé un second moteur de décision, à faire diverger
du premier. Le dépôt a déjà tranché ce genre de question (D-052 : « les deux ne doivent jamais
tourner ensemble ») ; ici il n'y a qu'un moteur, avec deux sources.

---

**Trois provenances, tenues distinctes** (D-084) :

- **du FLUX** — carnet et transactions, donc l'ATR, qui se dérive des barres de la séance
  rejouée. Aller le chercher ailleurs introduirait une seconde vérité sur le même instrument ;
- **du CONTEXTE DE SÉANCE** — VIX, calendrier, état F0, joints **point-in-time** depuis une
  série historique fournie. Jamais `fetch()` : interroger une API au présent injecterait le VIX
  d'aujourd'hui dans une séance d'alors, un lookahead d'autant plus coûteux qu'il est invisible ;
- **de nulle part** — `svs_score` est un score de stratégie calculé en amont, pas une donnée de
  marché. Le fabriquer reviendrait à réimplémenter une stratégie pour pouvoir la mesurer.

Sans contexte fourni, VIX et calendrier restent ABSENT, les gates refusent, et `diagnostics()`
dit **lesquelles** entrées manquent. C'est la doctrine de `ReplayDataSource` (« un replay dit ce
qu'il sait, et se tait sur le reste ») appliquée un cran plus bas.

**Le côté d'un print est l'AGRESSEUR.** Le carnet MBO résout le côté PASSIF consommé (D-079) ;
le tape du `ContextSchema` attend l'agresseur (convention `tradeSideMeaning`, `CLAUDE` v1.7 §5).
La conversion est donc une INVERSION explicite : passif ASK → agresseur BUY. L'omettre
retournerait B2 et B3 en silence — exactement ce que D-079 s'employait à empêcher.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Optional

from .. import config
from ..graph.liquidity_sweep import SWEEP_GRAPH, build_sweep_inputs
from ..lsr_engine import build_lsr_inputs, evaluate_lsr
from ..meta import Freshness, MetaField
from ..volume_profile import build_volume_profile
from ..schema import ContextSchema, LiquiditySweepAlert
from .book import MboBook
from .events import MboAction, MboEvent, MboSide
from .session_context import AtrTracker, SessionContext

#: Vérifié en lisant `build_lsr_inputs` (D-085) : la chaîne LSR consomme le sweep, les prints,
#: `absorption`, `aggressor_ratio`, le carnet, `vpoc` et l'order flow. **`svs_score` n'en fait
#: PAS partie** — c'est une entrée de la stratégie SVS de Sony, un autre système. L'annoncer
#: comme « manquant pour le LSR » envoyait l'opérateur chercher une donnée dont le moteur ne
#: veut pas. Plus rien ne manque structurellement au rejeu.
MISSING_FROM_MBO: tuple[str, ...] = ()

#: Entrées du LSR que le MBO ne porte pas telles quelles mais qui se DÉRIVENT du flux.
DERIVED_FROM_FLOW = ("atr_session", "vpoc")

#: Ce que le MBO ne porte pas mais qu'un CONTEXTE DE SÉANCE fournit (D-084) : joint
#: point-in-time depuis une série historique, jamais interrogé « au présent ».
JOINED_FROM_CONTEXT = ("vix", "econ_calendar", "news_state")


class MboLsrDetector:
    """Projette l'état MBO dans le schéma, puis appelle la chaîne LSR existante.

    S'utilise directement comme le `arm` du harnais de rejeu :

        detector = MboLsrDetector()
        outcomes = ReplayHarness().run(events, detector)
    """

    def __init__(self, *, tick_size: float = 0.25, depth: int = 10,
                 max_prints: int = 512, instrument: str = "MES",
                 news_state: Optional[str] = None,
                 context: Optional[SessionContext] = None):
        self.tick = float(tick_size)
        self.depth = int(depth)
        self.instrument = instrument
        #: `None` = calendrier inconnu. La porte F0 est fail-closed sur `SAFETY_UNKNOWN` ; on ne
        #: passe donc PAS `SAFE` par défaut, ce qui reviendrait à lever une protection faute de
        #: données (D-050).
        self.news_state = news_state
        #: Contexte de séance JOINT (D-084). `None` = aucune série fournie : VIX et calendrier
        #: restent ABSENT et les gates continuent de refuser — jamais un défaut inventé.
        self.context = context
        self._atr = AtrTracker()
        #: Volume par NIVEAU de prix (clé entière de tick), accumulé sur la séance rejouée.
        #: Borné par le nombre de NIVEAUX, pas de prints — même doctrine que `engine._vp_levels`.
        self._vp_levels: dict[int, float] = {}
        self._prints: deque = deque(maxlen=max_prints)
        self._seq = 0
        self._armed = 0
        self._refused = 0

    # -- projection --

    def _record_print(self, book: MboBook, event: MboEvent) -> None:
        """Un trade MBO → un print au format du tape. Le côté est INVERSÉ : le carnet raisonne
        en passif consommé, le tape en agresseur."""
        passive = (book.side_of_order(event.order_id)
                   or book._passive_side_from_price(event.price))   # noqa: SLF001 — même paquet
        if passive is None:
            return                                   # côté inrésolvable → aucun print inventé
        self._seq += 1
        self._prints.appendleft({
            "ts": event.ts_event / 1_000_000_000.0,
            "price": event.price,
            "size": event.size,
            "side": "BUY" if passive == MboSide.ASK else "SELL",
            "seq": self._seq,
        })

    def _accumulate_volume(self, event: MboEvent) -> None:
        """Volume par niveau, pour le VPOC. Le profil se DÉRIVE des transactions rejouées : le
        chercher ailleurs donnerait un POC calculé sur d'autres bornes de séance que celles
        qu'on mesure."""
        if not isinstance(event.size, (int, float)) or event.size <= 0:
            return
        key = round(event.price / self.tick)
        if len(self._vp_levels) >= config.VP_MAX_LEVELS and key not in self._vp_levels:
            return                                   # grille bornée, jamais de croissance libre
        self._vp_levels[key] = self._vp_levels.get(key, 0.0) + float(event.size)

    def _vpoc(self) -> Optional[float]:
        """POC du profil accumulé, via `build_volume_profile` — le MÊME calcul que le moteur
        live. En réécrire un ici ferait deux POC pour un seul marché."""
        if not self._vp_levels:
            return None
        profile = build_volume_profile(
            {key * self.tick: vol for key, vol in self._vp_levels.items()},
            self.tick, config.VP_VA_PCT, config.VP_LVN_RATIO, config.VP_MAX_LEVELS)
        return profile.get("poc")

    def build_schema(self, book: MboBook, now: float) -> ContextSchema:
        """`ContextSchema` minimal : carnet et tape FRESH, **le reste laissé ABSENT**. C'est ce
        silence qui fait refuser les gates dépendant de données que le MBO ne porte pas — et
        c'est le comportement voulu (§3)."""
        schema = ContextSchema()
        aggregated = book.to_aggregated_book(depth=self.depth)
        if aggregated.bids and aggregated.asks:
            schema.s1_state.order_book = MetaField(
                value={"bids": [[lvl.price, lvl.size] for lvl in aggregated.bids],
                       "asks": [[lvl.price, lvl.size] for lvl in aggregated.asks]},
                last_update_ts=now, source="mbo_replay", freshness=Freshness.FRESH)
        if self._prints:
            schema.s1_state.tape = MetaField(
                value=list(self._prints), last_update_ts=now, source="mbo_replay",
                freshness=Freshness.FRESH)
        vpoc = self._vpoc()
        if vpoc is not None:
            schema.s1_state.structure.vpoc = MetaField(
                value=vpoc, last_update_ts=now, source="mbo_replay",
                freshness=Freshness.FRESH)
        self._join_context(schema, now)
        return schema

    def _join_context(self, schema: ContextSchema, now: float) -> None:
        """Jointure POINT-IN-TIME (D-084) : à `now`, on ne voit que ce qui était déjà publié à
        `now`. Sans contexte fourni, rien n'est écrit — les champs restent ABSENT et les gates
        refusent, ce qui est le comportement voulu (§3)."""
        if self.context is None:
            return
        vix = self.context.vix_at(now)
        if vix is not None:
            schema.s2_state.cascade.vix = MetaField(
                value=vix, last_update_ts=now, source="session_context",
                freshness=Freshness.FRESH)
        events = self.context.events_known_at(now)
        if events:
            schema.econ_calendar.events = MetaField(
                value=events, last_update_ts=now, source="session_context",
                freshness=Freshness.FRESH)

    # -- interface d'armement (compatible ReplayHarness) --

    def __call__(self, book: MboBook, event: MboEvent) -> Optional[Any]:
        from ..replay_harness import Setup

        if event.action in (MboAction.TRADE, MboAction.FILL):
            self._record_print(book, event)
            # L'ATR se dérive du flux REJOUÉ, pas d'une source externe : une seconde source
            # produirait des barres qui ne coïncideraient pas avec celles qu'on mesure.
            self._atr.observe(event.price, event.ts_event / 1_000_000_000.0)
            self._accumulate_volume(event)

        now = event.ts_event / 1_000_000_000.0
        schema = self.build_schema(book, now)

        # 1. Détection de sweep — le graphe déterministe existant, inchangé.
        sweep_state = SWEEP_GRAPH.invoke(build_sweep_inputs(schema, now))
        if not sweep_state.get("triggered"):
            return None
        alert = sweep_state.get("alert")
        if alert is None:
            return None
        schema.liquidity_sweep.triggered = True
        schema.liquidity_sweep.alert = (alert if isinstance(alert, LiquiditySweepAlert)
                                        else LiquiditySweepAlert(**alert))

        # 2. Évaluation LSR — le moteur existant, inchangé. Il refusera tant que les entrées
        #    absentes du MBO manquent : c'est un refus MOTIVÉ, pas un bug.
        news = (self.context.news_state_at(now) if self.context is not None else None)
        plan = evaluate_lsr(build_lsr_inputs(schema, now,
                                             news_state=news if news is not None
                                             else self.news_state))
        if plan is None:
            self._refused += 1
            return None

        entry, risk = plan.get("executionPlan") or {}, plan.get("executionPlan") or {}
        entry_price = entry.get("entryPrice")
        stop, target = risk.get("stopLoss"), risk.get("takeProfit")
        if entry_price is None or stop is None or target is None:
            self._refused += 1
            return None

        self._armed += 1
        return Setup(
            setup_id=f"mbo-{event.sequence}-{self._armed}",
            side="LONG" if str(plan.get("direction", "")).upper() == "LONG" else "SHORT",
            entry_price=float(entry_price), stop_loss=float(stop), take_profit=float(target),
            qty=float(risk.get("contracts") or 1), armed_ts_ms=now * 1000.0)

    # -- diagnostic --

    def diagnostics(self) -> dict[str, Any]:
        """Pourquoi si peu (ou aucun) setup. Sans ce rapport, une matrice de calibration vide se
        lirait « la stratégie ne se déclenche jamais » alors que la cause peut être « le fichier
        ne porte pas les entrées que les filtres exigent »."""
        return {
            "prints_accumulated": len(self._prints),
            "armed": self._armed,
            "refused_after_sweep": self._refused,
            # Nommées, pas comptées : c'est la LISTE qui est actionnable.
            "inputs_absent_from_mbo": list(MISSING_FROM_MBO),
            "inputs_joined_from_context": (list(JOINED_FROM_CONTEXT) if self.context is not None
                                           else []),
            "inputs_derived_from_flow": list(DERIVED_FROM_FLOW),
            "context": self.context.diagnostics() if self.context is not None else None,
            "atr": self._atr.diagnostics(),
            "vpoc": self._vpoc(),
            "vp_levels": len(self._vp_levels),
            "news_state": self.news_state,
            "tick_size": self.tick,
            "instrument": self.instrument,
            "orderflow_source": config.MICROSTRUCTURE_SOURCE,
        }
