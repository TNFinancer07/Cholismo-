"""Central configuration. Every named threshold below marked AUTORITÉ comes verbatim from
PRD.md / TASKS.md / CLAUDE.md; the rest are PLACEHOLDER assumptions logged in DECISIONS.md."""
import os

# --- Cadences (CLAUDE §6 — fast/slow SSE channels; demo values, D-016) ---
FAST_TICK_SECONDS = 0.25
SLOW_TICK_SECONDS = float(os.getenv("SLOW_TICK_SECONDS", "15"))

# --- Freshness thresholds (per channel; GEX threshold is AUTORITÉ PRD §B2) ---
FAST_STALE_SECONDS = 3.0
FAST_ABSENT_SECONDS = 15.0
SLOW_STALE_SECONDS = SLOW_TICK_SECONDS * 3
SLOW_ABSENT_SECONDS = SLOW_TICK_SECONDS * 10
GEX_STALE_SECONDS = float(os.getenv("GEX_STALE_SECONDS", "180"))  # AUTORITÉ — single config

# --- Phase 0 / risk thresholds (AUTORITÉ TASKS §2.3 unless noted) ---
CHOP_CRIT = 61.8          # AUTORITÉ — CHOP >= 61.8 crit
VIX_CRIT = 30.0           # AUTORITÉ — VIX > 30 crit
RMS_WARN = 3.0            # AUTORITÉ — RMS >= 3 warn
RMS_CRIT = 5.0            # PLACEHOLDER — crit level, D-005
STREAK_AUDIT_THRESHOLD = 8  # AUTORITÉ — forced audit at 8 (PRD §C2)

# --- Decision window (PRD §C3) ---
ANTIPARALYSIS_SECONDS = float(os.getenv("ANTIPARALYSIS_SECONDS", "90"))  # AUTORITÉ (to revalidate vs S1 horizon)
DECISION_ARM_THRESHOLD = 60.0  # PLACEHOLDER — D-008

# --- Unified signal weights (AUTORITÉ PRD §0) ---
WEIGHT_STRUCTURE = 0.35
WEIGHT_ORDER_FLOW = 0.25
WEIGHT_MACRO = 0.20
WEIGHT_SENTIMENT = 0.15
WEIGHT_QUALITY = 0.05
DEGRADED_DENOMINATOR = 80.0  # AUTORITÉ — renormalize /80 when macro not calibrated

# --- Calibration / proof (AUTORITÉ CLAUDE §1/§2.7, PRD §C4) ---
CALIBRATION_WINDOW = 60          # N/60 gauge
CALIBRATION_TARGET_TRADES = 50   # 50+ disciplined trades
RESULT_SCORE_MIN_TRADES = 20     # result score displayed only after 20+
SIZING_LOCK_PCT = 50             # sizing locked at 50 %

# --- Reconciliation (PRD §Réconciliation; window/r-unit PLACEHOLDER D-018) ---
RECON_MATCH_WINDOW_SECONDS = float(os.getenv("RECON_MATCH_WINDOW_SECONDS", "120"))
R_UNIT_USD = float(os.getenv("R_UNIT_USD", "100"))

# --- Cognitive self-check (PRD §C5; TTL PLACEHOLDER) ---
SELF_CHECK_TTL_SECONDS = 3600

# --- Macro score (CLAUDE §8.1 — never calibrated by default) ---
MACRO_CALIBRATED = os.getenv("MACRO_CALIBRATED", "false").lower() == "true"

# --- Infra ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
EVENT_DB_PATH = os.getenv("EVENT_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "events.db"))
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))  # D-030
ENGINE_HEARTBEAT_MAX_AGE = 5.0  # engine itself stale -> fail-closed (D-005)

# --- AI (all async, out of hot path — CLAUDE §2.8/§7) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_TIMEOUT_SECONDS = 0.1       # AUTORITÉ — < 100 ms, fail-closed
CLAUDE_SCORING_PERIOD_SECONDS = 300
GEMINI_AUDIT_EVERY_N_TRADES = 20  # AUTORITÉ

# --- Liquidity Sweep detector (LangGraph, DÉTERMINISTE, advisory async — D-028) ---
SWEEP_TICK_SECONDS = float(os.getenv("SWEEP_TICK_SECONDS", "1.0"))  # hors hot path (§2.8)
SWEEP_RECENT_MAX = 8             # longueur du feed d'alertes récentes

# --- Trade Reconciliator (analytics FIFO sur snapshots — D-033) ---
# $/point par contrat. ES/MES = AUTORITÉ (spec) ; NQ/MNQ ajoutés (valeurs CME standard).
# Instrument inconnu → P&L USD non calculé (fail-closed §3, jamais inventé). Le risque de
# référence R réutilise R_UNIT_USD (défaut 100 $) — source unique, pas de double définition.
CONTRACT_POINT_VALUE = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}

