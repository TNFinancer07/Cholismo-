"""`MacroSeriesProvider` — le paquet `providers` branché sur le `ContextSchema` (D-063).

53 séries sont interrogeables depuis D-057 et **n'alimentaient rien**. Ce module est le pont
manquant : il fetche les séries, calcule les champs du canal lent avec les formules DÉJÀ écrites,
et publie sous la source `macro_feed` que le moteur attend — zéro ligne modifiée dans `engine.py`.

### La table de recettes, et pourquoi sa faisabilité est DÉRIVÉE
`RECIPES` déclare, pour chaque champ du schéma, comment il se construit depuis des clés du
registre. Elle ne dit JAMAIS elle-même si un champ est alimentable : ça se **déduit** du registre
(`fetch_block_reason`, `has_rest_endpoint`, existence des jambes) au moment de l'appel. Une
faisabilité écrite à la main mentirait le jour où un identifiant C2 est relevé — ou pire,
resterait « OK » après qu'une source soit passée C3.

### Ce que ça donne aujourd'hui, sans rien maquiller
**Un seul champ est réellement alimentable : `real_rates`** (DFII10, ligne C1). Les quinze autres
sont bloqués, chacun pour une raison NOMMÉE et vérifiable :
- `d1` — `cascade.aggregate` refuse de renormaliser sur les composantes présentes ; or `lei`,
  `sahm` et `ip` n'ont **aucune jambe BASE** au registre, donc aucune divergence. Un D1 calculé
  sur 45 % du poids se lirait comme un D1 complet ;
- `d2`/`d3` — ABSORBÉS par Arb1/Arb2 (poids 0 dans `DIMENSIONS`) : leur donner un score propre le
  ferait compter deux fois ;
- `d4` — `d4_coeff` est un PARAMÈTRE à calibrer, qu'aucune requête ne fournira ;
- `d5`, `beer_z` — `nfa` et `tot` sont C2 (identifiant à relever) ;
- `taylor_ois_delta` — `r_star_us` C2, `r_star_ez` C3 ;
- `phillips_tips_delta` — `beta_phillips` est un paramètre à calibrer ;
- `leading_turn` — bloqué par `oecd_cli` (C2) ; `rr_zscore` — par `bundei_real` (C2) ;
- `bridgewater_matrix`, `g_momentum`, `pi_momentum`, `carry_net`, `cycle_div_delta`,
  `spot_momentum` — **aucune formule figée** dans le référentiel. Le mock les fabrique ; en
  inventer une ici la ferait passer pour de la mesure (CLAUDE §8, §11).

Ce n'est pas un échec du câblage : c'est le câblage qui dit la vérité. Le jour où les six lignes
C2 sont relevées, les champs concernés s'allument **sans toucher à ce fichier**.

### Discipline de quota
Seules les séries dont dépend une recette FAISABLE sont interrogées. Fetcher les 53 pour n'en
utiliser qu'une brûlerait le quota du fournisseur pour rien, et masquerait l'unique appel utile
dans le bruit.

Deux étages, comme `ExternalDataModule` : worker async (fetch en `asyncio.to_thread`, §7) et
accesseurs synchrones purs. Cache fossile → rien n'est publié, le champ vieillit visiblement.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Callable, Mapping, Optional

from ..providers import cascade
from ..providers.catalog import BY_KEY, D1_WEIGHTS, fetch_block_reason, zscore_window
from ..providers.client import SeriesResult, client_for
from ..providers.connectors import SeriesBlocked, has_rest_endpoint
from ..redis_state import RedisState

log = logging.getLogger("cholismo.macro_series")

MACRO_SOURCE = "macro_feed"


@dataclass(frozen=True)
class Component:
    """Une composante de cascade : `div = z(base) − z(quote)`. Une jambe absente est déclarée
    `None` — c'est ce qui rend le blocage LISIBLE au lieu de le faire découvrir à l'exécution."""
    name: str
    base: Optional[str]
    quote: Optional[str]


@dataclass(frozen=True)
class Recipe:
    """Comment un champ du schéma se construit depuis le registre. Ne déclare AUCUNE
    faisabilité : elle se déduit (`blocage()`)."""
    field: str
    kind: str                                    # DIRECT · CASCADE · SANS_FORMULE
    series: tuple[str, ...] = ()                 # DIRECT : une seule clé
    components: tuple[Component, ...] = ()       # CASCADE
    weights: Mapping[str, float] = dc_field(default_factory=dict)
    note: str = ""                               # motif quand `kind == SANS_FORMULE`

    def keys(self) -> tuple[str, ...]:
        if self.kind == "DIRECT":
            return self.series
        return tuple(k for c in self.components for k in (c.base, c.quote) if k)

    def blocage(self, registry: Optional[dict[str, Any]] = None) -> Optional[str]:
        """`None` = alimentable. Sinon le motif, DÉDUIT du registre — jamais écrit à la main.

        `registry` permet d'évaluer contre un registre HYPOTHÉTIQUE : c'est ce qui laisse
        `providers.releve` répondre à « si je relève cet identifiant, qu'est-ce qui s'allume ? »
        sans monkey-patcher quoi que ce soit, ni dupliquer cette logique ailleurs.
        """
        table = BY_KEY if registry is None else registry
        if self.kind == "SANS_FORMULE":
            return self.note
        if self.kind == "DIRECT" and len(self.series) != 1:
            return (f"recette DIRECT mal formée : {len(self.series)} série(s) déclarée(s), une "
                    "seule est attendue")
        if self.kind == "CASCADE":
            orphelines = [c.name for c in self.components if not (c.base and c.quote)]
            if orphelines:
                return (f"jambe manquante pour {', '.join(sorted(orphelines))} — sans les deux "
                        "jambes il n'y a pas de divergence, et le score n'est pas renormalisé "
                        "sur les composantes présentes")
        for key in self.keys():
            if key not in table:
                return f"clé absente du registre : {key}"
            motif = fetch_block_reason(key, registry=table)
            if motif is not None:
                return f"{key} — {motif}"
            if not has_rest_endpoint(key):
                return f"{key} — aucun point d'accès REST"
        return None


# Composantes de D1 telles que `D1_WEIGHTS` les nomme. `lei`, `sahm` et `ip` n'ont AUCUNE jambe
# BASE (zone euro) au registre : la divergence n'existe pas, et `cascade.aggregate` le refusera.
_D1 = (
    Component("pmi", "pmi_ez", "pmi_us"),
    Component("gap", "output_gap_ez", "output_gap_us"),
    Component("lei", None, "lei"),
    Component("sahm", None, "sahm"),
    Component("ip", None, "ip"),
)

_SANS_FORMULE = ("aucune formule figée au référentiel — le mock la fabrique ; en inventer une "
                 "ici la ferait passer pour de la mesure (CLAUDE §8/§11)")

RECIPES: tuple[Recipe, ...] = (
    Recipe("real_rates", "DIRECT", series=("dfii10",),
           note="rendement réel TIPS 10 ans (US)"),
    Recipe("d1", "CASCADE", components=_D1, weights=D1_WEIGHTS),
    Recipe("d2", "SANS_FORMULE",
           note="D2 est ABSORBÉ par Arb1 (poids 0 dans DIMENSIONS) — lui donner un score propre "
                "le ferait compter deux fois"),
    Recipe("d3", "SANS_FORMULE",
           note="D3 est ABSORBÉ par Arb2 (poids 0 dans DIMENSIONS) — même double compte"),
    Recipe("d4", "SANS_FORMULE",
           note="`d4_coeff` est un PARAMÈTRE à calibrer (60 trades) — aucune requête ne le "
                "fournira, et l'incohérence `d4_red_coeff` reste ouverte"),
    Recipe("d5", "CASCADE",
           components=(Component("rdiff", "rdiff", "rdiff"), Component("nfa", "nfa", "nfa"),
                       Component("tot", "tot", "tot")),
           weights={"rdiff": 0.4, "nfa": 0.3, "tot": 0.3}),
    Recipe("taylor_ois_delta", "SANS_FORMULE",
           note="Arb1 exige un taux neutre : `r_star_us` est C2 (identifiant à relever) et "
                "`r_star_ez` est C3 (ne pas commencer)"),
    Recipe("phillips_tips_delta", "SANS_FORMULE",
           note="Arb2 exige `beta_phillips`, PARAMÈTRE à calibrer (60 trades)"),
    Recipe("beer_z", "CASCADE",
           components=(Component("nfa", "nfa", "nfa"), Component("tot", "tot", "tot")),
           weights={"nfa": 0.5, "tot": 0.5}),
    Recipe("leading_turn", "DIRECT", series=("oecd_cli",)),
    Recipe("rr_zscore", "DIRECT", series=("ilsw_ez",)),
    Recipe("bridgewater_matrix", "SANS_FORMULE",
           note="matrice 5×6 : aucun axe ni aucune définition d'intensité au référentiel — "
                "seul le mock en produit une"),
    Recipe("g_momentum", "SANS_FORMULE", note=_SANS_FORMULE),
    Recipe("pi_momentum", "SANS_FORMULE", note=_SANS_FORMULE),
    Recipe("carry_net", "SANS_FORMULE", note=_SANS_FORMULE),
    Recipe("cycle_div_delta", "SANS_FORMULE", note=_SANS_FORMULE),
    Recipe("spot_momentum", "SANS_FORMULE",
           note="dérivé de `dexuseu` (C1, disponible) mais AUCUN horizon de momentum n'est "
                "défini — choisir la fenêtre ici serait choisir le résultat"),
)

BY_FIELD: dict[str, Recipe] = {r.field: r for r in RECIPES}
# Champs dont ce provider devient PROPRIÉTAIRE : uniquement ceux qu'il alimente RÉELLEMENT.
# Revendiquer un champ qu'on ne remplit pas priverait le stack démo de son mock pour rien.
OWNED_FIELDS: tuple[str, ...] = tuple(r.field for r in RECIPES if r.blocage() is None)


@dataclass
class FieldValue:
    """Ce qu'une recette a produit — ou pourquoi rien."""
    field: str
    value: Optional[Any] = None
    observed_ts: Optional[float] = None
    motif: str = ""
    series_used: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def resume(self) -> str:
        if not self.ok:
            return f"{self.field} : AUCUNE VALEUR — {self.motif}"
        detail = f" (depuis {', '.join(self.series_used)})" if self.series_used else ""
        return f"{self.field} = {self.value}{detail}"


