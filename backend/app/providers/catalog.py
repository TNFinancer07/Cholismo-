"""Registre des séries macro de Youssef — transcription EXÉCUTABLE des deux specs (D-057).

Les artefacts `API × Arbitrage` et `API × Dimension` décrivent, ligne par ligne, quelle variable
de quelle formule chaque appel API alimente. Ce module en est le miroir machine : une entrée par
variable, rattachée à **sa dimension (D1–D5)** et **aux arbitrages qu'elle sert (1–6)** — c'est-à-
dire structurée par les indicateurs, pas par les fournisseurs.

**La doctrine de confiance est exécutable, pas décorative.** Les specs sont explicites :
« un C2 veut dire *ne pas coder l'identifiant en dur sans être passé par le catalogue du
fournisseur d'abord*, un C3 veut dire *ne pas commencer* ». Conséquence tenue ici : une ligne
non-C1 n'a **aucun identifiant** dans le code (`identifier is None`). Écrire une clé « probable »
produirait exactement ce que ce terminal refuse — un identifiant qui a l'air vérifié (§3).

**Trois natures de ligne**, et les confondre est le piège principal :
- `OBSERVED`  — une série lue chez un fournisseur ; seule nature collectable ;
- `DERIVED`   — un calcul sur d'autres lignes (`depends_on`) ; jamais collectée ;
- `PARAMETER` — une constante à calibrer ; **aucune requête ne la fournira**.

**Ce module est PUR** : aucune horloge, aucune I/O, aucune bibliothèque de dates. Les échéances
fixes sont des epochs constants — un test, qui lui a le droit d'ouvrir un calendrier, vérifie
qu'ils correspondent bien à la date annoncée.

Arbitrage de version assumé : quand les deux specs se contredisent sur une confiance, la plus
RÉCENTE gagne (dimensions, catalogues vérifiés le 31.07.2026) — plusieurs lignes ✕/≈ de la spec
arbitrage y sont résolues (`ois_term` USD par les settlements ZQ, `hicp_ez` par HICP, `ancrée`
USD par le 5y5y). Les lignes que la spec dimension ne couvre pas gardent leur tag d'origine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Confidence(str, Enum):
    C1 = "C1"          # vérifié — endpoint et identifiant confirmés, utilisable tel quel
    C2 = "C2"          # bon fournisseur, identifiant à confirmer au catalogue AVANT de coder
    C3 = "C3"          # bloqué — et parfois « bloqué » ne veut pas dire « donnée manquante »


class Kind(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    PARAMETER = "PARAMETER"


class Leg(str, Enum):
    BASE = "BASE"        # jambe base de la paire (EUR dans EUR/USD)
    QUOTE = "QUOTE"      # jambe quote (USD)
    DIFF = "DIFF"        # différentiel déjà construit
    GLOBAL = "GLOBAL"    # mesure de régime, sans déclinaison par pays
    NONE = "—"           # paramètre, constante ou calcul interne


class Provider(str, Enum):
    FRED = "FRED"
    ECB_SDMX = "ECB_SDMX"
    EUROSTAT = "EUROSTAT"
    BUNDESBANK = "BUNDESBANK"
    CFTC_SOCRATA = "CFTC_SOCRATA"
    SDMX_INTL = "SDMX_INTL"            # BIS / FMI / OCDE / DBnomics — même protocole
    YFINANCE = "YFINANCE"
    PHILADELPHIA_FED = "PHILADELPHIA_FED"   # SPF : fichiers XLSX, pas de REST (structurel)
    NY_FED = "NY_FED"                       # Holston-Laubach-Williams, fichier public
    NONE = "—"


class Frequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    NONE = "—"


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    label: str                       # français (§5) — c'est ce que lit un opérateur
    kind: Kind
    dimension: str                   # "D1".."D5" — la dimension propriétaire de la ligne
    arbitrages: tuple[int, ...]      # arbitrages servis (une ligne sert souvent plusieurs)
    leg: Leg
    provider: Provider
    identifier: Optional[str]        # None dès que ce n'est pas C1 — jamais de clé « probable »
    frequency: Frequency
    confidence: Confidence
    note: str
    depends_on: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()      # clés supplémentaires d'une même ligne (ténors, variantes)
    catalog_hint: str = ""           # OÙ relever la clé, pour une ligne C2


@dataclass(frozen=True)
class DimensionSpec:
    code: str
    label: str
    kind: str                        # "A" directionnel · "ABSORBED" · "B" modulateur
    horizon: str
    ttl_s: float
    long_weight: float               # poids dans l'horizon LONG (0 pour un label absorbé)
    absorbed_by: Optional[str] = None
    fail_closed: bool = False


@dataclass(frozen=True)
class ArbitrageSpec:
    arb_id: int
    name: str
    source_dim: str
    horizon: str
    threshold_label: str
    status: str                      # PRÊT · PARTIEL · BLOQUÉ (état de la spec, pas du code)
    formula: str


# =============================================================================================
# Étape 0 — le quadrant fixe les poids (AUTORITÉ : matrice W, valeurs exactes)
# =============================================================================================

# Miroir de `strategies.youssef.WEIGHTS` : la matrice existe à deux endroits (spec et moteur
# d'agrégation), un test verrouille leur égalité — sinon le terminal pondère autrement que
# ce que la spec dit, en silence.
QUADRANT_WEIGHTS: dict[str, dict[str, float]] = {
    "SURCHAUFFE":   {"D1": 0.15, "D2": 0.35, "D3": 0.30, "D4": 0.10, "D5": 0.10},
    "GOLDILOCKS":   {"D1": 0.20, "D2": 0.15, "D3": 0.10, "D4": 0.30, "D5": 0.25},
    "STAGFLATION":  {"D1": 0.15, "D2": 0.15, "D3": 0.25, "D4": 0.25, "D5": 0.20},
    "DESINFLATION": {"D1": 0.30, "D2": 0.30, "D3": 0.10, "D4": 0.15, "D5": 0.15},
}

# Poids internes de D1 (spec dimension). Ceux de D5 ne sont PAS spécifiés — PLACEHOLDER assumé,
# et c'est pour ça qu'ils n'apparaissent pas ici : inventer une répartition serait pire que
# reconnaître qu'elle manque.
D1_WEIGHTS: dict[str, float] = {"pmi": 0.30, "gap": 0.25, "lei": 0.20, "sahm": 0.15, "ip": 0.10}

# Horizon LONG : D1 0.40 · D5 0.30 · Arb3 0.30.
LONG_HORIZON_WEIGHTS: dict[str, float] = {"D1": 0.40, "D5": 0.30, "Arb3": 0.30}

_DAY = 86_400.0

DIMENSIONS: dict[str, DimensionSpec] = {
    "D1": DimensionSpec("D1", "Cycle économique", "A", "LONG", 45 * _DAY, 0.40),
    "D2": DimensionSpec("D2", "Politique monétaire", "ABSORBED", "MOYEN", 30 * _DAY, 0.0,
                        absorbed_by="Arb1"),
    "D3": DimensionSpec("D3", "Inflation", "ABSORBED", "MOYEN", 30 * _DAY, 0.0,
                        absorbed_by="Arb2"),
    "D4": DimensionSpec("D4", "Régime de risque", "B", "JOUR", 4 * 3600.0, 0.0,
                        fail_closed=True),
    "D5": DimensionSpec("D5", "Facteurs structurels", "A", "LONG", 90 * _DAY, 0.30),
}

ARBITRAGES: tuple[ArbitrageSpec, ...] = (
    ArbitrageSpec(1, "Taylor vs OIS", "D2", "1-4 sem", "|δ| > 0.30 %", "PRÊT",
                  "arb1_delta = taylor_diff − ois_implied_diff"),
    ArbitrageSpec(2, "Phillips vs TIPS", "D3", "2-4 sem", "|δ| > 0.25 %", "PARTIEL",
                  "surprise = Phillips − TIPS ; arb2_delta = surprise_base − surprise_quote"),
    ArbitrageSpec(3, "BEER vs spot", "D5", "6-12+ sem", "|z| > 1.5", "PARTIEL",
                  "BEER = 1.00 + r_diff + NFA + TOT + productivité ; z = misalignment / σ"),
    ArbitrageSpec(4, "Carry / UIP", "D2+D4", "1-3 sem", "|signal| > 2.0 après gate", "PRÊT",
                  "carry_net = rate_diff − dépréciation ; signal = carry_net × gate_D4"),
    ArbitrageSpec(5, "Cycle Divergence", "D1", "4-8 sem", "|δ| > 0.5", "PRÊT",
                  "arb5_delta = divergence_réelle − divergence_pricée"),
    ArbitrageSpec(6, "Risk Reversal", "D4", "1-3 sem", "|z| > 1.5 ET divergence > 0", "BLOQUÉ",
                  "rr_zscore = (rr_current − rr_average)/rr_std"),
)

# Code de zone AMECO — constante VISIBLE : « le code zone AMECO suit les élargissements
# (EA20 → EA21) ». Quand la zone euro s'agrandit, un seul endroit change.
AMECO_ZONE = "EA20"

# Bund€i de référence. Programme d'émission de titres indexés allemands ARRÊTÉ depuis 2024 :
# aucun titre ne viendra remplacer celui-ci. Epoch constant pour garder le module sans horloge
# (2033-04-15T00:00:00Z ; le jour exact n'est pas donné par la spec — l'écart est immatériel à
# l'échelle de l'année mesurée).
BUNDEI: dict = {"isin": "DE0001030575", "label": "Bund€i 0,10 % 04.2033",
                "maturity_ts": 1_997_136_000.0, "maturity_label": "2033-04"}
# Ténor de la jambe US (T10YIE) : CONSTANT à 10 ans, là où le linker allemand raccourcit d'un an
# par an. Écart toléré avant bascule d'ISIN : PLACEHOLDER de calibration, pas une valeur de spec.
US_BREAKEVEN_TENOR_Y = 10.0
BUNDEI_MAX_TENOR_DRIFT_Y = 2.0
_YEAR_S = 365.2425 * _DAY


# =============================================================================================
# Le registre — une entrée par variable, rattachée à sa dimension et à ses arbitrages
# =============================================================================================

def _s(*args, **kwargs) -> SeriesSpec:
    return SeriesSpec(*args, **kwargs)


CATALOG: tuple[SeriesSpec, ...] = (
    # --- D1 · Cycle économique (type A, TTL 45 j, poids LONG 0.40) -----------------------
    _s("pmi_us", "PMI — composite Fed régionales", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.FRED, "GACDISA066MSFRBNY", Frequency.MONTHLY, Confidence.C1,
       "w 0.30, le plus gros poids. L'ISM a été retiré de FRED — composite régional en "
       "substitut ; pondération inter-régions à fixer (v1 : Empire seul).",
       extra=("GACDFSA066MSFRBPHI", "BACTSAMFRBDAL")),
    _s("pmi_ez", "PMI zone euro — proxy ESI", Kind.OBSERVED, "D1", (5,), Leg.BASE,
       Provider.EUROSTAT, "ei_bssi_m_r2", Frequency.MONTHLY, Confidence.C1,
       "w 0.30, jambe base. L'ESI n'est PAS un PMI : échelle et construction différentes. "
       "Le z-score le rend comparable, le niveau brut non."),
    _s("gdpc1", "PIB réel US", Kind.OBSERVED, "D1", (1, 5), Leg.QUOTE,
       Provider.FRED, "GDPC1", Frequency.QUARTERLY, Confidence.C1, "numérateur de l'output gap"),
    _s("gdppot", "PIB potentiel US (CBO)", Kind.OBSERVED, "D1", (1, 5), Leg.QUOTE,
       Provider.FRED, "GDPPOT", Frequency.QUARTERLY, Confidence.C1, "dénominateur de l'output gap"),
    _s("output_gap_us", "Output gap US", Kind.DERIVED, "D1", (1, 5), Leg.QUOTE,
       Provider.NONE, None, Frequency.QUARTERLY, Confidence.C1,
       "w 0.25. (GDPC1 − GDPPOT)/GDPPOT. Variante Hamilton évoquée côté calculateur, à trancher "
       "contre le gap CBO.", depends_on=("gdpc1", "gdppot")),
    _s("output_gap_ez", "Output gap zone euro (AMECO)", Kind.OBSERVED, "D1", (1,), Leg.BASE,
       Provider.ECB_SDMX, f"AME.A.{AMECO_ZONE}.1.0.0.0.AVGDGP", Frequency.ANNUAL, Confidence.C1,
       "w 0.25, jambe base. ANNUEL côté AMECO contre TRIMESTRIEL côté US : l'asymétrie de "
       "fréquence est réelle et non résolue."),
    _s("lei", "Indicateur avancé (Philly Fed)", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.FRED, "USSLIND", Frequency.MONTHLY, Confidence.C1,
       "w 0.20, entre aussi dans timing_factor. Le LEI du Conference Board est propriétaire "
       "et sans API — USSLIND est public et actif."),
    _s("sahm", "Règle de Sahm (temps réel)", Kind.OBSERVED, "D1", (), Leg.QUOTE,
       Provider.FRED, "SAHMREALTIME", Frequency.MONTHLY, Confidence.C1,
       "w 0.15. REALTIME et pas CURRENT : CURRENT est recalculé sur données révisées et "
       "introduit du look-ahead dans tout backtest."),
    _s("ip", "Production industrielle US", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.FRED, "INDPRO", Frequency.MONTHLY, Confidence.C1,
       "w 0.10. Le « réalisé » du timing_factor : c'est lui qu'on confronte au LEI."),
    _s("timing_factor", "Facteur de timing D1", Kind.DERIVED, "D1", (5,), Leg.NONE,
       Provider.NONE, None, Frequency.NONE, Confidence.C1,
       "×0.70 si l'avancé et le réalisé ne confirment pas. Le −30 % est un PLACEHOLDER de "
       "calibration, pas une valeur de spec.", depends_on=("lei", "pmi_us", "ip")),
    _s("oecd_cli", "Indicateur avancé composite OCDE", Kind.OBSERVED, "D1", (5,), Leg.GLOBAL,
       Provider.SDMX_INTL, None, Frequency.MONTHLY, Confidence.C2,
       "L'OCDE a changé de plateforme : l'ancien MEI_CLI n'est plus fiable.",
       catalog_hint="dataflow OECD.SDD.STES — clé finale au codelist (miroir DBnomics)"),
    _s("gdpnow", "Nowcast GDPNow (Atlanta Fed)", Kind.OBSERVED, "D1", (), Leg.QUOTE,
       Provider.FRED, "GDPNOW", Frequency.DAILY, Confidence.C1,
       "Contrôle de cohérence du gap. La série FRED évite tout parsing de la page Atlanta Fed."),
    _s("totbkcr", "Crédit bancaire total US", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.FRED, "TOTBKCR", Frequency.WEEKLY, Confidence.C1, "série brute du credit impulse"),
    _s("credit_impulse", "Impulsion de crédit", Kind.DERIVED, "D1", (5,), Leg.QUOTE,
       Provider.NONE, None, Frequency.WEEKLY, Confidence.C1,
       "Ratio à calculer contre le PIB — la série brute ne suffit pas.",
       depends_on=("totbkcr", "gdpc1")),
    _s("unrate", "Taux de chômage US", Kind.OBSERVED, "D1", (2, 5), Leg.QUOTE,
       Provider.FRED, "UNRATE", Frequency.MONTHLY, Confidence.C1,
       "Aucune collecte propre à D1 — réutilisation directe par Arb 2 et Arb 5."),
    _s("nrou", "NAIRU US (estimation CBO)", Kind.OBSERVED, "D1", (2, 5), Leg.QUOTE,
       Provider.FRED, "NROU", Frequency.QUARTERLY, Confidence.C1, "ancre du marché du travail"),
    _s("unrate_ez", "Taux de chômage zone euro", Kind.OBSERVED, "D1", (2,), Leg.BASE,
       Provider.EUROSTAT, "une_rt_m", Frequency.MONTHLY, Confidence.C1, "filtre geo=EA20"),
    _s("nairu_ez", "NAWRU zone euro (AMECO)", Kind.OBSERVED, "D1", (2,), Leg.BASE,
       Provider.ECB_SDMX, None, Frequency.ANNUAL, Confidence.C2,
       "Même connecteur SDMX que l'output gap AMECO, variable différente.",
       catalog_hint="dataflow AME — variable NAWRU, code exact au catalogue CSV du dataflow"),
    _s("t10y2y", "Pente 2s10s US", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.FRED, "T10Y2Y", Frequency.DAILY, Confidence.C1, "signal de cycle, partagé Arb 5"),
    _s("spf_us", "Consensus de croissance US (SPF)", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.PHILADELPHIA_FED, "SPF", Frequency.QUARTERLY, Confidence.C1,
       "Fichiers XLSX trimestriels à parser : l'absence de REST est STRUCTURELLE, pas un trou "
       "d'accès."),
    _s("spf_ez", "Consensus de croissance EZ (SPF BCE)", Kind.OBSERVED, "D1", (5,), Leg.BASE,
       Provider.ECB_SDMX, "SPF.Q.U2.RGDP.POINT.M0M.Q.ECB", Frequency.QUARTERLY, Confidence.C1,
       "Structure de clé vérifiée sur la variante HICP (SPF.M.U2.HICP.POINT.M0M.Q.ECB) ; "
       "topic RGDP par substitution."),
    _s("sp500", "S&P 500", Kind.OBSERVED, "D1", (5,), Leg.QUOTE,
       Provider.FRED, "SP500", Frequency.DAILY, Confidence.C1, "risk appetite, jambe pricée"),
    _s("dax", "DAX", Kind.OBSERVED, "D1", (5,), Leg.BASE,
       Provider.YFINANCE, "^GDAXI", Frequency.DAILY, Confidence.C1,
       "Deux fournisseurs pour une même grandeur — vérifier l'alignement des jours fériés "
       "AVANT de soustraire."),
    _s("leading_turn", "Détection de retournement", Kind.DERIVED, "D1", (5,), Leg.NONE,
       Provider.NONE, None, Frequency.NONE, Confidence.C1,
       "Module de code, pas une source — et le meilleur candidat ML de la dimension.",
       depends_on=("oecd_cli", "pmi_us", "t10y2y")),

    # --- D2 · Politique monétaire (label absorbé par Arb 1, poids 0) ---------------------
    _s("ois_usd", "Anticipations Fed (futures ZQ)", Kind.OBSERVED, "D2", (1,), Leg.QUOTE,
       Provider.YFINANCE, "ZQ", Frequency.DAILY, Confidence.C1,
       "taux implicite = 100 − prix. FedWatch n'a jamais eu d'API ; la méthodologie étant "
       "publique, on refait le calcul (résout la ligne ✕ C3 de la spec arbitrage)."),
    _s("fedwatch_calc", "Probabilités FOMC implicites", Kind.DERIVED, "D2", (1,), Leg.NONE,
       Provider.NONE, None, Frequency.DAILY, Confidence.C1,
       "Interpolation entre paliers de 25 pb sur le taux implicite ZQ — la convention "
       "d'interpolation est sous contrôle, ce que FedWatch ne permettait pas.",
       depends_on=("ois_usd",)),
    _s("estr", "€STR", Kind.OBSERVED, "D2", (1,), Leg.BASE,
       Provider.ECB_SDMX, "EST.B.EU000A2X2A25.WT", Frequency.DAILY, Confidence.C1,
       "Moyenne tronquée pondérée par volume — le vrai taux au jour le jour, publié 08:00 CET."),
    _s("yc_spot", "Courbe souveraine AAA (1A)", Kind.OBSERVED, "D2", (1,), Leg.BASE,
       Provider.ECB_SDMX, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y", Frequency.DAILY, Confidence.C1,
       "SOUVERAINE, pas OIS — porte une prime de terme et de rareté du collatéral que l'OIS "
       "n'a pas. C'est la source du bruit asymétrique entre les deux jambes de l'Arb 1.",
       extra=("YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y", "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y")),
    _s("yc_fwd_1y", "Forward instantané 1 an", Kind.OBSERVED, "D2", (1,), Leg.BASE,
       Provider.ECB_SDMX, "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.IF_1Y", Frequency.DAILY, Confidence.C1,
       "Isole le taux FUTUR au lieu de moyenner le chemin — meilleur proxy d'anticipation "
       "que le spot 1Y."),
    _s("ecbbs", "Bilan Eurosystème", Kind.OBSERVED, "D2", (), Leg.BASE,
       Provider.ECB_SDMX, "ILM.W.U2.C.A070100.U2.EUR", Frequency.WEEKLY, Confidence.C1,
       "Titres de politique monétaire : meilleur proxy du rythme de QT. Le total "
       "(ILM.W.U2.C.T000000.Z5.Z01) est bruité par les opérations de refinancement.",
       extra=("ILM.W.U2.C.T000000.Z5.Z01",)),
    _s("dff", "Fed Funds effectif", Kind.OBSERVED, "D2", (1, 4), Leg.QUOTE,
       Provider.FRED, "DFF", Frequency.DAILY, Confidence.C1,
       "OBSERVÉ, pas anticipé — ne pas confondre avec ois_term."),
    _s("ecbdfr", "Taux de dépôt BCE", Kind.OBSERVED, "D2", (1, 4), Leg.BASE,
       Provider.FRED, "ECBDFR", Frequency.DAILY, Confidence.C1, "observé, pas anticipé"),
    _s("r_star_us", "Taux neutre réel US (HLW)", Kind.OBSERVED, "D2", (1,), Leg.QUOTE,
       Provider.NY_FED, None, Frequency.QUARTERLY, Confidence.C2,
       "Holston-Laubach-Williams — fichier public trimestriel, pas de série FRED directe.",
       catalog_hint="format du fichier publié par la NY Fed à confirmer avant parsing"),
    _s("r_star_ez", "Taux neutre réel zone euro", Kind.OBSERVED, "D2", (1,), Leg.BASE,
       Provider.NONE, None, Frequency.QUARTERLY, Confidence.C3,
       "Non traité : gap non résolu — à traiter AVANT de coder la jambe EUR complète de l'Arb 1."),
    _s("uip_implied", "Dépréciation implicite (UIP)", Kind.DERIVED, "D2", (4,), Leg.NONE,
       Provider.NONE, None, Frequency.DAILY, Confidence.C2,
       "Parité couverte : se dérive de rate_diff, pas de collecte séparée nécessaire.",
       depends_on=("dff", "ecbdfr")),
    _s("d2_label", "Étiquette D2 (absorbée)", Kind.DERIVED, "D2", (1,), Leg.NONE,
       Provider.NONE, None, Frequency.NONE, Confidence.C1,
       "Sortie d'affichage en labels_absorbes, poids 0 — magnitude portée par l'Arb 1. "
       "L'oublier ne casse rien, mais son absence rend le terminal illisible."),

    # --- D3 · Inflation (label absorbé par Arb 2, poids 0) -------------------------------
    _s("pcepilfe", "Core PCE", Kind.OBSERVED, "D3", (1, 2), Leg.QUOTE,
       Provider.FRED, "PCEPILFE", Frequency.MONTHLY, Confidence.C1,
       "C'est la cible OFFICIELLE de la Fed, pas le CPI."),
    _s("hicp_ez", "HICP zone euro", Kind.OBSERVED, "D3", (1, 2), Leg.BASE,
       Provider.ECB_SDMX, "HICP.M.U2.N.000000.4.ANR", Frequency.MONTHLY, Confidence.C1,
       "⚠ Le dataflow ICP est DISCONTINUÉ depuis le 04.02.2026, remplacé par HICP à structure "
       "de clé identique. Une clé ICP codée en dur renvoie une erreur, pas une valeur fausse."),
    _s("t10yie", "Breakeven 10 ans US", Kind.OBSERVED, "D3", (2,), Leg.QUOTE,
       Provider.FRED, "T10YIE", Frequency.DAILY, Confidence.C1,
       "Ténor 10 ans, choisi pour matcher la jambe EUR — voir l'alerte Bund€i."),
    _s("t5yie", "Breakeven 5 ans US", Kind.OBSERVED, "D3", (2,), Leg.QUOTE,
       Provider.FRED, "T5YIE", Frequency.DAILY, Confidence.C1, "variante d'horizon"),
    _s("t5yifr", "Forward 5y5y US", Kind.OBSERVED, "D3", (2,), Leg.QUOTE,
       Provider.FRED, "T5YIFR", Frequency.DAILY, Confidence.C1,
       "Ancre par défaut de la courbe de Phillips US : quotidien et market-based, cohérent "
       "avec la jambe TIPS (résout le « à trancher » de la spec arbitrage)."),
    _s("dfii10", "TIPS réel 10 ans", Kind.OBSERVED, "D3", (2, 3), Leg.QUOTE,
       Provider.FRED, "DFII10", Frequency.DAILY, Confidence.C1,
       "Seule ligne de D3 qui sort de D3 : elle alimente le BEER."),
    _s("bund_nominal", "Bund nominal 10 ans (Svensson)", Kind.OBSERVED, "D3", (2,), Leg.BASE,
       Provider.BUNDESBANK,
       "BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A", Frequency.DAILY, Confidence.C1,
       "Courbe Svensson quotidienne — R10XX encode la maturité résiduelle (R05XX pour 5 ans).",
       extra=("BBSIS.D.I.ZST.ZI.EUR.S1311.B.A604.R05XX.R.A.A._Z._Z.A",)),
    _s("bundei_real", "Bund€i réel (par ISIN)", Kind.OBSERVED, "D3", (2, 3), Leg.BASE,
       Provider.BUNDESBANK, None, Frequency.DAILY, Confidence.C2,
       "ISIN de référence choisi (DE0001030575) et connecteur écrit : il ne manque QUE le "
       "relevé de la clé de série. C'est la ligne au meilleur rapport effort/déblocage — elle "
       "ferme D3 et rdiff côté D5.",
       catalog_hint="portail Bundesbank, thème W138 — repli : factsheet Finanzagentur"),
    _s("ilsw_ez", "Breakeven zone euro", Kind.DERIVED, "D3", (2,), Leg.BASE,
       Provider.NONE, None, Frequency.DAILY, Confidence.C1,
       "Méthode Finanzagentur : simple écart de rendement nominal − réel. Biais connus NON "
       "corrigés : prime de liquidité du Bund€i, saisonnalité HICP — à documenter, pas à "
       "neutraliser en douce.", depends_on=("bund_nominal", "bundei_real")),
    _s("ahe", "Salaire horaire moyen", Kind.OBSERVED, "D3", (2,), Leg.QUOTE,
       Provider.FRED, "CES0500000003", Frequency.MONTHLY, Confidence.C1, "pression de coûts"),
    _s("eci", "Coût du travail (ECI)", Kind.OBSERVED, "D3", (2,), Leg.QUOTE,
       Provider.FRED, "ECIALLCIV", Frequency.QUARTERLY, Confidence.C1,
       "Trimestriel mais bien moins bruité que l'AHE — à préférer si un seul doit être gardé."),
    _s("anchor_ez", "Inflation ancrée zone euro (SPF)", Kind.OBSERVED, "D3", (2,), Leg.BASE,
       Provider.ECB_SDMX, "SPF.M.U2.HICP.POINT.M0M.Q.ECB", Frequency.QUARTERLY, Confidence.C1,
       "Structure de clé vérifiée — même dataflow que le consensus de croissance EZ."),
    _s("beta_phillips", "Pente de la courbe de Phillips (β)", Kind.PARAMETER, "D3", (2,),
       Leg.NONE, Provider.NONE, None, Frequency.NONE, Confidence.C3,
       "Paramètre à estimer PAR PAYS — PLACEHOLDER. Pas une donnée à collecter."),

    # --- D4 · Régime de risque (type B modulateur, TTL 4 h, fail-closed) -----------------
    _s("vixcls", "VIX", Kind.OBSERVED, "D4", (4, 6), Leg.GLOBAL,
       Provider.FRED, "VIXCLS", Frequency.DAILY, Confidence.C1, "composant du régime"),
    _s("hyoas", "Spread high yield", Kind.OBSERVED, "D4", (4,), Leg.GLOBAL,
       Provider.FRED, "BAMLH0A0HYM2", Frequency.DAILY, Confidence.C1,
       "Le plus réactif des trois piliers du régime."),
    _s("nfci", "Conditions financières (NFCI)", Kind.OBSERVED, "D4", (4,), Leg.GLOBAL,
       Provider.FRED, "NFCI", Frequency.WEEKLY, Confidence.C1,
       "HEBDOMADAIRE — incompatible avec une lecture littérale du TTL 4 h de D4 "
       "(voir KNOWN_CONFLICTS d4_ttl_vs_nfci)."),
    _s("move", "MOVE (volatilité obligataire)", Kind.OBSERVED, "D4", (), Leg.GLOBAL,
       Provider.YFINANCE, "^MOVE", Frequency.DAILY, Confidence.C1,
       "Ligne SUPPRIMABLE : VIX + HY + NFCI suffisent à définir le régime sans elle."),
    _s("igoas", "Spread investment grade", Kind.OBSERVED, "D4", (), Leg.GLOBAL,
       Provider.FRED, "BAMLC0A0CM", Frequency.DAILY, Confidence.C1,
       "Second rang — redondant avec HY, à garder pour le diagnostic, pas dans la formule."),
    _s("stlfsi", "Stress financier St. Louis", Kind.OBSERVED, "D4", (), Leg.GLOBAL,
       Provider.FRED, "STLFSI4", Frequency.WEEKLY, Confidence.C1, "second rang, diagnostic"),
    _s("dtwexbgs", "Dollar index (broad)", Kind.OBSERVED, "D4", (), Leg.GLOBAL,
       Provider.FRED, "DTWEXBGS", Frequency.DAILY, Confidence.C1,
       "BROAD, pas le DXY — pondération commerciale différente."),
    _s("cot_fx", "Positionnement COT (TFF)", Kind.OBSERVED, "D4", (6,), Leg.GLOBAL,
       Provider.CFTC_SOCRATA, "gpe5-46if", Frequency.WEEKLY, Confidence.C1,
       "Hebdomadaire (mardi, publié vendredi) — historique gratuit et RÉTROACTIF, point "
       "important pour tout z-score. Alimente l'Arb 6bis."),
    _s("d4_coeff", "Coefficient de régime D4", Kind.PARAMETER, "D4", (4,), Leg.NONE,
       Provider.NONE, None, Frequency.NONE, Confidence.C3,
       "Seuils de bascule GREEN/YELLOW/ORANGE/RED — PLACEHOLDER, et valeur RED contradictoire "
       "entre deux sources (voir KNOWN_CONFLICTS d4_red_coeff)."),
    _s("spot_momentum", "Momentum du spot", Kind.DERIVED, "D4", (6,), Leg.NONE,
       Provider.NONE, None, Frequency.DAILY, Confidence.C1,
       "|variation| du spot normalisée — seule variable NON bloquée de l'Arb 6.",
       depends_on=("dexuseu",)),
    _s("rr_current", "Risk Reversal 25Δ", Kind.OBSERVED, "D4", (6,), Leg.GLOBAL,
       Provider.NONE, None, Frequency.DAILY, Confidence.C3,
       "Donnée de gré à gré, jamais cotée publiquement — bloquant CONFIRMÉ, aucune alternative "
       "gratuite. Deux voies ouvertes : skew approché depuis les chaînes d'options FX du CME, "
       "ou remplacement par l'Arb 6bis (positionnement COT)."),
    _s("rr_history", "Historique RR (moyenne, écart-type)", Kind.OBSERVED, "D4", (6,), Leg.GLOBAL,
       Provider.NONE, None, Frequency.DAILY, Confidence.C3, "même blocage que rr_current"),

    # --- D5 · Facteurs structurels (type A, TTL 90 j, poids LONG 0.30) -------------------
    _s("rdiff", "Différentiel de taux réels", Kind.DERIVED, "D5", (3,), Leg.DIFF,
       Provider.NONE, None, Frequency.DAILY, Confidence.C1,
       "1ʳᵉ composante du BEER. Hérite du statut de bundei_real : la jambe US est vérifiée, "
       "la jambe EZ attend sa clé. Aucune collecte propre à faire.",
       depends_on=("dfii10", "bundei_real")),
    _s("nfa", "Position extérieure nette", Kind.OBSERVED, "D5", (3,), Leg.DIFF,
       Provider.SDMX_INTL, None, Frequency.QUARTERLY, Confidence.C2,
       "2ᵉ composante du BEER. Trimestriel avec retard de plusieurs mois — c'est ce qui "
       "justifie le TTL de 90 j.",
       catalog_hint="data.imf.org — dataflow IMF.STA/BOP, clé au DSD (miroir DBnomics)"),
    _s("tot", "Termes de l'échange", Kind.OBSERVED, "D5", (3,), Leg.DIFF,
       Provider.SDMX_INTL, None, Frequency.QUARTERLY, Confidence.C2,
       "3ᵉ composante du BEER. Même réserve de fréquence que NFA.",
       catalog_hint="FMI / OCDE — même connecteur que nfa et oecd_cli, clé au codelist"),
    _s("ophnfb", "Productivité horaire US", Kind.OBSERVED, "D5", (3,), Leg.QUOTE,
       Provider.FRED, "OPHNFB", Frequency.QUARTERLY, Confidence.C1,
       "4ᵉ composante du BEER (effet Balassa)"),
    _s("prod_ez", "Productivité zone euro", Kind.OBSERVED, "D5", (3,), Leg.BASE,
       Provider.EUROSTAT, "nama_10_lp_ulc", Frequency.ANNUAL, Confidence.C1,
       "Même connecteur que le PMI EZ."),
    _s("reer", "Taux de change effectif réel", Kind.OBSERVED, "D5", (3,), Leg.DIFF,
       Provider.SDMX_INTL, "WS_EER_M/M.R.B.XM", Frequency.MONTHLY, Confidence.C1,
       "Validation croisée du misalignment. Exemple validé côté BIS : M.N.B.CH ; cible zone "
       "euro M.R.B.XM (real, broad)."),
    _s("bopgstb", "Balance commerciale US", Kind.OBSERVED, "D5", (3,), Leg.QUOTE,
       Provider.FRED, "BOPGSTB", Frequency.MONTHLY, Confidence.C1,
       "Mensuel — la seule ligne rapide d'une dimension par ailleurs lente."),
    _s("dexuseu", "Spot EUR/USD", Kind.OBSERVED, "D5", (3, 4, 6), Leg.DIFF,
       Provider.FRED, "DEXUSEU", Frequency.DAILY, Confidence.C1,
       "Comparé au BEER pour le misalignment ; sert aussi la dépréciation de l'Arb 4."),
    _s("sigma_beer", "Écart-type du misalignment (σ)", Kind.DERIVED, "D5", (3,), Leg.NONE,
       Provider.NONE, None, Frequency.NONE, Confidence.C1,
       "Normalisation en z-score — module de code. Prévoir un PLANCHER : un σ proche de zéro "
       "fabrique des z-scores infinis.", depends_on=("dexuseu",)),
)

BY_KEY: dict[str, SeriesSpec] = {s.key: s for s in CATALOG}


# =============================================================================================
# Incohérences déclarées — « à trancher, pas des bugs à patcher en douce »
# =============================================================================================

KNOWN_CONFLICTS: tuple[dict, ...] = (
    {
        "topic": "d4_red_coeff",
        "question": "Combien vaut le coefficient RED du régime D4 ?",
        "values": {"registre_N3": 0.4, "referentiel_indicateurs": 0.0},
        "impact": "À 0.0 le régime rouge ANNULE le carry ; à 0.4 il le réduit seulement — et "
                  "ORANGE vaut déjà 0.4, donc à 0.4 RED et ORANGE deviennent indistinguables.",
        "code_actuel": "strategies.youssef.GATES applique carry 0.0 en RED (valeur du "
                       "référentiel d'indicateurs).",
        "status": "OUVERT",
    },
    {
        "topic": "d4_ttl_vs_nfci",
        "question": "Un TTL de 4 h peut-il s'appliquer à une composante hebdomadaire ?",
        "values": {"ttl_d4_h": 4, "frequence_nfci": "hebdomadaire"},
        "impact": "Appliqué littéralement à l'ÂGE D'OBSERVATION avec la règle fail-closed, il "
                  "forcerait un RED permanent. Constat qui va plus loin que la spec : VIXCLS et "
                  "BAMLH0A0HYM2 sont des séries de CLÔTURE quotidienne — un seuil de 4 h sur "
                  "l'âge d'observation les tuerait aussi, pas seulement le NFCI.",
        "code_actuel": "Deux axes distincts ici : `cache_max_age_s` (âge de NOTRE copie, piloté "
                       "par le TTL de la dimension) et `observation_max_age_s` (âge de la "
                       "publication, piloté par la FRÉQUENCE de la série).",
        "status": "OUVERT",
    },
    {
        "topic": "k_etape1_vs_seuils_etape3",
        "question": "Pourquoi le système ne déclenche-t-il jamais de GO ?",
        "values": {"k_etape1": 25, "seuils_etape3": "échelle d'autorité"},
        "impact": "Le k uniforme de l'Étape 1 et les seuils d'autorité de l'Étape 3 ont été "
                  "posés sur des échelles INCOMPATIBLES — mécaniquement, aucun GO ne se "
                  "déclenche. Défaut connu, à corriger par une calibration CONJOINTE des deux "
                  "étapes, pas séparément.",
        "code_actuel": "Aucun — la calibration n'est pas faite.",
        "status": "OUVERT",
    },
)


# =============================================================================================
# Fraîcheur & profondeur — deux axes qu'on ne mélange jamais
# =============================================================================================

# Âge maximal de la PUBLICATION, dérivé de la fréquence de la série : une série hebdomadaire est
# légitimement vieille d'une semaine, l'exiger « fraîche de 4 h » n'est pas une exigence, c'est
# un bug. Marges pour week-ends, jours fériés et retards de publication. v1 provisional.
_OBSERVATION_MAX_AGE_S: dict[Frequency, float] = {
    Frequency.DAILY: 4 * _DAY,
    Frequency.WEEKLY: 10 * _DAY,
    Frequency.MONTHLY: 45 * _DAY,
    Frequency.QUARTERLY: 150 * _DAY,
    Frequency.ANNUAL: 500 * _DAY,
    Frequency.NONE: 0.0,
}

# Fenêtre du z-score en OBSERVATIONS, jamais en jours calendaires : « un z-score sur 252 jours
# n'a pas de sens sur une série trimestrielle ». 252 est la valeur de la spec (AUTORITÉ) ; les
# fenêtres réduites sont des PLACEHOLDER — la spec dit qu'il en faut, pas lesquelles.
_ZSCORE_WINDOW: dict[Frequency, int] = {
    Frequency.DAILY: 252,
    Frequency.WEEKLY: 104,
    Frequency.MONTHLY: 60,
    Frequency.QUARTERLY: 40,
    Frequency.ANNUAL: 20,
    Frequency.NONE: 0,
}


def cache_max_age_s(key: str) -> float:
    """Âge maximal de NOTRE copie (dernier fetch réussi) — piloté par le TTL de la dimension.
    C'est cet axe-là que la règle fail-closed de D4 doit lire."""
    spec = BY_KEY.get(key)
    if spec is None:
        return 0.0                       # inconnu → périmé d'office (fail-closed, §3)
    return DIMENSIONS[spec.dimension].ttl_s


