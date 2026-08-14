"""Exporteur Notion — service AUTONOME (D-118).

Tourne HORS du terminal, comme `options_worker.py`. Le moteur ne le connaît pas, ne l'attend pas,
et ne ralentit jamais à cause de lui : `CLAUDE §7` interdit tout appel réseau synchrone dans le
chemin de décision, et un export de journal n'a aucune raison d'y entrer.

    NOTION_API_KEY=... NOTION_DATABASE_ID=... python workers/notion_exporter.py

---

**Opt-in strict.** Sans les DEUX variables, le worker le dit et s'arrête. Il n'envoie jamais rien
par défaut : les données de trading ne partent vers un service tiers que sur demande explicite.

**Fail-safe.** Coupure réseau, clé invalide, base mal configurée : journalisé en local, aucune
exception qui remonte, aucune donnée perdue — le journal des setups reste la source de vérité et
la ligne repartira à la passe suivante.

**Anti-doublon persistant.** Les identifiants déjà envoyés sont conservés sur disque. Sans cela,
chaque redémarrage recréerait toutes les lignes de la base.

⚠️ **Le format d'API n'a été confronté à AUCUN service réel** — pas de clé ici. Ce qui est
garanti, c'est le mappage (testé) et le comportement en panne, pas la conformité à l'API Notion.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.notion_export import already_exported, is_configured, to_notion_properties  # noqa: E402
from app.setup_journal import SetupJournal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("cholismo.notion")

NOTION_API = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"
POLL_SECONDS = float(os.getenv("NOTION_POLL_SECONDS", "60"))
STATE_PATH = pathlib.Path(os.getenv("NOTION_STATE_PATH", "data/notion_exported.json"))


def charger_exportes() -> set[str]:
    """Identifiants déjà envoyés. Un fichier illisible rend un ensemble VIDE : on préfère un
    doublon visible dans Notion à un trou silencieux dans l'historique."""
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except Exception:
        return set()


def enregistrer_exportes(ids: set[str]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(sorted(ids)), encoding="utf-8")
    except Exception:
        # Perdre l'état produira des doublons à la prochaine passe — gênant, jamais destructeur.
        log.exception("état d'export non persisté — doublons possibles au redémarrage")


async def envoyer(client, properties: dict, database_id: str, api_key: str) -> bool:
    """Rend `True` si Notion a accepté la ligne. Toute panne est journalisée et rendue `False` :
    la ligne repartira, le journal local restant la source de vérité."""
    try:
        res = await client.post(
            NOTION_API,
            headers={"Authorization": f"Bearer {api_key}",
                     "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"},
            json={"parent": {"database_id": database_id}, "properties": properties},
            timeout=10.0)
        if res.status_code >= 400:
            # Le corps porte le motif exact (colonne absente, type incompatible) : le taire
            # obligerait à deviner ce que Notion reproche.
            log.error("Notion a refusé la ligne (%s) : %s", res.status_code, res.text[:400])
            return False
        return True
    except Exception as exc:
        log.warning("export Notion indisponible (%s) — la ligne repartira", type(exc).__name__)
        return False


async def passe(client, api_key: str, database_id: str) -> int:
    """Une passe : journal → lignes neuves → Notion. Rend le nombre de lignes envoyées."""
    exportes = charger_exportes()
    envoyees = 0
    try:
        entrees = SetupJournal().projection()
    except Exception:
        log.exception("journal des setups illisible — passe abandonnée, rien n'est perdu")
        return 0

    for entree in entrees:
        setup_id = entree.get("setup_id") if isinstance(entree, dict) else None
        if already_exported(setup_id, exportes):
            continue
        props = to_notion_properties(entree)
        if props is None:
            continue
        if await envoyer(client, props, database_id, api_key):
            exportes.add(str(setup_id))
            envoyees += 1
    if envoyees:
        enregistrer_exportes(exportes)
    return envoyees


async def main() -> int:
    api_key = os.getenv("NOTION_API_KEY", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "")
    if not is_configured(api_key, database_id):
        log.info("export Notion NON configuré (NOTION_API_KEY + NOTION_DATABASE_ID) — "
                 "rien ne sera envoyé. C'est le comportement par défaut, pas une panne.")
        return 0

    import httpx
    log.info("export Notion actif — base %s…, cadence %.0f s", database_id[:8], POLL_SECONDS)
    async with httpx.AsyncClient() as client:
        while True:
            n = await passe(client, api_key, database_id)
            if n:
                log.info("%d setup(s) exporté(s)", n)
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
