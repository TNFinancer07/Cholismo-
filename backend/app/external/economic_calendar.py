"""Calendrier économique — la source du filtre F5 (D-062).

**Ce qui manquait vraiment.** Le verrou F5 existe déjà et il est bon : `macro_releases` →
`build_macro_calendar` → `compute_macro_risk` → règle Phase 0 `MACRO_BLACKOUT` (D-040). Mais
**rien ne remplissait `macro_releases` depuis une source réelle** : seul le mock l'émettait, et
en mode replay `tick_slow` n'écrit rien, donc le champ vieillissait vers ABSENT et le garde
tournait à vide. Ce module est la source manquante — pas un second verrou.

`is_high_impact_news_near()` **délègue** à `compute_macro_risk`. Recoder la fenêtre ici
donnerait deux réponses à « sommes-nous en blackout ? », et le jour où elles divergeraient,
personne ne saurait laquelle a raison.

### La promotion Tier-1, et pourquoi elle va dans le sens du verrou
`build_macro_calendar` écarte tout événement dont l'`impact` n'est pas lisible. C'est correct
pour du bruit — mais écarter un NFP parce que le fournisseur a omis son champ `impact`
**ouvrirait** le verrou au pire moment : un fail-OPEN déguisé en fail-closed. Quand l'impact est
ABSENT ou illisible **et** que le nom correspond à une publication Tier-1 connue (`T1_PATTERNS`),
l'événement est donc promu `HIGH` et marqué. On ne contredit jamais un impact explicite : le
fournisseur qui dit « low » est cru, parce que le corriger serait inventer.

### Ce que je n'ai PAS pu vérifier
Le format de réponse Finnhub est repris de sa documentation, **jamais d'une réponse réelle** :
l'egress est bloqué dans l'environnement où ce module a été écrit. Doctrine C2 (D-057) : un
identifiant qui a l'air vérifié sans l'être est pire que pas d'identifiant. `FinnhubCalendar`
porte donc `verified=False`, ce qui devient un drapeau `SOURCE_NON_VERIFIEE` jusque dans le
panneau, et `scripts/validation_externe.py` existe pour lever le doute depuis une machine avec
du réseau.

**Le piège n° 1 est le fuseau horaire, pas le format.** Finnhub renvoie `"2026-08-07 12:30:00"`
sans offset. Sa documentation dit UTC ; l'hypothèse est donc EXPLICITE (`assume_tz`) et non
enfouie. Une heure d'écart déplace toute la fenêtre de blackout : le terminal autoriserait à
trader pile pendant le NFP en affichant NORMAL, un état parfaitement crédible et complètement
faux (même classe de faute que ms/s en D-060).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..macro_risk import compute_macro_risk
from ..providers.connectors import redact
from .contracts import (MAX_EVENTS, MAX_FEED_BYTES, CalendarEvent, CalendarFetch, Impact)

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"
DEFAULT_TIMEOUT_S = 10.0

# Publications dont l'absence de verrou coûterait le plus cher. Servent UNIQUEMENT à promouvoir
# un événement dont l'impact est absent ou illisible — jamais à contredire un impact explicite.
T1_PATTERNS = (
    "non-farm payroll", "nonfarm payroll", "non farm payroll",
    "cpi", "consumer price index",
    "fomc", "fed interest rate", "federal funds", "interest rate decision",
    "ppi", "producer price index",
    "jobless claims", "unemployment rate",
)

_IMPACTS: dict[str, Impact] = {
    "high": "HIGH", "3": "HIGH", "haut": "HIGH",
    "medium": "MED", "med": "MED", "moderate": "MED", "2": "MED",
    "low": "LOW", "1": "LOW",
}


def _num(value: object) -> Optional[float]:
    """Nombre fini, ou `None`. Une chaîne vide, un tiret ou une unité collée ne sont pas des
    zéros — un consensus inventé fabriquerait une surprise qui n'a jamais existé."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            v = float(value.strip())
        except (ValueError, TypeError):
            return None
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    return None


def is_tier1(name: str) -> bool:
    """Le nom désigne-t-il une publication Tier-1 connue ? Insensible à la casse, par sous-chaîne
    (« Core CPI m/m », « US CPI YoY » doivent tous matcher)."""
    bas = (name or "").strip().lower()
    return any(p in bas for p in T1_PATTERNS)