def observation_max_age_s(key: str) -> float:
    """Âge maximal de la PUBLICATION — piloté par la fréquence de la série."""
    spec = BY_KEY.get(key)
    if spec is None:
        return 0.0
    return _OBSERVATION_MAX_AGE_S.get(spec.frequency, 0.0)


def zscore_window(key: str) -> int:
    """Profondeur exigée avant de produire un z-score, en OBSERVATIONS. 0 = pas de z-score
    (ligne dérivée ou paramètre)."""
    spec = BY_KEY.get(key)
    if spec is None:
        return 0
    return _ZSCORE_WINDOW.get(spec.frequency, 0)


# =============================================================================================
# Doctrine de confiance — le seul portillon d'accès
# =============================================================================================

def fetch_block_reason(key: str) -> Optional[str]:
    """`None` = ligne collectable. Sinon, le motif — en français, et il dit QUOI FAIRE.

    Fail-closed : une clé inconnue est bloquée, jamais autorisée par défaut."""
    spec = BY_KEY.get(key)
    if spec is None:
        return f"« {key} » n'est pas au registre — rien à collecter tant qu'il n'y est pas."
    if spec.kind is Kind.PARAMETER:
        return ("paramètre à CALIBRER (60 trades), pas une donnée : aucune requête ne le "
                "fournira" + (f" — {spec.note}" if spec.note else ""))
    blocked_deps = [d for d in spec.depends_on if fetch_block_reason(d) is not None]
    if spec.kind is Kind.DERIVED:
        if blocked_deps:
            return (f"calcul dérivé, et sa dépendance est bloquée : {', '.join(blocked_deps)} — "
                    "ouvrir le maillon avant l'étage du dessus")
        return "calcul dérivé, pas une collecte — voir depends_on"
    if spec.confidence is Confidence.C2:
        hint = spec.catalog_hint or "catalogue du fournisseur"
        return (f"C2 — relever l'identifiant au CATALOGUE avant tout codage en dur ({hint})")
    if spec.confidence is Confidence.C3:
        return f"C3 — bloqué, ne pas commencer : {spec.note}"
    if blocked_deps:
        return f"dépendance bloquée : {', '.join(blocked_deps)}"
    return None