class MacroSeriesProvider:
    """Pont registre → `ContextSchema`. Voir la docstring du module pour les invariants."""

    def __init__(self, *, refresh_s: float = 6 * 3600.0, max_age_s: float = 36 * 3600.0,
                 clock: Callable[[], float] = time.time,
                 fetcher: Optional[Callable[[str], SeriesResult]] = None) -> None:
        # Cadence LONGUE par défaut : ces séries sont quotidiennes au mieux, souvent mensuelles.
        # Les interroger toutes les minutes brûlerait le quota pour relire le même chiffre.
        self._refresh_s = refresh_s
        self._max_age_s = max_age_s
        self._clock = clock
        self._fetcher = fetcher                  # injecté : aucun test n'ouvre de socket
        self._cache: dict[str, tuple[FieldValue, float]] = {}
        self._echecs: dict[str, str] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._state: Optional[RedisState] = None
        self._lock = asyncio.Lock()

    # -- ce qu'on interroge : uniquement ce qui sert --

    @staticmethod
    def required_series() -> tuple[str, ...]:
        """Séries dont dépend une recette FAISABLE. Fetcher les 53 pour n'en utiliser qu'une
        brûlerait le quota et noierait l'unique appel utile dans le bruit."""
        besoin: list[str] = []
        for r in RECIPES:
            if r.blocage() is None:
                besoin.extend(k for k in r.keys() if k not in besoin)
        return tuple(besoin)

    # -- étage async --

    async def start(self, state: Optional[RedisState] = None) -> None:
        self._state = state
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh()
                if self._state is not None:
                    await self.publish(self._state)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("rafraîchissement macro échoué (le cache vieillit, §3)")
            await asyncio.sleep(max(60.0, self._refresh_s))

    async def refresh(self) -> dict[str, str]:
        async with self._lock:
            return await self._refresh()

    async def _refresh(self) -> dict[str, str]:
        now = float(self._clock())
        brutes = await asyncio.to_thread(self._fetch_all)
        bilan: dict[str, str] = {}
        for recette in RECIPES:
            if recette.blocage() is not None:
                continue                          # rien à tenter : le registre l'interdit
            valeur = _compute(recette, brutes, now)
            bilan[recette.field] = valeur.resume
            if valeur.ok:
                self._cache[recette.field] = (valeur, now)
        return bilan

    def _fetch_all(self) -> dict[str, SeriesResult]:
        """Interrogation SYNCHRONE des séries requises, appelée dans un thread. Un échec est
        enregistré par série : une source morte n'emporte pas les autres."""
        out: dict[str, SeriesResult] = {}
        self._echecs = {}
        for key in self.required_series():
            try:
                if self._fetcher is not None:
                    out[key] = self._fetcher(key)
                    continue
                # `fetch_catalog` est désormais DÉCLARÉ sur `HttpSeriesClient` (D-064) :
                # plus de `cast`, le typage vérifie l'appel.
                out[key] = client_for(key).fetch_catalog(key)
            except SeriesBlocked as exc:
                # Refus de POLITIQUE, distinct d'une condition de donnée (D-050) : registre qui a
                # changé, ou clé d'API absente. Le worker ne meurt PAS — le tuer priverait la
                # macro de tout, avec une trace de pile, là où le champ doit simplement rester
                # ABSENT. Le motif est conservé tel quel : il dit déjà quoi faire.
                self._echecs[key] = f"refus de politique — {exc}"
            except Exception as exc:              # réseau, parsing, fournisseur défaillant
                self._echecs[key] = f"{type(exc).__name__} — série non récupérée"
        return out

    # -- étage sync : accesseurs PURS --

    def _frais(self, champ: str, now: float) -> Optional[FieldValue]:
        entree = self._cache.get(champ)
        if entree is None or not isinstance(now, (int, float)) or not math.isfinite(now):
            return None
        valeur, ts = entree
        if not math.isfinite(ts) or ts > now or now - ts > self._max_age_s:
            return None                           # souvenir, pas donnée
        return valeur

    def value(self, champ: str, now: float) -> Optional[Any]:
        v = self._frais(champ, now)
        return None if v is None else v.value

    async def publish(self, state: RedisState, now: Optional[float] = None) -> list[str]:
        """Écrit sous `macro_feed`. Un champ non calculé n'est PAS écrit : il vieillit vers
        ABSENT, ce qui est la vérité — bien mieux qu'un zéro qui a l'air d'une mesure."""
        maintenant = float(self._clock()) if now is None else float(now)
        ecrits: list[str] = []
        for champ in OWNED_FIELDS:
            v = self._frais(champ, maintenant)
            if v is None or v.value is None:
                continue
            await state.write_raw(champ, v.value, MACRO_SOURCE,
                                  ts=v.observed_ts if v.observed_ts is not None else maintenant,
                                  flags=["MACRO_SERIES"])
            ecrits.append(champ)
        return ecrits

    def state_dict(self, now: float) -> dict[str, Any]:
        champs = []
        for r in RECIPES:
            blocage = r.blocage()
            v = self._frais(r.field, now) if blocage is None else None
            champs.append({"field": r.field, "kind": r.kind,
                           "alimentable": blocage is None,
                           "valeur": None if v is None else v.value,
                           "motif": blocage or ("" if v is not None else "pas encore calculé"),
                           "series": list(r.keys())})
        return {"champs": champs, "series_requises": list(self.required_series()),
                "echecs": dict(self._echecs),
                "alimentes": [c["field"] for c in champs if c["valeur"] is not None]}


