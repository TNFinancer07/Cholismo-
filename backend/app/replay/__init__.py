"""Mode Replay local — rejouer un tape enregistré (Étape 1).

`replay_engine` lit un CSV et pousse des ticks validés vers un callback ; `mock_data_generator`
fabrique un fichier d'essai qui, conformément à CLAUDE §4, injecte les PATHOLOGIES réelles —
un mock trop propre est un piège.
"""
from .replay_engine import MAX_TICKS, SIDES, ReplayEngine, ReplaySummary

__all__ = ["ReplayEngine", "ReplaySummary", "MAX_TICKS", "SIDES"]