def fetchable() -> tuple[SeriesSpec, ...]:
    """Les lignes qu'on a le droit d'aller chercher, aujourd'hui, telles quelles."""
    return tuple(s for s in CATALOG if fetch_block_reason(s.key) is None)


# =============================================================================================
# Vues par indicateur — la structure demandée : dimensions et arbitrages, pas fournisseurs
# =============================================================================================

def by_dimension() -> dict[str, tuple[SeriesSpec, ...]]:
    out: dict[str, list[SeriesSpec]] = {code: [] for code in DIMENSIONS}
    for spec in CATALOG:
        out.setdefault(spec.dimension, []).append(spec)
    return {k: tuple(v) for k, v in out.items()}


def by_arbitrage() -> dict[int, tuple[SeriesSpec, ...]]:
    out: dict[int, list[SeriesSpec]] = {a.arb_id: [] for a in ARBITRAGES}
    for spec in CATALOG:
        for arb_id in spec.arbitrages:
            out.setdefault(arb_id, []).append(spec)
    return {k: tuple(v) for k, v in out.items()}


def by_provider() -> dict[str, tuple[SeriesSpec, ...]]:
    out: dict[str, list[SeriesSpec]] = {}
    for spec in CATALOG:
        out.setdefault(spec.provider.value, []).append(spec)
    return {k: tuple(v) for k, v in out.items()}


