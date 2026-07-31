"""Order Flow in-house — Niveau 2 CALCUL (D-055).

Transforme un flux **brut** (carnet L2/MBO + Time & Sales) en `OrderFlowSnapshot` : les quatre
portes B1-B4, le profil de volume et l'ATR. Ce module **mesure, il ne décide pas** : aucun seuil,
aucun verdict, aucun ordre (§2.1). La comparaison aux seuils reste au moteur (`evaluate_lsr`) —
séparer la mesure de la décision permet de re-calibrer un seuil sans retoucher un calcul, et de
tester un calcul sans simuler une décision.

**Ce qu'il remplace.** Jusqu'ici les portes étaient des PROXYS fournis par la source
(`absorption` booléen, `aggressor_ratio` déjà agrégé) — `lsr_engine` les nomme d'ailleurs
« B1-like » / « B2-like » pour cette raison. Ici les mêmes grandeurs sont **calculées chez nous**
depuis les ticks, ce qui les rend vérifiables et indépendantes du fournisseur. Le câblage du
moteur sur ces valeurs est une tranche SÉPARÉE : brancher une nouvelle mesure sur le chemin
d'émission live sans l'avoir observée serait imprudent.

**Formules — `v1 provisional` assumé (§11/§12).** Le doc LSR NOMME les portes, il n'en donne pas
les formules ; aucun `/reference/` ne fait AUTORITÉ ici. Chaque définition ci-dessous est donc une
première passe, isolée dans ce module et documentée pour être discutée :

- **B1 `wall_refill_ratio`** — sur la fenêtre, à un niveau de prix DÉSIGNÉ : `consommé` =
  taille initiale − taille minimale observée ; `rechargé` = taille finale − taille minimale ;
  ratio = rechargé / consommé. Jamais écrêté à 1 (un mur reconstruit plus gros qu'il n'a été mangé
  est une défense agressive, pas une anomalie).
- **B2 `tape_aggressor_buy_fraction`** — volume acheteur / volume total, **pondéré par le
  volume** et non par le nombre de prints (un print de 100 lots ne pèse pas comme un de 1 lot).
- **B3 `rejection_delta_ratio`** — delta net (acheteur − vendeur) des prints POSTÉRIEURS à
  l'extrême de la fenêtre, normalisé par le volume total. Signe = sens du rejet : positif = le bas
  a été rejeté (l'acheteur a repris la main), négatif = le haut. Borné [−1, 1] par construction.
- **B4 `post_sweep_aggression_ratio`** — débit d'agression APRÈS le sweep divisé par le débit
  AVANT (volume/seconde de part et d'autre). C'est bien une VITESSE : 100 lots en 1 s ne se lit
  pas comme 100 lots en 30 s.

**Fail-closed, porte par porte (§3).** Chaque grandeur vaut `None` **avec son motif** dans
`missing` dès que ses entrées ne suffisent pas. Aucune valeur par défaut : ni 0, ni 1, ni 0,5 —
un chiffre qui a l'air d'une mesure est plus dangereux qu'une absence déclarée. Les motifs
comptent autant que les valeurs : quatre `None` muets ne disent pas POURQUOI.

Trois pièges traités explicitement, tous testés :
1. **Niveau hors profondeur publiée ≠ taille nulle.** Un carnet tronqué à 3 niveaux ne dit RIEN
   du 8e ; le confondre avec un mur retiré inventerait un événement.
2. **Aucune déplétion → B1 non calculable.** Rendre 1,0 (« le mur a tenu ») affirmerait une
   défense qui n'a jamais été mise à l'épreuve.
3. **Barre corrompue → ATR non calculé.** Écarter une barre au milieu recollerait deux barres non
   adjacentes ; le True Range de ce faux voisinage serait fabriqué.

Le module est **PUR** : `now` est injecté, aucune horloge lue, aucun état retenu, aucune I/O.
Le profil de volume est **délégué** à `app/volume_profile.py` (D-041) : deux implémentations du
VPOC dans le même terminal finiraient par se contredire.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .. import config
from ..volume_profile import build_volume_profile


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _publishable(value: Optional[float], label: str, missing: list[str]) -> Optional[float]:
    """Dernier filet avant publication (/devil) : des tailles à 1e308 débordent en `inf`, et
    `inf / inf` vaut `nan`. Une porte publierait alors « nan » comme s'il s'agissait d'un ratio —
    exactement le chiffre-qui-a-l'air-d'une-mesure que tout le module refuse."""
    if value is None:
        return None
    if not _finite(value):
        missing.append(f"{label}: résultat non fini (débordement de taille) — mesure retirée")
        return None
    return float(value)


@dataclass(frozen=True)
class OrderFlowSnapshot:
    """Mesures d'order flow à un instant donné. Immuable : un snapshot circule entre couches et
    ne doit jamais être « corrigé » en route. Chaque champ vaut `None` quand il n'est pas
    calculable, et `missing` dit pourquoi."""
    now: float
    window_s: float
    # --- portes (mesures brutes, AUCUN seuil appliqué ici) ---
    wall_refill_ratio: Optional[float] = None            # B1
    tape_aggressor_buy_fraction: Optional[float] = None  # B2
    rejection_delta_ratio: Optional[float] = None        # B3
    post_sweep_aggression_ratio: Optional[float] = None  # B4
    # --- contexte ---
    volume_profile: Optional[dict] = None                # délégué à D-041
    atr_fast: Optional[float] = None
    atr_slow: Optional[float] = None
    # --- honnêteté ---
    prints_used: int = 0
    prints_dropped: int = 0
    missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def atr_5(self) -> Optional[float]:
        """Alias de lecture : les périodes sont configurables, les noms d'usage restent 5/14."""
        return self.atr_fast

    @property
    def atr_14(self) -> Optional[float]:
        return self.atr_slow


