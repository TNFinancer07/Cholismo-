"""
test_options_worker.py — suite pytest pour les fonctions pures et la machine
d'états du Slow Worker. Pas de dépendance réseau ni Redis dans ces tests :
la vérification bout en bout avec un vrai Redis est faite séparément
(voir verify_e2e.py) pour ne pas coupler correction logique et infrastructure.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))
import options_worker as w  # noqa: E402

NY_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# compute_basis_factor / convert_spx_to_es — vérifiés contre les valeurs
# déjà validées dans cholismo_pont_options_lsr_v2.html (section 6, v1)
# ---------------------------------------------------------------------------

class TestBasisConversion:
    def test_facteur_conforme_a_la_valeur_deja_verifiee(self):
        # SPX 6004, r=4.5%, q=1.3%, T=38j -> base = +20.04 pts (vérifié précédemment)
        t_years = 38 / 365
        factor = w.compute_basis_factor(0.045, 0.013, t_years)
        es = w.convert_spx_to_es(6004.0, factor)
        base = es - 6004.0
        assert base == pytest.approx(20.04, abs=0.05)

    def test_facteur_neutre_a_taux_egaux(self):
        assert w.compute_basis_factor(0.03, 0.03, 1.0) == pytest.approx(1.0)

    def test_facteur_augmente_avec_le_temps(self):
        f1 = w.compute_basis_factor(0.045, 0.013, 5 / 365)
        f2 = w.compute_basis_factor(0.045, 0.013, 60 / 365)
        assert f2 > f1

    def test_rejette_temps_negatif(self):
        with pytest.raises(ValueError):
            w.compute_basis_factor(0.045, 0.013, -1.0)

    def test_conversion_arrondit_au_tick(self):
        es = w.convert_spx_to_es(4975.0, 1.003337)
        remainder = (es / w.TICK_ES) % 1
        assert remainder == pytest.approx(0.0, abs=1e-9) or remainder == pytest.approx(1.0, abs=1e-9)

    def test_conversion_reproduit_lexemple_put_wall_deja_verifie(self):
        # Strike SPX 4975 -> ES 4991.50 (déjà vérifié dans le document Pont v2)
        es = w.convert_spx_to_es(4975.0, 1.003337)
        assert es == pytest.approx(4991.50, abs=0.01)


class TestThirdFridayExpiry:
    def test_troisieme_vendredi_de_mars_2026_est_un_vendredi(self):
        d = w._third_friday(2026, 3)
        assert d.weekday() == 4  # vendredi

    def test_troisieme_vendredi_tombe_bien_dans_la_troisieme_semaine(self):
        d = w._third_friday(2026, 6)
        assert 15 <= d.day <= 21

    def test_temps_jusqua_echeance_est_positif_avant_expiry(self):
        now = datetime(2026, 3, 1, 9, 0, tzinfo=NY_TZ)
        t = w.years_to_next_quarterly_expiry(now)
        assert t > 0

    def test_bascule_sur_le_trimestre_suivant_apres_expiry(self):
        expiry_march = w._third_friday(2026, 3)
        after = expiry_march.replace(hour=17)  # après la clôture du jour d'expiry
        t = w.years_to_next_quarterly_expiry(after)
        next_expiry = w._third_friday(2026, 6)
        expected = (next_expiry - after).total_seconds() / (365 * 24 * 3600)
        assert t == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# CircuitBreaker — transitions d'état
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_pas_down_initialement(self):
        cb = w.CircuitBreaker(max_consecutive_failures=3)
        assert cb.is_down is False

    def test_passe_down_au_seuil_exact(self):
        cb = w.CircuitBreaker(max_consecutive_failures=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_down is False
        cb.record_failure()
        assert cb.is_down is True

    def test_succes_reinitialise_le_compteur(self):
        cb = w.CircuitBreaker(max_consecutive_failures=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.is_down is False
        cb.record_failure()
        cb.record_failure()
        assert cb.is_down is False  # nouveau compte : 2, pas 3

    def test_backoff_croissant_et_borne(self):
        cb = w.CircuitBreaker(backoff_base_seconds=2.0, backoff_max_seconds=20.0)
        vals = []
        for _ in range(8):
            cb.record_failure()
            vals.append(cb.backoff_seconds())
        assert vals == sorted(vals)  # strictement croissant puis plafonné
        assert max(vals) <= 20.0

    def test_backoff_nul_sans_echec(self):
        cb = w.CircuitBreaker()
        assert cb.backoff_seconds() == 0.0


# ---------------------------------------------------------------------------
# MockVendorClient — déterminisme et forme des données
# ---------------------------------------------------------------------------

class TestMockVendorClient:
    def test_meme_seed_meme_sequence(self):
        async def run():
            c1 = w.MockVendorClient(seed=42)
            c2 = w.MockVendorClient(seed=42)
            g1 = await c1.fetch_gex()
            g2 = await c2.fetch_gex()
            return g1, g2
        g1, g2 = asyncio.run(run())
        assert g1.gamma_zero_es == g2.gamma_zero_es
        assert g1.put_wall_es == g2.put_wall_es

    def test_put_wall_sous_call_wall(self):
        async def run():
            c = w.MockVendorClient(seed=7)
            return await c.fetch_gex()
        g = asyncio.run(run())
        assert g.put_wall_es < g.call_wall_es

    def test_taux_echec_100pct_leve_systematiquement(self):
        async def run():
            c = w.MockVendorClient(seed=1, failure_rate=1.0)
            with pytest.raises(w.VendorUnavailableError):
                await c.fetch_gex()
        asyncio.run(run())

    def test_net_drift_source_non_confirmee(self):
        # Reflète fidèlement le blocage documenté : Net Drift "QQQ only"
        async def run():
            c = w.MockVendorClient(seed=3)
            return await c.fetch_net_drift()
        d = asyncio.run(run())
        assert d.source_confirmed is False


# ---------------------------------------------------------------------------
# OptionsWorker — recalcul du basis une seule fois par jour, après l'heure cible
# ---------------------------------------------------------------------------

class TestBasisRecomputeScheduling:
    def _make_worker(self):
        vendor = w.MockVendorClient(seed=1)
        # redis_client jamais utilisé dans ces tests (pas de _poll_once appelé)
        return w.OptionsWorker(vendor, redis_client=None)  # type: ignore[arg-type]

    def test_calcule_au_premier_appel(self):
        worker = self._make_worker()
        now = datetime(2026, 3, 10, 9, 20, tzinfo=NY_TZ)
        worker._maybe_recompute_basis(now)
        assert worker._last_basis is not None

    def test_ne_recalcule_pas_deux_fois_le_meme_jour(self):
        worker = self._make_worker()
        t1 = datetime(2026, 3, 10, 9, 20, tzinfo=NY_TZ)
        worker._maybe_recompute_basis(t1)
        first = worker._last_basis
        t2 = datetime(2026, 3, 10, 10, 45, tzinfo=NY_TZ)
        worker._maybe_recompute_basis(t2)
        assert worker._last_basis is first  # même objet, pas recalculé

    def test_ne_calcule_pas_avant_09h15(self):
        worker = self._make_worker()
        t = datetime(2026, 3, 10, 9, 0, tzinfo=NY_TZ)
        worker._maybe_recompute_basis(t)
        assert worker._last_basis is None

    def test_recalcule_le_jour_suivant(self):
        worker = self._make_worker()
        t1 = datetime(2026, 3, 10, 9, 20, tzinfo=NY_TZ)
        worker._maybe_recompute_basis(t1)
        first = worker._last_basis
        t2 = datetime(2026, 3, 11, 9, 20, tzinfo=NY_TZ)
        worker._maybe_recompute_basis(t2)
        assert worker._last_basis is not first