def directional_dimensions() -> tuple[str, ...]:
    """Les SEULES dimensions qui produisent un score directionnel. Additionner cinq « scores D »
    serait un contresens : D2/D3 sont absorbés (leur contenu passe par Arb 1 / Arb 2, donc il
    compterait deux fois), et D4 n'est pas du même type — il MULTIPLIE."""
    return tuple(code for code, d in DIMENSIONS.items() if d.kind == "A")


# =============================================================================================
# Piège d'échéance — la règle de bascule d'ISIN, écrite MAINTENANT
# =============================================================================================

def bundei_roll_state(now: float) -> dict:
    """Écart de ténor entre les deux jambes du breakeven, MESURÉ et non supposé.

    La jambe US (T10YIE) reste à 10 ans constants ; le linker allemand raccourcit d'un an par an
    et ne sera pas remplacé (programme arrêté depuis 2024). Le breakeven EUR dérive donc
    mécaniquement vers le court terme. Écrire la règle maintenant, « pas le jour où la série
    cassera, et surtout pas après plusieurs mois de comparaison silencieuse entre deux
    maturités différentes »."""
    if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
        return {**_bundei_id(), "residual_years": None, "tenor_drift_years": None,
                "status": "INCONNU",
                "message": "horloge douteuse — écart de ténor non mesurable"}
    residual = (BUNDEI["maturity_ts"] - float(now)) / _YEAR_S
    if residual <= 0:
        return {**_bundei_id(), "residual_years": round(residual, 2), "tenor_drift_years": None,
                "status": "ECHU",
                "message": f"{BUNDEI['label']} est ÉCHU — le breakeven EUR n'a plus de support"}
    drift = US_BREAKEVEN_TENOR_Y - residual
    over = drift > BUNDEI_MAX_TENOR_DRIFT_Y
    return {
        **_bundei_id(),
        "residual_years": round(residual, 2),
        "tenor_drift_years": round(drift, 2),
        "max_drift_years": BUNDEI_MAX_TENOR_DRIFT_Y,
        "status": "BASCULE_REQUISE" if over else "OK",
        "message": (f"jambe EUR à {residual:.1f} ans contre {US_BREAKEVEN_TENOR_Y:.0f} ans côté "
                    f"US : {drift:.1f} an(s) d'écart de ténor"
                    + (" — bascule d'ISIN requise avant de comparer les deux breakevens"
                       if over else "")),
    }


def _bundei_id() -> dict:
    return {"isin": BUNDEI["isin"], "label": BUNDEI["label"],
            "maturity": BUNDEI["maturity_label"]}