# --- normalisation des entrées ----------------------------------------------------------------

def _norm_print(p: Any, now: float, floor_ts: float) -> Optional[tuple[float, float, float, str]]:
    """`(ts, price, size, side)` ; `side` ∈ BUY|SELL|UNKNOWN. Un côté inconnu est CONSERVÉ (il
    compte dans le volume total, donc dans la couverture de B2) — le jeter gonflerait
    artificiellement la confiance dans le ratio."""
    if not isinstance(p, dict):
        return None
    ts, price, size = p.get("ts"), p.get("price"), p.get("size")
    if not (_finite(ts) and _finite(price) and _finite(size)) or size <= 0 or price <= 0:
        return None
    if ts > now or ts < floor_ts:            # fantôme du futur (D-048/D-050) ou hors fenêtre
        return None
    side = p.get("side")
    return (float(ts), float(price), float(size),
            side if side in ("BUY", "SELL") else "UNKNOWN")


def _level_size(book: Any, price: float, side: str, tick: float) -> Optional[float]:
    """Taille au niveau `price` dans un snapshot de carnet. `None` = **inconnu** (carnet
    malformé, ou niveau HORS de la profondeur publiée) ; `0.0` = niveau réellement vide alors
    qu'il est dans la plage cotée. Confondre les deux inventerait un mur retiré."""
    if not isinstance(book, dict):
        return None
    levels = book.get("bids" if side == "BID" else "asks")
    if not isinstance(levels, list) or not levels:
        return None
    prices: list[float] = []
    for row in levels:
        if (isinstance(row, (list, tuple)) and len(row) >= 2
                and _finite(row[0]) and _finite(row[1]) and row[1] >= 0):
            prices.append(float(row[0]))
            if abs(float(row[0]) - price) < tick / 2:
                return float(row[1])
    if not prices:
        return None
    # Le niveau n'est pas coté. La réponse dépend du CÔTÉ, pas d'une simple plage : un carnet
    # publie du meilleur vers le profond.
    #  - BID : au-dessus du meilleur bid, plus personne n'achète → vide RÉEL (0). En dessous du
    #    dernier niveau publié, on ne sait pas — le carnet est tronqué là.
    #  - ASK : symétrique.
    # (Première version : « dans la plage publiée → 0 ». Elle ratait le cas central — le mur EST
    # souvent le meilleur bid, et sa disparition rétrécit la plage, donc le niveau retombait
    # « hors plage » et le retrait du mur devenait invisible. Trouvé par le test.)
    best, deepest = (max(prices), min(prices)) if side == "BID" else (min(prices), max(prices))
    beyond_depth = price < deepest if side == "BID" else price > deepest
    if beyond_depth:
        return None
    inside_spread = price > best if side == "BID" else price < best
    return 0.0 if inside_spread or deepest <= price <= best or best <= price <= deepest else None


