"""Source de microstructure LIVE — la couture, et rien de plus (D-097).

Ce module définit **où** un flux réel se branche, pas comment tel fournisseur parle. Rithmic,
Bookmap et Sierra exigent un SDK propriétaire et des identifiants que ce dépôt n'a pas : écrire
un client qui *simule* une connexion serait le pire des deux mondes — l'apparence d'un connecteur
avec le comportement d'un mock. `CLIENTS` est donc **vide**, et le restera jusqu'à ce qu'un vrai
client existe.

---

**Ce que le terminal demande à un fournisseur, et ce qu'il refuse.**

Deux choses seulement : le **tape** (prints) et le **carnet** (profondeur). Tout le reste —
CVD, absorption, ratio d'agression, VPOC, VAH/VAL/LVN — est calculé **ici** (`app/orderflow/`,
`app/volume_profile.py`).

Un fournisseur qui offre son propre « CVD » serait une seconde vérité sur un nombre qu'on calcule
déjà : deux chiffres du même nom qui divergent, et plus personne pour dire lequel a raison. On
prend la donnée brute, on garde le calcul.

**Le moteur cadence, le client tamponne.** `drain_prints()` rend ce qui s'est accumulé depuis le
dernier appel — même contrat que `ReplayDataSource` : aucun `sleep` ici, c'est le tick du moteur
qui rythme.

**Fail-closed, jamais de repli sur le mock.** Pas de client, client déconnecté, client qui lève →
**on n'écrit rien**. Les champs vieillissent visiblement vers STALE puis ABSENT et Phase 0 bloque
(§3). Retomber sur le mock rendrait l'écran vivant pendant que le flux est mort — exactement ce
que D-093 vient d'interdire.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from ..redis_state import RedisState
from .base import MarketDataSource
from .mock import MOCK_PREFIX

log = logging.getLogger("cholismo.datasource.live")


@runtime_checkable
class MicrostructureClient(Protocol):
    """Ce qu'un connecteur réel doit fournir. Volontairement étroit : plus le port est large,
    plus il est facile d'y faire passer une donnée dérivée qu'on calcule déjà mieux ici."""

    @property
    def vendor(self) -> str:
        """Nom RÉEL du fournisseur (`rithmic`, `bookmap`, …). Il sera estampillé tel quel sur
        chaque lecture : seul un connecteur réel a le droit de porter le nom d'un vendeur
        (contrepartie de D-093)."""

    @property
    def connected(self) -> bool:
        """Faux dès que la session est perdue. Un client qui ment ici rend le fail-closed
        inopérant — c'est la seule propriété dont tout le reste dépend."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    def drain_prints(self) -> list[dict]:
        """Prints accumulés depuis le dernier appel, ordre chronologique. Liste vide = rien de
        neuf (marché calme), ce qui n'est PAS la même chose qu'une déconnexion — c'est
        `connected` qui porte cette information."""

    def order_book(self) -> Optional[dict]:
        """Meilleur état connu du carnet, ou `None` si inconnu. `None` plutôt qu'un carnet vide :
        un carnet à zéro niveau se lirait « plus aucune liquidité », ce qui est une mesure."""


#: Fabriques de clients, par nom. **VIDE** : aucun connecteur n'existe dans ce dépôt. Une entrée
#: ici signifie « ce fournisseur est réellement joignable », et rien d'autre ne doit y figurer.
CLIENTS: dict[str, Callable[[], MicrostructureClient]] = {}


