"""Order Flow in-house — Niveau 2 CALCUL (D-055).

Paquet du calculateur : un flux brut (carnet L2/MBO + Time & Sales) devient un
`OrderFlowSnapshot` portant les portes B1-B4, le profil de volume et l'ATR.

L'API publique tient en trois noms — un consommateur n'a pas à connaître le chemin du module :

    from app.orderflow import compute_snapshot, OrderFlowSnapshot, MOTIF_CODES

`MOTIF_CODES` énumère le vocabulaire des motifs de `missing` (« CODE : texte ») : il est FERMÉ
pour qu'un log ou un futur panneau puisse filtrer sans deviner.
"""
from .calculator import MOTIF_CODES, OrderFlowSnapshot, compute_snapshot

__all__ = ["MOTIF_CODES", "OrderFlowSnapshot", "compute_snapshot"]