def parse_finnhub_json(text: str, *, assume_tz: timezone = timezone.utc,
                       promote_tier1: bool = True) -> Optional[list[CalendarEvent]]:
    """Flux Finnhub → événements normalisés. `None` = flux ILLISIBLE ou EMPOISONNÉ (l'appelant
    garde son cache) ; `[]` = flux lisible et VIDE (état connu, semaine calme).

    Entrée corrompue ignorée LIGNE À LIGNE : un calendrier ne meurt pas d'une entrée pourrie.
    Flux obèse rejeté ENTIER, jamais tronqué — si la publication imminente tombe au-delà de la
    coupe, le verrou s'ouvrirait à tort (leçon D-050).
    """
    if not isinstance(text, str) or len(text) > MAX_FEED_BYTES:
        return None
    try:
        raw: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    except RecursionError:
        # JSON profondément imbriqué (« [[[[… »). `json` lève une RecursionError, qui n'est PAS
        # une ValueError : sans cette branche elle traversait le parser et remontait au worker
        # (/devil). Un flux qui fait exploser la pile est empoisonné, pas illisible — même issue.
        return None
    entries = raw.get("economicCalendar") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or len(entries) > MAX_EVENTS:
        return None
    events: list[CalendarEvent] = []
    for entry in entries:
        e = _one_finnhub(entry, assume_tz, promote_tier1)
        if e is not None:
            events.append(e)
    return events


def _one_finnhub(entry: object, tz: timezone, promote: bool) -> Optional[CalendarEvent]:
    if not isinstance(entry, dict):
        return None
    name = entry.get("event") or entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    ts = _finnhub_time(entry.get("time"), tz)
    if ts is None:
        return None
    brut = entry.get("impact")
    impact = _IMPACTS.get(str(brut).strip().lower()) if brut is not None else None
    if impact is None:
        # Impact absent ou illisible. Écarter un NFP pour cette raison OUVRIRAIT le verrou au
        # pire moment : on promeut vers le verrou, jamais vers son absence.
        if not (promote and is_tier1(name)):
            return None
        impact = "HIGH"
    country = entry.get("country")
    return CalendarEvent(
        ts=ts, name=name.strip(),
        country=country if isinstance(country, str) else None,
        currency=_currency(country),
        impact=impact,
        consensus=_num(entry.get("estimate")),
        previous=_num(entry.get("prev")),
        actual=_num(entry.get("actual")),
    )


def _currency(country: object) -> Optional[str]:
    """Le pays ISO du flux → devise, pour les seuls cas SANS ambiguïté. Deviner au-delà
    fabriquerait une devise que le fournisseur n'a pas publiée."""
    table = {"US": "USD", "EU": "EUR", "DE": "EUR", "FR": "EUR", "GB": "GBP",
             "JP": "JPY", "CH": "CHF", "CA": "CAD", "AU": "AUD", "NZ": "NZD"}
    return table.get(str(country).strip().upper()) if isinstance(country, str) else None


def _finnhub_time(value: object, tz: timezone) -> Optional[float]:
    """`"2026-08-07 12:30:00"` → epoch. Une date naïve reçoit le fuseau ASSUMÉ, déclaré par
    l'appelant : c'est le piège n° 1 d'un calendrier tiers, une heure d'écart déplaçant toute la
    fenêtre de blackout sans que rien ne le signale."""
    if not isinstance(value, str) or not value.strip():
        return None
    texte = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(texte)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    try:
        return dt.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


