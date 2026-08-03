"""Niveau VIX et régime de volatilité — la source du filtre F3 (D-062).

**Ce qui manquait vraiment.** Le régime F3 existe déjà et il est bon : `update_regime`
(hystérésis D4, `reference/youssef/01`) plus le veto `config.VIX_CRIT` marqué AUTORITÉ. Ce qui
n'existait pas, c'est une **source** : le champ `vix` n'était rempli que par le mock, et en
replay il vieillissait vers ABSENT. Ce module est la source manquante.

### Le constat gênant qu'il faut poser d'emblée
Le dépôt porte **deux systèmes de seuils VIX qui ne coïncident pas** :
- `VIX_CRIT = 30.0` — **AUTORITÉ**, veto dur : Phase 0, orchestrateur, scoring, live_mode ;
- l'hystérésis D4 — GREEN→YELLOW 18, YELLOW→ORANGE 26, ORANGE→RED 37 (sorties 14 / 22 / 33).

Un VIX à 32 est donc **un veto Phase 0 mais seulement ORANGE** au sens D4. Ce n'est pas
forcément une contradiction (un veto d'exécution et un multiplicateur de sizing ne répondent pas
à la même question), mais c'est un écart réel que personne n'avait écrit. `get_vix_regime()`
rend donc **les deux faits séparément** — `tier` ET `veto` — et n'invente surtout pas un
troisième jeu de seuils qui aurait « concilié » les deux en douce. Arbitrage à trancher par le
propriétaire de la spec ; en attendant, les deux couches gardent chacune la sienne, inchangée.

### Trois sources, par ordre d'honnêteté décroissante
1. `FredVix` — VIXCLS chez FRED, ligne **C1** déjà au registre (D-057), client déjà écrit. Sa
   limite est nommée, pas maquillée : c'est une **clôture QUOTIDIENNE**. Lue en séance, elle
   décrit hier. `as_of` porte la date de l'observation et l'horodatage publié est celui de
   l'observation, pas `now` — la couche de fraîcheur fait alors son travail toute seule.
2. `TermStructureVix` — lit le ténor 30 jours de `vol_term_structure`, déjà dans le schéma.
   Aucun réseau, et c'est la valeur que le terminal affiche déjà par ailleurs.
3. `StaticVix` — valeur fixe configurable, pour travailler hors ligne. Marquée `fallback`, donc
   `EXTERNAL_FALLBACK` jusque dans le panneau : un VIX simulé indiscernable d'un VIX mesuré
   serait le seul état vraiment dangereux (leçon REPLAY, D-058).
"""
from __future__ import annotations

from typing import Any, Optional

from .. import config
from ..providers.client import SeriesResult
from ..providers.fred import FredClient
from ..strategies.youssef import HYSTERESIS, update_regime
from .contracts import VixFetch, plausible_vix

FRED_VIX_SERIES = "VIXCLS"


class VixRegime:
    """Le régime F3, en deux faits SÉPARÉS parce que le dépôt les définit séparément.

    `tier` vient de l'hystérésis D4 (état, donc dépend du précédent) ; `veto` du seuil AUTORITÉ
    `VIX_CRIT`. Les fusionner en un seul mot (« HIGH_VOL ») perdrait justement l'information
    qu'ils ne s'accordent pas — un VIX à 32 est un veto ET seulement ORANGE.
    """

    __slots__ = ("tier", "veto", "vix", "source", "motif")

    def __init__(self, tier: str, veto: bool, vix: Optional[float], source: str,
                 motif: str) -> None:
        self.tier = tier
        self.veto = veto
        self.vix = vix
        self.source = source
        self.motif = motif

    @property
    def resume(self) -> str:
        if self.vix is None:
            return f"VIX indisponible — {self.motif}"
        veto = f" · VETO (> {config.VIX_CRIT:.0f})" if self.veto else ""
        return f"VIX {self.vix:.2f} · palier D4 {self.tier}{veto} · {self.source}"

    def as_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "veto": self.veto, "vix": self.vix,
                "source": self.source, "motif": self.motif, "resume": self.resume}


