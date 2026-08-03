"""Contrats des sources externes — Niveau 3, hors flux microstructure (D-062).

Ce paquet alimente deux champs du `ContextSchema` que **rien ne remplissait depuis une source
réelle** : `macro_releases` (calendrier F5) et `vix` (régime F3). Les deux existaient déjà en
mock uniquement ; en mode replay, `tick_slow` n'écrivant rien, ils vieillissaient vers ABSENT.

**Ce que ce paquet ne fait PAS, et pourquoi.** Il ne décide rien. Le verdict F5 reste
`macro_risk.compute_macro_risk` (verrou UNIQUE §2.2, qui alimente déjà la règle Phase 0
`MACRO_BLACKOUT`) et le régime F3 reste `strategies.youssef.update_regime` (hystérésis D4) plus
le veto `config.VIX_CRIT` (AUTORITÉ). Écrire ici un second classificateur de régime ou une
seconde fenêtre de news donnerait deux réponses à « sommes-nous en blackout ? » — exactement la
panne que ce terminal existe pour empêcher. Les fetchers **transportent la donnée**, les couches
déterministes existantes **tranchent**.

**Trois natures d'issue, jamais confondues** (leçon D-050, reprise de `providers`) :
1. `unavailable_reason()` non nul → le fournisseur ne peut même pas ESSAYER (pas de clé, pas de
   fichier). Ce n'est pas un échec de fetch : c'est une configuration absente, et la chaîne de
   repli doit le savoir AVANT de tenter quoi que ce soit.
2. `error` non nul → on a essayé, ça a échoué (réseau, service, parsing). L'appelant garde son
   cache.
3. `events == []` / valeur présente → succès. Un calendrier lisible et VIDE est un état CONNU
   (semaine calme), pas une panne.

**La provenance ne se perd jamais.** Une valeur de repli porte `fallback=True`, qui devient un
drapeau `EXTERNAL_FALLBACK` jusque dans Redis puis dans le panneau. C'est la leçon du mode
REPLAY (D-058) appliquée ici : une donnée de secours indiscernable de la vraie est le seul état
réellement dangereux d'un terminal qui journalise des décisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol, TypedDict, runtime_checkable

Impact = Literal["HIGH", "MED", "LOW"]

# Un calendrier éco hebdomadaire réel porte quelques centaines d'entrées. Au-delà, ce n'est plus
# un calendrier : c'est un flux empoisonné. Le TRONQUER serait pire que le rejeter — si la
# publication imminente tombe au-delà de la coupe, le verrou F5 s'ouvrirait à tort (leçon D-050).
MAX_EVENTS = 5_000
MAX_FEED_BYTES = 4_000_000

# Bornes de plausibilité du VIX. En dessous de 5 ou au-dessus de 200, ce n'est pas une lecture :
# c'est un champ mal mappé ou une unité qui n'est pas la bonne. Un VIX à 0,14 (une fraction lue
# pour un pourcentage) passerait tous les seuils en VERT — un chiffre faux mais crédible, §3.
VIX_MIN, VIX_MAX = 5.0, 200.0


class CalendarEvent(TypedDict):
    """Publication éco normalisée — **exactement** la forme que `build_macro_calendar` et
    `compute_macro_risk` consomment déjà (`macro_releases`, D-040). S'en écarter obligerait à
    écrire un adaptateur, donc une seconde définition de ce qu'est un événement."""
    ts: float                          # epoch UTC de la publication PROGRAMMÉE
    name: str
    country: Optional[str]
    currency: Optional[str]
    impact: Impact
    consensus: Optional[float]
    previous: Optional[float]
    actual: Optional[float]


@dataclass(frozen=True)
class CalendarFetch:
    """Le résultat d'UNE interrogation de calendrier. `events` et `error` sont mutuellement
    exclusifs : `None` = échec (l'appelant garde son cache), `[]` = lu et vide (état connu)."""
    provider: str
    events: Optional[list[CalendarEvent]] = None
    observed_ts: Optional[float] = None      # instant où la donnée a été OBSERVÉE, jamais `now`
    error: Optional[str] = None
    verified: bool = False                   # une réponse RÉELLE de ce fournisseur a-t-elle été vue ?
    fallback: bool = False

    @property
    def ok(self) -> bool:
        return self.events is not None

    @property
    def flags(self) -> list[str]:
        """Drapeaux portés jusque dans Redis puis dans le panneau : la provenance ne se perd
        jamais en route."""
        f = []
        if self.fallback:
            f.append("EXTERNAL_FALLBACK")
        if not self.verified:
            f.append("SOURCE_NON_VERIFIEE")
        return f

    @property
    def resume(self) -> str:
        if self.events is None:
            return f"{self.provider} : ÉCHEC — {self.error or 'motif inconnu'}"
        haut = sum(1 for e in self.events if e["impact"] == "HIGH")
        etat = f"{len(self.events)} événement(s), dont {haut} à fort impact"
        return f"{self.provider} : {etat}" + (" · REPLI" if self.fallback else "")


@dataclass(frozen=True)
class VixFetch:
    """Le résultat d'UNE lecture de VIX. `as_of` dit de QUAND date la valeur — une clôture
    quotidienne lue en séance est une approximation, et le taire serait le mensonge habituel."""
    provider: str
    value: Optional[float] = None
    observed_ts: Optional[float] = None
    error: Optional[str] = None
    verified: bool = False
    fallback: bool = False
    as_of: str = ""                          # « 2026-08-01 » pour une clôture, « » si temps réel

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def flags(self) -> list[str]:
        f = []
        if self.fallback:
            f.append("EXTERNAL_FALLBACK")
        if not self.verified:
            f.append("SOURCE_NON_VERIFIEE")
        return f

    @property
    def resume(self) -> str:
        if self.value is None:
            return f"{self.provider} : ÉCHEC — {self.error or 'motif inconnu'}"
        quand = f" (clôture {self.as_of})" if self.as_of else ""
        return f"{self.provider} : VIX {self.value:.2f}{quand}" + (" · REPLI" if self.fallback else "")


@runtime_checkable
class EconomicCalendarProvider(Protocol):
    """Une source de calendrier éco. `fetch` est **synchrone** : elle fait de l'I/O bloquante et
    le module l'appelle dans un thread (`asyncio.to_thread`), comme le `MacroNewsProvider`
    (D-050). Une source qui dormirait dans la boucle d'événements gèlerait le hot path (§7)."""
    name: str

    def unavailable_reason(self) -> Optional[str]:
        """`None` = utilisable. Sinon le motif, en français, actionnable (clé absente, fichier
        introuvable) — distinct d'un échec de fetch."""
        ...

    def fetch(self, *, now: float) -> CalendarFetch: ...


@runtime_checkable
class VixProvider(Protocol):
    """Une source de niveau VIX. Mêmes règles que ci-dessus."""
    name: str

    def unavailable_reason(self) -> Optional[str]: ...

    def fetch(self, *, now: float) -> VixFetch: ...


def plausible_vix(value: object) -> Optional[float]:
    """Valeur → VIX plausible, ou `None` **avec la valeur écartée**. Aucune correction d'unité
    n'est tentée : diviser par 100 « au cas où » fabriquerait une lecture que personne n'a
    publiée. Hors bornes = refus, pas conversion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v if VIX_MIN <= v <= VIX_MAX else None