class FinnhubCalendar:
    """Source principale. La clé est OPTIONNELLE au sens du cahier des charges : sans elle, le
    fournisseur se déclare indisponible et la chaîne passe au suivant — il n'essaie pas puis
    échoue, ce qui donnerait un motif d'erreur pour un problème de configuration (D-050)."""

    name = "finnhub"

    def __init__(self, api_key: Optional[str] = None, *, url: str = FINNHUB_URL,
                 timeout_s: float = DEFAULT_TIMEOUT_S,
                 assume_tz: timezone = timezone.utc,
                 fetcher: Optional[Any] = None) -> None:
        self._key = (api_key or "").strip()
        self._url = url
        self._timeout = timeout_s
        self._tz = assume_tz
        self._fetcher = fetcher                      # injectable : aucun test ne touche le réseau

    def unavailable_reason(self) -> Optional[str]:
        if not self._key:
            return ("clé Finnhub absente — renseigner FINNHUB_API_KEY, ou laisser la chaîne "
                    "basculer sur le calendrier local")
        return None

    def fetch(self, *, now: float) -> CalendarFetch:
        motif = self.unavailable_reason()
        if motif is not None:
            return CalendarFetch(provider=self.name, error=motif)
        url = f"{self._url}?token={self._key}"
        try:
            text = self._fetcher(url) if self._fetcher is not None else self._http(url)
        except urllib.error.HTTPError as exc:
            # Le service a RÉPONDU et refusé : ce n'est pas « injoignable » (leçon D-057). Le
            # calendrier éco de Finnhub est un point d'accès payant sur la plupart des plans —
            # un 401/403 ici veut dire « plan insuffisant », pas « clé fausse ».
            return CalendarFetch(provider=self.name, error=self._motif_http(exc.code))
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return CalendarFetch(provider=self.name,
                                 error=f"service injoignable ({type(exc).__name__}) — "
                                       f"{redact(url)}")
        events = parse_finnhub_json(text, assume_tz=self._tz)
        if events is None:
            return CalendarFetch(provider=self.name,
                                 error="réponse illisible ou hors de toute taille plausible — "
                                       "cache conservé")
        return CalendarFetch(provider=self.name, events=events, observed_ts=now, verified=False)

    @staticmethod
    def _motif_http(code: int) -> str:
        if code in (401, 403):
            return (f"accès refusé (HTTP {code}) — le calendrier économique Finnhub est un point "
                    "d'accès payant sur la plupart des plans : vérifier le plan, pas la clé")
        if code == 429:
            return f"quota dépassé (HTTP {code}) — espacer EXTERNAL_REFRESH_SECONDS"
        if 400 <= code < 500:
            return f"requête refusée (HTTP {code})"
        return f"panne du service (HTTP {code}) — réessayer plus tard"

    def _http(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=self._timeout) as resp:   # appelé dans un thread
            # Lecture BORNÉE (+1 pour détecter le dépassement) : une réponse plus grosse que la
            # borne ne peut pas être un calendrier et ne doit pas manger la RAM du worker.
            data: bytes = resp.read(MAX_FEED_BYTES + 1)
        return data.decode("utf-8", errors="replace")


class LocalCalendarFile:
    """Repli hors ligne : un fichier JSON fourni par l'OPÉRATEUR, à la forme normalisée.

    Aucun calendrier n'est embarqué en dur dans le code. Des dates de NFP inventées, servies
    sans réseau et indiscernables d'un vrai calendrier, seraient précisément le chiffre-qui-a-
    l'air-d'une-mesure que la §3 interdit. Pas de fichier = indisponible, jamais « vide ».
    Tout ce qui sort d'ici porte `fallback=True` → drapeau `EXTERNAL_FALLBACK` dans le panneau.
    """

    name = "calendrier local"

    def __init__(self, path: Optional[str]) -> None:
        self._path = Path(path) if path else None

    def unavailable_reason(self) -> Optional[str]:
        if self._path is None:
            return ("aucun calendrier local configuré — renseigner EXTERNAL_CALENDAR_FILE pour "
                    "travailler hors ligne")
        if not self._path.exists():
            return f"calendrier local introuvable : {self._path}"
        return None

    def fetch(self, *, now: float) -> CalendarFetch:
        motif = self.unavailable_reason()
        if motif is not None or self._path is None:
            return CalendarFetch(provider=self.name, error=motif, fallback=True)
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            return CalendarFetch(provider=self.name, fallback=True,
                                 error=f"lecture impossible ({type(exc).__name__})")
        events = parse_normalised_json(text)
        if events is None:
            return CalendarFetch(provider=self.name, fallback=True,
                                 error=f"{self._path.name} illisible — attendu une LISTE d'objets "
                                       "{ts, name, impact, …}")
        # `observed_ts=now` : un fichier local est lu maintenant, sa fraîcheur est celle de la
        # lecture. C'est son contenu qui peut être périmé, et c'est à l'opérateur de le savoir —
        # d'où le drapeau de repli, qui ne le quitte jamais.
        return CalendarFetch(provider=self.name, events=events, observed_ts=now,
                             verified=True, fallback=True)