def get_vix_regime(vix: Optional[float], *, previous_tier: str = "GREEN",
                   source: str = "", kurtosis: Optional[float] = None) -> VixRegime:
    """Régime F3 — **délègue** l'hystérésis à `update_regime` et le veto à `VIX_CRIT`.

    `previous_tier` est obligatoire par nature : l'hystérésis D4 a des zones mortes (entrée ≠
    sortie), donc le palier dépend d'où l'on vient. Un classificateur « sans mémoire » écrit ici
    donnerait un palier différent du reste du terminal aux frontières — deux réponses à la même
    question, pour la seule commodité d'une signature plus courte.

    VIX absent → le palier NE BOUGE PAS (comportement de `update_regime`) et `veto` reste faux :
    l'absence de donnée n'est pas un motif de veto ici, c'est Phase 0 qui refuse une entrée
    absente en amont (§3).
    """
    tier = update_regime(previous_tier, vix, kurtosis)
    if vix is None:
        return VixRegime(tier, False, None, source or "aucune",
                         "aucune lecture — palier conservé, aucun veto prononcé ici")
    veto = float(vix) > config.VIX_CRIT
    e = HYSTERESIS
    motif = (f"seuils D4 {e['green_yellow']['entry']}/{e['yellow_orange']['entry']}/"
             f"{e['orange_red']['entry']} (sorties {e['green_yellow']['exit']}/"
             f"{e['yellow_orange']['exit']}/{e['orange_red']['exit']}) · "
             f"veto AUTORITÉ à {config.VIX_CRIT:.0f}")
    return VixRegime(tier, veto, float(vix), source or "inconnue", motif)


class FredVix:
    """VIXCLS chez FRED — la seule source VÉRIFIÉE du lot (ligne C1 au registre, D-057).

    Délègue au `FredClient` existant : réécrire ici un appel HTTP FRED donnerait deux façons
    d'interroger le même fournisseur, qui divergeraient à la première correction.
    """

    name = "FRED VIXCLS"

    def __init__(self, *, api_key: Optional[str] = None, client: Optional[FredClient] = None,
                 fetcher: Optional[Any] = None) -> None:
        self._client = client if client is not None else FredClient(api_key=api_key,
                                                                    fetcher=fetcher)
        self._api_key = api_key

    def unavailable_reason(self) -> Optional[str]:
        cle = config.FRED_API_KEY if self._api_key is None else self._api_key
        if not cle:
            return ("clé FRED absente — renseigner FRED_API_KEY, ou laisser la chaîne basculer "
                    "sur la structure de vol du terminal")
        return None

    def fetch(self, *, now: float) -> VixFetch:
        motif = self.unavailable_reason()
        if motif is not None:
            return VixFetch(provider=self.name, error=motif)
        res: SeriesResult = self._client.fetch(FRED_VIX_SERIES)
        if res.series is None:
            # LIMITE CONNUE, héritée de `providers` (D-057, `_finish`) : « rien de lisible =
            # illisible, pas vide » y est un choix délibéré. Conséquence ici — un jour de
            # fermeture, VIXCLS ne publie que des « . », tout est écarté, et le motif remonte
            # « illisible ». On n'invente pas la distinction qu'on n'a pas ; on ajoute l'indice
            # qui évite d'aller chercher une panne là où il y a un jour férié.
            return VixFetch(provider=self.name,
                            error=f"{res.error or 'aucune observation'} — sur VIXCLS, la cause "
                                  "la plus fréquente est un jour de fermeture (valeurs « . »), "
                                  "pas une panne")
        obs = res.series.observations
        if not obs:
            return VixFetch(provider=self.name, error="série lue mais AUCUNE observation")
        dernier = obs[-1]
        valeur = plausible_vix(dernier.value)
        if valeur is None:
            return VixFetch(provider=self.name,
                            error=f"valeur hors bornes de plausibilité ({dernier.value!r}) — "
                                  "champ mal mappé ou unité inattendue, aucune conversion tentée")
        # `observed_ts` reste `now` : c'est l'instant où NOUS avons lu. La date de la donnée part
        # dans `as_of`, et c'est elle qui dit que la valeur peut décrire hier.
        return VixFetch(provider=self.name, value=valeur, observed_ts=now,
                        verified=True, as_of=dernier.date)