# --- Footprint + imbalances (D-037) ---
# Ratio d'imbalance diagonal = AUTORITÉ (spec : > 300 %). Tick ES = 0.25. Le reste PLACEHOLDER
# (v1 provisional — durée de bougie, plancher de volume, fenêtres, à calibrer par l'humain).
PRICE_TICK = float(os.getenv("PRICE_TICK", "0.25"))                    # grille de prix ES
FOOTPRINT_CANDLE_SECONDS = float(os.getenv("FOOTPRINT_CANDLE_SECONDS", "60"))  # v1 provisional
FOOTPRINT_CANDLES = int(os.getenv("FOOTPRINT_CANDLES", "12"))         # bougies affichées
FOOTPRINT_IMBALANCE_RATIO = float(os.getenv("FOOTPRINT_IMBALANCE_RATIO", "3.0"))   # AUTORITÉ (300 %)
FOOTPRINT_MIN_IMBALANCE_VOL = float(os.getenv("FOOTPRINT_MIN_IMBALANCE_VOL", "1"))  # plancher, v1
FOOTPRINT_MAX_PRINTS = int(os.getenv("FOOTPRINT_MAX_PRINTS", "800"))  # tampon de prints accumulés

# --- CVD granulaire stratifié par taille d'ordre (D-038) ---
# Seuil retail/institutionnel = v1 provisional (PLACEHOLDER — pas d'AUTORITÉ dans /reference ;
# calibration owner: Sony). Bucket temporel, fenêtre de série, deadbands de divergence = v1.
CVD_SIZE_THRESHOLD = float(os.getenv("CVD_SIZE_THRESHOLD", "10"))         # ≥ seuil → institutionnel
CVD_STRAT_BUCKET_SECONDS = float(os.getenv("CVD_STRAT_BUCKET_SECONDS", "5"))   # échantillon série
CVD_STRAT_MAX_POINTS = int(os.getenv("CVD_STRAT_MAX_POINTS", "120"))     # points de série affichés
CVD_STRAT_MAX_PRINTS = int(os.getenv("CVD_STRAT_MAX_PRINTS", "4000"))    # tampon de prints accumulés
CVD_STRAT_DIV_LOOKBACK = int(os.getenv("CVD_STRAT_DIV_LOOKBACK", "12"))  # fenêtre de divergence
CVD_STRAT_DIV_MIN_PRICE = float(os.getenv("CVD_STRAT_DIV_MIN_PRICE", "0.5"))   # deadband prix (pts)
CVD_STRAT_DIV_MIN_DELTA = float(os.getenv("CVD_STRAT_DIV_MIN_DELTA", "25"))    # deadband delta (vol)

# --- Chaîne d'options (OMON) + Term Structure de volatilité (D-039) ---
# Bande ATM + eps FLAT = v1 provisional (PLACEHOLDER §11 — pas d'AUTORITÉ ; à calibrer). Bornes
# d'affichage. Ténors VIX = jours standards de la structure (CBOE).
OPTIONS_ATM_BAND = float(os.getenv("OPTIONS_ATM_BAND", "6"))          # |strike−U| ≤ bande → ATM
OPTIONS_MAX_EXPIRATIONS = int(os.getenv("OPTIONS_MAX_EXPIRATIONS", "4"))
OPTIONS_MAX_STRIKES = int(os.getenv("OPTIONS_MAX_STRIKES", "13"))    # strikes affichés par échéance
VOL_TERM_FLAT_EPS = float(os.getenv("VOL_TERM_FLAT_EPS", "0.3"))     # |Δ| ≤ eps → FLAT (points VIX)
VOL_TENORS = (("VIX9D", 9), ("VIX", 30), ("VIX3M", 93), ("VIX6M", 186))  # ténor → jours (CBOE)

# --- Heatmap de liquidité (LOB, canal rapide 4 Hz — D-036) ---
# Fenêtre glissante de colonnes temporelles (une par tick rapide de 0,25 s). 60 colonnes ≈ 15 s
# d'historique. Niveaux par côté = profondeur affichée du carnet (BOOK_DEPTH).
HEATMAP_COLS = int(os.getenv("HEATMAP_COLS", "60"))       # colonnes temporelles conservées
HEATMAP_LEVELS = int(os.getenv("HEATMAP_LEVELS", "10"))   # niveaux par côté (= BOOK_DEPTH)

# --- Cortex Cognitif — bias_detector (analytique post-hoc, DÉTERMINISTE — D-035) ---
# Seuils de détection de biais. FOMO/EXEC = PLACEHOLDER (v1 provisional, à calibrer par l'humain
# sur les 50+ trades) ; la fenêtre revenge est AUTORITÉ (spec : < 3 min après une perte).
FOMO_MAX_DURATION_S = float(os.getenv("FOMO_MAX_DURATION_S", "30"))       # v1 provisional
EXEC_MAX_DURATION_S = float(os.getenv("EXEC_MAX_DURATION_S", "1800"))     # v1 provisional (30 min)
REVENGE_WINDOW_S = float(os.getenv("REVENGE_WINDOW_S", "180"))            # AUTORITÉ — < 3 min

# --- log_scraper : tailer NT8 → auto-snapshot (OBSERVATION seule §2.1 — D-031) ---
# Désactivé par défaut : aucun log NT8 en démo. Activer avec un vrai dossier NT8
# (Documents/NinjaTrader 8/log). Fail-closed si le dossier/log du jour est absent.
LOG_SCRAPER_ENABLED = os.getenv("LOG_SCRAPER_ENABLED", "false").lower() == "true"
NT8_LOG_DIR = os.getenv("NT8_LOG_DIR", "")
LOG_SCRAPER_POLL_SECONDS = float(os.getenv("LOG_SCRAPER_POLL_SECONDS", "1.0"))  # hors hot path

# --- Session windows CET (PLACEHOLDER D-006) ---
LONDON_OBS_CET = (8, 12)      # 08:00–12:00 CET
OVERLAP_NY_CET = (14.5, 17.5)  # 14:30–17:30 CET