class LiveDataSource(MarketDataSource):
    """Publie tape et carnet d'un client réel. N'invente rien, ne comble rien."""

    def __init__(self, client: MicrostructureClient, *, source_name: str,
                 tape_maxlen: int = 200) -> None:
        vendor = getattr(client, "vendor", "") or ""
        if not vendor:
            raise ValueError("client de microstructure sans nom de fournisseur — une lecture "
                             "doit pouvoir dire d'où elle vient (§3)")
        if vendor.startswith(MOCK_PREFIX):
            raise ValueError(f"un client réel ne peut pas s'estampiller « {vendor} » : le "
                             f"préfixe « {MOCK_PREFIX} » est réservé aux lectures simulées (D-093)")
        if vendor != source_name:
            # Sinon `/sources`, la table de provenance et les bascules de coupure nommeraient
            # une source que personne n'écrit : la coupure ne couperait rien.
            raise ValueError(
                f"identité incohérente : le client dit « {vendor} », la configuration attend "
                f"« {source_name} ». Les bascules de coupure porteraient à faux.")
        self._client = client
        self._source = vendor
        self._tape: list[dict] = []
        self._maxlen = max(1, tape_maxlen)
        self._seq = 0

    @property
    def vendor(self) -> str:
        return self._source

    async def start(self) -> None:
        await self._client.connect()

    async def stop(self) -> None:
        try:
            await self._client.close()
        except Exception:
            log.exception("fermeture du client de microstructure en échec")

    # -- MarketDataSource --

    async def tick_fast(self, state: RedisState) -> None:
        """Publie ce que le client a réellement livré. Toute défaillance = silence.

        Le silence est la bonne réponse parce qu'il est VISIBLE : `last_update_ts` cesse
        d'avancer, l'âge court, le champ passe STALE puis ABSENT. Un `except` qui écrirait une
        dernière valeur connue rendrait la panne invisible.
        """
        if not await self._up(state):
            return
        try:
            prints = self._client.drain_prints()
            book = self._client.order_book()
        except Exception:
            log.exception("client de microstructure en échec — rien n'est publié (fail-closed)")
            return

        published_ts = self._append(prints)
        if published_ts is not None:
            await state.write_raw("tape", list(self._tape), self._source, ts=published_ts)
        if isinstance(book, dict) and book:
            # Le carnet est horodaté de MAINTENANT et non du dernier print : un marché sans
            # transaction a quand même un carnet vivant, et le dater d'un print ancien le ferait
            # vieillir à tort.
            await state.write_raw("order_book", book, self._source, ts=_now())

    async def tick_slow(self, state: RedisState) -> None:
        """Un flux de microstructure ne porte aucune macro. Rien n'est écrit — les blocs lents
        vieillissent visiblement, ce qui est la vérité (§3)."""
        return None

    # -- internes --

    async def _up(self, state: RedisState) -> bool:
        if not getattr(self._client, "connected", False):
            return False
        try:
            return await state.source_up(self._source)
        except Exception:
            log.exception("état de coupure illisible — fail-closed")
            return False

    def _append(self, prints: Any) -> Optional[float]:
        """Ajoute les prints exploitables au tape roulant. Rend l'horodatage du dernier, ou
        `None` si rien d'exploitable n'est arrivé — un tape republié à l'identique avec un
        horodatage neuf ferait passer un flux mort pour un flux calme."""
        if not isinstance(prints, list):
            return None
        last_ts: Optional[float] = None
        for p in prints:
            if not isinstance(p, dict):
                continue
            ts, price, size = p.get("ts"), p.get("price"), p.get("size")
            if ts is None or price is None or size is None:
                continue                       # un print incomplet n'est pas un print
            try:
                ts_f = float(ts)
            except (TypeError, ValueError):
                continue
            self._seq += 1
            self._tape.append({"ts": ts_f, "price": price, "size": size,
                               "side": p.get("side"), "seq": self._seq})
            last_ts = ts_f
        if len(self._tape) > self._maxlen:
            del self._tape[:-self._maxlen]
        return last_ts


def _now() -> float:
    import time
    return time.time()


def resolve_client(name: str) -> Optional[MicrostructureClient]:
    """Fabrique le client nommé, ou `None` si aucun connecteur ne porte ce nom.

    `None` déclenche le repli documenté du démarrage (source simulée, avertissement explicite) —
    et **jamais** un client factice : un connecteur absent doit se voir, pas se remplacer.
    """
    factory = CLIENTS.get(name)
    if factory is None:
        return None
    return factory()
