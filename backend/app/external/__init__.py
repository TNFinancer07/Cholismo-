"""Sources externes — Niveau 3, hors flux microstructure (D-062).

    from app.external import ExternalDataModule, build_default

Ce paquet TRANSPORTE la donnée (calendrier éco F5, VIX F3) ; les couches déterministes
existantes TRANCHENT (`macro_risk.compute_macro_risk`, `strategies.youssef.update_regime`,
`config.VIX_CRIT`). Voir `contracts.py` pour les invariants.
"""
from .contracts import (CalendarEvent, CalendarFetch, EconomicCalendarProvider, VixFetch,
                        VixProvider)
from .economic_calendar import (ChainedCalendar, FinnhubCalendar, LocalCalendarFile,
                                is_high_impact_news_near)
from .module import OWNED_FIELDS, ExternalDataModule, build_default
from .vix import ChainedVix, FredVix, StaticVix, TermStructureVix, VixRegime, get_vix_regime

__all__ = ["CalendarEvent", "CalendarFetch", "EconomicCalendarProvider", "VixFetch",
           "VixProvider", "ChainedCalendar", "FinnhubCalendar", "LocalCalendarFile",
           "is_high_impact_news_near", "ExternalDataModule", "OWNED_FIELDS", "build_default",
           "ChainedVix",
           "FredVix", "StaticVix", "TermStructureVix", "VixRegime", "get_vix_regime"]