class TermStructureVix:
    """Repli sans réseau : le ténor 30 jours de `vol_term_structure`, déjà dans le schéma.

    Ce n'est pas une source externe au sens strict — c'est la valeur que le terminal affiche
    déjà. La retenir ici évite d'ouvrir une socket pour un chiffre qu'on a sous la main, et
    garantit qu'aucun panneau ne montre deux VIX différents au même instant.
    """

    name = "structure de vol (30j)"

    def __init__(self, reader: Any, *, tenor: str = "VIX") -> None:
        # `reader()` rend la valeur brute de `vol_term_structure` (ou None). Injecté : ce module
        # ne connaît ni Redis ni le schéma, et reste testable sans les deux.
        self._reader = reader
        self._tenor = tenor

    def unavailable_reason(self) -> Optional[str]:
        if self._reader is None:
            return "aucun lecteur de structure de vol fourni"
        return None

    def fetch(self, *, now: float) -> VixFetch:
        try:
            brut = self._reader()
        except Exception as exc:                      # un lecteur défaillant n'emporte pas la chaîne
            return VixFetch(provider=self.name, fallback=True,
                            error=f"lecture impossible ({type(exc).__name__})")
        valeur = plausible_vix(_tenor_value(brut, self._tenor))
        if valeur is None:
            return VixFetch(provider=self.name, fallback=True,
                            error=f"ténor {self._tenor} absent ou hors bornes dans "
                                  "vol_term_structure")
        return VixFetch(provider=self.name, value=valeur, observed_ts=now,
                        verified=True, fallback=True)


def _tenor_value(brut: object, tenor: str) -> Optional[float]:
    """Extrait un ténor de `vol_term_structure`, quelle que soit la forme retenue par la source
    (liste de points ou dictionnaire). Aucune interpolation : un ténor absent est absent."""
    if isinstance(brut, dict):
        direct = brut.get(tenor)
        if isinstance(direct, (int, float)) and not isinstance(direct, bool):
            return float(direct)
        points: object = brut.get("points") or brut.get("tenors")
    else:
        points = brut
    if isinstance(points, list):
        for p in points:
            if isinstance(p, dict) and str(p.get("tenor") or p.get("name")).upper() == tenor:
                v = p.get("value") if "value" in p else p.get("iv")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return float(v)
    return None


class StaticVix:
    """Valeur fixe configurable — pour travailler hors ligne, jamais pour décider.

    Toujours `fallback=True` : ce qui en sort porte `EXTERNAL_FALLBACK` jusque dans le panneau.
    Un VIX simulé qu'on ne distingue pas d'un VIX mesuré est exactement l'état contre lequel le
    drapeau REPLAY a été conservé (D-058).
    """

    name = "VIX simulé"

    def __init__(self, value: Optional[float]) -> None:
        self._value = value

    def unavailable_reason(self) -> Optional[str]:
        if self._value is None:
            return "aucune valeur simulée configurée — renseigner EXTERNAL_VIX_STATIC"
        if plausible_vix(self._value) is None:
            return f"valeur simulée hors bornes de plausibilité ({self._value!r})"
        return None

    def fetch(self, *, now: float) -> VixFetch:
        motif = self.unavailable_reason()
        if motif is not None:
            return VixFetch(provider=self.name, error=motif, fallback=True)
        return VixFetch(provider=self.name, value=plausible_vix(self._value),
                        observed_ts=now, verified=True, fallback=True)


class ChainedVix:
    """Source principale puis replis, dans l'ordre. Voir `ChainedCalendar` — même contrat, même
    exigence : le compte rendu dit qui a servi ET pourquoi les autres n'ont pas."""

    name = "chaîne"

    def __init__(self, providers: list[Any]) -> None:
        self._providers = list(providers)
        self.attempts: list[str] = []

    def unavailable_reason(self) -> Optional[str]:
        if not self._providers:
            return "aucune source VIX configurée"
        motifs = [p.unavailable_reason() for p in self._providers]
        if all(m is not None for m in motifs):
            return " · ".join(str(m) for m in motifs)
        return None

    def fetch(self, *, now: float) -> VixFetch:
        self.attempts = []
        dernier: Optional[VixFetch] = None
        for p in self._providers:
            try:
                motif = p.unavailable_reason()
                if motif is not None:
                    self.attempts.append(f"{p.name} : indisponible — {motif}")
                    continue
                res: VixFetch = p.fetch(now=now)
            except Exception as exc:
                self.attempts.append(f"{p.name} : a levé ({type(exc).__name__}) — écarté")
                continue
            self.attempts.append(res.resume)     # `resume` porte déjà le nom du fournisseur
            if res.ok:
                return res
            dernier = res
        if dernier is not None:
            return dernier
        return VixFetch(provider=self.name,
                        error=self.unavailable_reason() or "aucune source utilisable")