# --- portes ------------------------------------------------------------------------------------

def _crossed(book: Any) -> bool:
    """Meilleur bid ≥ meilleur ask : le carnet est CORROMPU (pathologie réelle, détectée ailleurs
    sous `CROSSED_BOOK`). Mesurer un rechargement de mur dessus produirait un nombre plausible à
    partir d'une donnée fausse."""
    if not isinstance(book, dict):
        return False
    def _best(key, pick):
        rows = book.get(key)
        prices = [float(r[0]) for r in rows
                  if isinstance(rows, list) and isinstance(r, (list, tuple)) and len(r) >= 2
                  and _finite(r[0])] if isinstance(rows, list) else []
        return pick(prices) if prices else None
    bid, ask = _best("bids", max), _best("asks", min)
    return bid is not None and ask is not None and bid >= ask


def _b1_wall_refill(books: Sequence[Any], price: Optional[float], side: Optional[str],
                    tick: float, missing: list[str]) -> Optional[float]:
    if price is None or side not in ("BID", "ASK") or not _finite(price):
        missing.append("B1: aucun niveau de mur désigné")
        return None
    sane = [b for b in books if not _crossed(b)]
    if len(sane) < len(books):
        missing.append(f"B1: {len(books) - len(sane)} snapshot(s) de carnet CROISÉ écarté(s)")
    sizes = [s for s in (_level_size(b, price, side, tick) for b in sane) if s is not None]
    if len(sizes) < 2:
        missing.append("B1: moins de deux observations du niveau (ou niveau hors profondeur)")
        return None
    consumed = sizes[0] - min(sizes)
    if consumed <= 0:
        # Le mur n'a jamais été entamé : le ratio est une division par zéro, pas un 1,0.
        missing.append("B1: aucune déplétion observée — défense non éprouvée")
        return None
    refilled = sizes[-1] - min(sizes)
    return max(0.0, refilled) / consumed


def _b2_aggressor_fraction(prints: Sequence[tuple], min_coverage: float, min_volume: float,
                           missing: list[str]) -> Optional[float]:
    total = sum(p[2] for p in prints)
    if not _finite(total):
        # Le total a débordé : `known/total` vaudrait `nan` et passerait le test de couverture,
        # puis `delta/total` vaudrait 0,0 — fini, donc publiable, et lu comme une mesure neutre.
        missing.append("B2: volume total non fini (débordement) — aucune mesure")
        return None
    if total < min_volume:
        # « 100 % acheteur » sur un lot n'est pas un flux acheteur : c'est du bruit présenté
        # comme une mesure (/devil). Le plancher est v1 provisional, à calibrer par instrument.
        missing.append(f"B2: volume {total:g} sous le plancher de mesure ({min_volume:g})")
        return None
    known = sum(p[2] for p in prints if p[3] != "UNKNOWN")
    if known / total < min_coverage:
        missing.append(f"B2: côté agresseur connu sur {known / total:.0%} du volume "
                       f"(minimum {min_coverage:.0%})")
        return None
    buy = sum(p[2] for p in prints if p[3] == "BUY")
    return buy / known