# --- calcul : les formules existantes, jamais une nouvelle --------------------------------------

def _observations(res: Optional[SeriesResult]) -> list[float]:
    if res is None or res.series is None:
        return []
    return [o.value for o in res.series.observations]


def _compute(recette: Recipe, brutes: Mapping[str, SeriesResult], now: float) -> FieldValue:
    if recette.kind == "DIRECT":
        cle = recette.series[0]
        obs = _observations(brutes.get(cle))
        if not obs:
            res = brutes.get(cle)
            return FieldValue(recette.field,
                              motif=f"{cle} : {(res.error if res else None) or 'aucune observation'}")
        return FieldValue(recette.field, value=float(obs[-1]), observed_ts=now,
                          series_used=(cle,))
    if recette.kind == "CASCADE":
        divergences: dict[str, Optional[float]] = {}
        for c in recette.components:
            zb = cascade.zscore(_observations(brutes.get(c.base or "")),
                                window=zscore_window(c.base or ""))
            zq = cascade.zscore(_observations(brutes.get(c.quote or "")),
                                window=zscore_window(c.quote or ""))
            divergences[c.name] = cascade.divergence(zb.value, zq.value)
        # `timing_factor` n'est PAS deviné : sans lui, `aggregate` refuse — et c'est correct.
        out = cascade.aggregate(divergences, recette.weights, timing_factor=1.0)
        if out.score is None:
            return FieldValue(recette.field, motif=out.motif)
        return FieldValue(recette.field, value=round(out.score, 4), observed_ts=now,
                          series_used=recette.keys())
    return FieldValue(recette.field, motif=recette.blocage() or "recette sans calcul")