def parse_normalised_json(text: str) -> Optional[list[CalendarEvent]]:
    """Fichier local → événements. Même discipline que le parser distant : entrée corrompue
    écartée ligne à ligne, flux obèse rejeté entier."""
    if not isinstance(text, str) or len(text) > MAX_FEED_BYTES:
        return None
    try:
        raw: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
        return None
    entries = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or len(entries) > MAX_EVENTS:
        return None
    events: list[CalendarEvent] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ts, name = _num(entry.get("ts")), entry.get("name")
        impact = _IMPACTS.get(str(entry.get("impact")).strip().lower())
        if ts is None or not isinstance(name, str) or not name.strip():
            continue
        if impact is None:
            if not is_tier1(name):
                continue
            impact = "HIGH"
        country = entry.get("country")
        currency = entry.get("currency")
        events.append(CalendarEvent(
            ts=ts, name=name.strip(),
            country=country if isinstance(country, str) else None,
            currency=currency if isinstance(currency, str) else _currency(country),
            impact=impact, consensus=_num(entry.get("consensus")),
            previous=_num(entry.get("previous")), actual=_num(entry.get("actual"))))
    return events


class ChainedCalendar:
    """Source principale puis replis, dans l'ordre. Le PREMIER succès gagne, et le compte rendu
    dit lequel a servi ET pourquoi les autres n'ont pas — un repli silencieux ferait croire à
    une source principale en bonne santé."""

    name = "chaîne"

    def __init__(self, providers: list[Any]) -> None:
        self._providers = list(providers)
        self.attempts: list[str] = []

    def unavailable_reason(self) -> Optional[str]:
        if not self._providers:
            return "aucune source de calendrier configurée"
        motifs = [p.unavailable_reason() for p in self._providers]
        if all(m is not None for m in motifs):
            return " · ".join(str(m) for m in motifs)
        return None

    def fetch(self, *, now: float) -> CalendarFetch:
        self.attempts = []
        dernier: Optional[CalendarFetch] = None
        for p in self._providers:
            try:
                motif = p.unavailable_reason()
                if motif is not None:
                    self.attempts.append(f"{p.name} : indisponible — {motif}")
                    continue
                res: CalendarFetch = p.fetch(now=now)
            except Exception as exc:
                # Un fournisseur qui LÈVE emportait toute la chaîne, donc le repli — c'est-à-dire
                # exactement ce pour quoi la chaîne existe (/devil). Il est écarté, pas suivi.
                self.attempts.append(f"{p.name} : a levé ({type(exc).__name__}) — écarté")
                continue
            self.attempts.append(res.resume)
            if res.ok:
                return res
            dernier = res
        if dernier is not None:
            return dernier
        return CalendarFetch(provider=self.name,
                             error=self.unavailable_reason() or "aucune source utilisable")


# --- le verdict F5 : DÉLÉGUÉ, jamais recalculé ------------------------------------------------

def is_high_impact_news_near(events: list[CalendarEvent], now: float,
                             window_minutes: float) -> dict[str, Any]:
    """« Sommes-nous dans la fenêtre d'interdiction F5 ? » — et le détail de l'événement.

    **Aucun seuil n'est défini ici.** Tout passe par `compute_macro_risk`, le garde déterministe
    qui alimente déjà la règle Phase 0 `MACRO_BLACKOUT` (verrou unique, §2.2). La fenêtre est
    SYMÉTRIQUE autour de la publication (`|ts − now| ≤ fenêtre`) : le chaos ne commence pas à
    l'heure pile et ne s'arrête pas non plus à la seconde.

    Rend `{near, regime, event, seconds_until}` : `near` est le booléen demandé, `event` porte
    `{name, ts, impact, country}` — un « BLOQUÉ » qui ne dit pas POURQUOI est un cul-de-sac pour
    l'opérateur.
    """
    fenetre_min = float(window_minutes)
    if fenetre_min != fenetre_min or fenetre_min in (float("inf"), float("-inf")):
        # `max(0.0, nan)` rend 0.0 en Python : une fenêtre NaN devenait donc PERMISSIVE et
        # autorisait à trader (/devil). Une fenêtre non finie est une faute d'appel, pas une
        # condition de donnée — elle lève, comme un refus de politique (doctrine D-050).
        raise ValueError(f"fenêtre F5 non finie ({window_minutes!r}) — une fenêtre absurde "
                         "deviendrait silencieusement permissive")
    fenetre = max(0.0, fenetre_min) * 60.0
    risk = compute_macro_risk(list(events), now, fenetre, fenetre)
    return {"near": bool(risk["in_window"]), "regime": risk["regime"],
            "event": risk["event"], "seconds_until": risk["seconds_until"]}