def _b3_rejection_delta(prints: Sequence[tuple], min_coverage: float, min_volume: float,
                        missing: list[str]) -> Optional[float]:
    """Delta postérieur à l'extrême, normalisé. L'extrême retenu est celui qui a le plus de
    chemin parcouru depuis lui — sinon un plus-haut et un plus-bas simultanés rendraient le signe
    arbitraire.

    Exige la MÊME couverture de côté que B2 : sans côté agresseur, le delta vaut mécaniquement 0,
    et ce 0 se lirait comme « rejet neutre observé » alors que rien n'a été observé."""
    total = sum(p[2] for p in prints)
    if not _finite(total):
        missing.append("B3: volume total non fini (débordement) — aucune mesure")
        return None
    if total < min_volume or len(prints) < 2:
        missing.append(f"B3: volume {total:g} sous le plancher de mesure ({min_volume:g}) "
                       f"ou moins de deux prints")
        return None
    known = sum(p[2] for p in prints if p[3] != "UNKNOWN")
    if known / total < min_coverage:
        missing.append(f"B3: côté agresseur connu sur {known / total:.0%} du volume "
                       f"(minimum {min_coverage:.0%}) — delta non mesurable")
        return None
    prices = [p[1] for p in prints]
    # DERNIÈRE touche de l'extrême, pas la première (/devil) : sur un double creux, partir de la
    # première ferait compter la vente du second creux comme du rejet acheteur. Le rejet commence
    # quand le prix quitte l'extrême POUR DE BON.
    low_i = len(prices) - 1 - prices[::-1].index(min(prices))
    high_i = len(prices) - 1 - prices[::-1].index(max(prices))
    if min(prices) == max(prices):
        missing.append("B3: prix plat — aucun extrême distinguable")
        return None
    last = prices[-1]
    # Rejet du BAS si le prix est remonté depuis le plus-bas plus qu'il n'est descendu du plus-haut.
    up_from_low, down_from_high = last - prices[low_i], prices[high_i] - last
    extreme_i, sign = (low_i, 1.0) if up_from_low >= down_from_high else (high_i, -1.0)
    leg = prints[extreme_i + 1:]
    if not leg:
        missing.append("B3: l'extrême est le dernier print — aucune jambe de rejet observée")
        return None
    delta = sum(p[2] if p[3] == "BUY" else -p[2] if p[3] == "SELL" else 0.0 for p in leg)
    ratio = delta / total
    # Le signe suit le rejet mesuré : un delta acheteur après un plus-bas EST un rejet du bas.
    return max(-1.0, min(1.0, ratio if sign > 0 else ratio))


def _b4_post_sweep(prints: Sequence[tuple], sweep: Any, now: float, floor_ts: float,
                   min_span: float, missing: list[str]) -> Optional[float]:
    sweep_ts = sweep.get("ts") if isinstance(sweep, dict) else None
    if not _finite(sweep_ts):
        missing.append("B4: aucun sweep horodaté")
        return None
    if not (floor_ts <= sweep_ts <= now):
        missing.append("B4: sweep hors de la fenêtre d'analyse")
        return None
    before = [p for p in prints if p[0] < sweep_ts]
    after = [p for p in prints if p[0] >= sweep_ts]
    span_before, span_after = sweep_ts - floor_ts, now - sweep_ts
    if min(span_before, span_after) < min_span:
        # Un débit mesuré sur quelques millisecondes est du bruit multiplié par mille.
        missing.append(f"B4: durée insuffisante de part et d'autre du sweep "
                       f"({min(span_before, span_after):.3g}s < {min_span:g}s)")
        return None
    vol_before, vol_after = sum(p[2] for p in before), sum(p[2] for p in after)
    if not (_finite(vol_before) and _finite(vol_after)):
        missing.append("B4: volume non fini (débordement) — aucune mesure")
        return None
    rate_before, rate_after = vol_before / span_before, vol_after / span_after
    if rate_before <= 0:
        # Diviser par un débit nul donnerait « ∞ » ou un nombre géant présenté comme une mesure.
        missing.append("B4: aucun volume avant le sweep — accélération non mesurable")
        return None
    return rate_after / rate_before


# --- ATR ----------------------------------------------------------------------------------------