# --- rapport lisible : `python -m app.external.macro_series` ------------------------------------

_GLYPHES = {"ok": "✓", "bloque": "✕"}
_LARGEUR = 118


def _couper(texte: str, n: int) -> str:
    """Troncature VISIBLE — un motif amputé en silence se lit comme un motif entier."""
    return texte if len(texte) <= n else texte[:n - 1] + "…"


def rapport() -> str:
    """Ce que le pont alimente, ce qu'il n'alimente pas, et POURQUOI. Lecture seule, aucun appel
    réseau : c'est une lecture du registre, pas une interrogation des fournisseurs."""
    lignes = [
        "CHOLISMO · pont registre → ContextSchema (D-063)",
        f"{len(RECIPES)} champs du canal lent · {len(OWNED_FIELDS)} ALIMENTÉ(S) aujourd'hui · "
        f"{len(MacroSeriesProvider.required_series())} série(s) interrogée(s)",
        "  ✓ alimenté   ✕ bloqué — le motif est TOUJOURS affiché, aucun statut ne tient au glyphe",
        "  lecture seule · aucun appel réseau · aucun ordre (§2.1)",
        "",
    ]
    for r in RECIPES:
        b = r.blocage()
        glyphe = _GLYPHES["ok"] if b is None else _GLYPHES["bloque"]
        detail = b or (f"depuis {', '.join(r.keys())}" + (f" · {r.note}" if r.note else ""))
        lignes.append(_couper(f"  {glyphe} {r.field:<20} {r.kind:<14} {detail}", _LARGEUR))
    lignes += [
        "",
        "Ce que ça veut dire — et ce que ça ne veut pas dire",
        "─" * 60,
        "  Un champ bloqué n'est pas une panne : c'est le registre qui refuse de laisser inventer",
        "  une valeur. Les champs non alimentés restent ABSENT dans le schéma (§3), et le panneau",
        "  affiche PAS DE DONNÉES plutôt qu'un chiffre qui aurait l'air d'une mesure.",
        "  Les six lignes C2 relevées au catalogue débloqueront leurs champs SANS toucher ce fichier.",
    ]
    return "\n".join(lignes)


def main(argv: Optional[list[str]] = None) -> int:
    print(rapport())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