def _atr(bars: Sequence[Any], period: int, missing: list[str]) -> Optional[float]:
    """Moyenne des `period` derniers True Range. `TR = max(H−L, |H−C_prev|, |L−C_prev|)` —
    la clôture précédente fait entrer les GAPS dans la mesure, c'est tout l'intérêt du TR.

    Moyenne simple et non lissage de Wilder : le lissage exige de rejouer TOUT l'historique depuis
    l'origine pour être reproductible ; sur une fenêtre bornée, la moyenne simple est
    déterministe et vérifiable à la main (`v1 provisional`, documenté).
    """
    if period < 1:
        return None
    rows: list[tuple[float, float, float]] = []
    for b in bars if isinstance(bars, (list, tuple)) else []:
        if not isinstance(b, dict):
            missing.append(f"ATR({period}): barre inexploitable — série interrompue")
            return None
        h, low, c = b.get("high"), b.get("low"), b.get("close")
        if not (_finite(h) and _finite(low) and _finite(c)) or h < low:
            # Une barre corrompue casse la série : la sauter recollerait deux barres non
            # adjacentes et fabriquerait un True Range qui n'a jamais existé.
            missing.append(f"ATR({period}): barre corrompue — série interrompue")
            return None
        rows.append((float(h), float(low), float(c)))
    if len(rows) < period + 1:
        missing.append(f"ATR({period}): {len(rows)} barres pour {period + 1} requises")
        return None
    trs = []
    for i in range(1, len(rows)):
        h, low, _ = rows[i]
        prev_close = rows[i - 1][2]
        trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    return sum(trs[-period:]) / period


# --- point d'entrée ------------------------------------------------------------------------------

def compute_snapshot(*, now: Any, prints: Any = (), books: Any = (), bars: Any = (),
                     sweep: Any = None, tick: float = None,          # type: ignore[assignment]
                     wall_price: Optional[float] = None, wall_side: Optional[str] = None,
                     window_s: float = None,                          # type: ignore[assignment]
                     atr_fast: int = None, atr_slow: int = None,      # type: ignore[assignment]
                     min_side_coverage: float = None,                 # type: ignore[assignment]
                     min_volume: float = None,                        # type: ignore[assignment]
                     min_span: float = None,                          # type: ignore[assignment]
                     ) -> OrderFlowSnapshot:
    """Calcule un `OrderFlowSnapshot`. Ne lève JAMAIS : toute entrée inexploitable dégrade la
    grandeur concernée en `None` motivé, sans toucher aux autres (§3)."""
    window_s = window_s if window_s is not None else config.ORDERFLOW_WINDOW_S
    tick = tick if tick is not None else config.PRICE_TICK
    atr_fast = atr_fast if atr_fast is not None else config.ORDERFLOW_ATR_FAST
    atr_slow = atr_slow if atr_slow is not None else config.ORDERFLOW_ATR_SLOW
    coverage = (min_side_coverage if min_side_coverage is not None
                else config.ORDERFLOW_MIN_SIDE_COVERAGE)
    missing: list[str] = []

    if not _finite(window_s) or window_s <= 0:
        # Config cassée : une fenêtre vide rendrait quatre `None` sans cause visible, et un
        # snapshot muet ressemble à un marché calme (/devil).
        return OrderFlowSnapshot(now=float(now) if _finite(now) else float("nan"), window_s=0.0,
                                 missing=("fenêtre d'analyse invalide: aucun calcul",))
    if not _finite(now):
        # Horloge douteuse : tout est suspect, rien n'est calculé (même règle que le driver D-052).
        return OrderFlowSnapshot(now=float("nan"), window_s=window_s,
                                 missing=("horloge non finie: aucun calcul",))
    now = float(now)
    floor_ts = now - window_s

    raw_prints = list(prints)[-config.ORDERFLOW_MAX_PRINTS:] if isinstance(prints, (list, tuple)) else []
    kept, dropped, from_future, seen_seq = [], 0, 0, set()
    for p in raw_prints:
        norm = _norm_print(p, now, floor_ts)
        if norm is None:
            dropped += 1
            if isinstance(p, dict) and _finite(p.get("ts")) and p["ts"] > now:
                from_future += 1
            continue
        # Dédup sur `seq` UNIQUEMENT (identifiant explicite du flux) : rejeu ou fenêtres qui se
        # chevauchent. Sans `seq`, deux prints identiques sont indiscernables d'un vrai double
        # passage au même prix — dédupliquer « au contenu » effacerait du volume RÉEL.
        seq = p.get("seq")
        if seq is not None:
            if seq in seen_seq:
                dropped += 1
                continue
            seen_seq.add(seq)
        kept.append(norm)
    kept.sort(key=lambda p: p[0])
    if from_future and not kept:
        # Erreur de câblage classique : le `now` fourni est en retard sur le flux. Sans ce motif,
        # « volume sous le plancher » enverrait chercher au mauvais endroit.
        missing.append(f"tape: {from_future} print(s) postérieur(s) à `now` et AUCUN retenu — "
                       f"horloge d'appel en retard sur le flux ?")

    raw_books = list(books)[-config.ORDERFLOW_MAX_BOOKS:] if isinstance(books, (list, tuple)) else []
    # TRIÉS comme les prints : `sizes[0]`/`sizes[-1]` doivent être le plus ANCIEN et le plus
    # RÉCENT, pas le premier et le dernier reçus. Deux tampons concaténés suffisaient à mesurer
    # le rechargement entre les mauvaises bornes (/devil 2e passe).
    books_in_window = sorted(
        (b for b in raw_books
         if isinstance(b, dict) and _finite(b.get("ts")) and floor_ts <= b["ts"] <= now),
        key=lambda b: b["ts"])

    # Profil de volume : DÉLÉGUÉ (D-041) — une seule implémentation du VPOC dans le terminal.
    volume_by_price: dict[float, float] = {}
    buy_by_price: dict[float, float] = {}
    for _ts, price, size, side in kept:
        volume_by_price[price] = volume_by_price.get(price, 0.0) + size
        if side == "BUY":
            buy_by_price[price] = buy_by_price.get(price, 0.0) + size
    profile = None
    if not _finite(tick) or tick <= 0:
        # `build_volume_profile` rend un objet VIDE (pas `None`) sur un tick absurde ; publié tel
        # quel il se lirait « connecté mais sans volume ». Un tick invalide n'a pas de sens
        # physique : il empêche la mesure, il ne la dégrade pas.
        missing.append(f"VP/B1: tick de prix invalide ({tick!r}) — aucune grille de prix")
        tick_ok = False
    else:
        tick_ok = True
        if volume_by_price:
            profile = build_volume_profile(volume_by_price, tick, config.VP_VA_PCT,
                                           config.VP_LVN_RATIO, config.VP_MAX_LEVELS,
                                           buy_by_price=buy_by_price)
        else:
            missing.append("VP: aucun print exploitable dans la fenêtre")

    min_volume = (min_volume if min_volume is not None else config.ORDERFLOW_MIN_VOLUME)
    min_span = (min_span if min_span is not None else config.ORDERFLOW_MIN_SPAN_S)
    return OrderFlowSnapshot(
        now=now, window_s=window_s,
        wall_refill_ratio=_publishable(
            _b1_wall_refill(books_in_window, wall_price, wall_side, tick, missing)
            if tick_ok else None, "B1", missing),
        tape_aggressor_buy_fraction=_publishable(
            _b2_aggressor_fraction(kept, coverage, min_volume, missing), "B2", missing),
        rejection_delta_ratio=_publishable(
            _b3_rejection_delta(kept, coverage, min_volume, missing), "B3", missing),
        post_sweep_aggression_ratio=_publishable(
            _b4_post_sweep(kept, sweep, now, floor_ts, min_span, missing), "B4", missing),
        volume_profile=profile,
        atr_fast=_publishable(_atr(bars, atr_fast, missing), f"ATR({atr_fast})", missing),
        atr_slow=_publishable(_atr(bars, atr_slow, missing), f"ATR({atr_slow})", missing),
        prints_used=len(kept), prints_dropped=dropped,
        missing=tuple(missing),
    )
