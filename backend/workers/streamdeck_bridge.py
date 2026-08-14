"""Pont Stream Deck — daemon WebSocket LOCAL (D-119).

    STREAMDECK_BRIDGE=1 python workers/streamdeck_bridge.py

Service autonome, comme les autres workers : le terminal ne le connaît pas et ne ralentit jamais
à cause de lui. Il lit l'état par HTTP (lecture seule), projette des tuiles, et n'accepte que les
actions de la liste blanche de `app/streamdeck.py`.

---

**Local seulement.** Le serveur écoute sur `127.0.0.1`. Un boîtier physique est branché sur le
poste ; exposer ce pont au réseau donnerait à un tiers les commandes d'un terminal de trading —
même bornées à des actions réversibles, ce n'est pas une porte qu'on ouvre par confort.

**Opt-in.** Sans `STREAMDECK_BRIDGE=1`, le daemon le dit et s'arrête.

⚠️ **Aucun matériel Stream Deck n'a été branché ici.** Le protocole du boîtier (plugin Elgato,
format des tuiles) n'est pas vérifié. Ce qui est garanti : la projection, la liste blanche et le
refus des actions de décision — tous testés.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.streamdeck import build_keys, validate_action  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("cholismo.streamdeck")

HOST = "127.0.0.1"                       # jamais 0.0.0.0 — voir docstring
PORT = int(os.getenv("STREAMDECK_PORT", "8777"))
API = os.getenv("VITE_API_BASE", "http://localhost:8000")
POLL_SECONDS = float(os.getenv("STREAMDECK_POLL_SECONDS", "1.0"))


async def lire_etat(client) -> dict:
    """État courant, agrégé depuis les endpoints de LECTURE. Toute panne rend un état vide —
    et les tuiles passeront `UNKNOWN`, ce qui est la vérité."""
    etat: dict = {}
    for chemin, cle in (("/state", None), ("/protection", "protection")):
        try:
            res = await client.get(f"{API}{chemin}", timeout=3.0)
            if res.status_code < 400:
                corps = res.json()
                if cle is None:
                    etat.update(corps if isinstance(corps, dict) else {})
                else:
                    etat[cle] = corps
        except Exception:
            # Silence volontaire : un terminal arrêté n'est pas une panne du pont, et le dire à
            # chaque seconde noierait les vrais incidents.
            pass
    return etat


async def servir(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Un client (le plugin du boîtier). Protocole volontairement trivial : une ligne JSON par
    message, dans les deux sens — un pont local n'a pas besoin d'une pile WebSocket complète, et
    chaque dépendance en plus est une surface en plus."""
    import httpx
    pair = writer.get_extra_info("peername")
    log.info("boîtier connecté : %s", pair)
    async with httpx.AsyncClient() as client:
        envoi = asyncio.create_task(_pousser(writer, client))
        try:
            while True:
                ligne = await reader.readline()
                if not ligne:
                    break
                await _traiter(ligne, writer)
        finally:
            envoi.cancel()
            writer.close()
            log.info("boîtier déconnecté : %s", pair)


async def _pousser(writer: asyncio.StreamWriter, client) -> None:
    while True:
        etat = await lire_etat(client)
        writer.write((json.dumps({"keys": build_keys(etat)}) + "\n").encode())
        try:
            await writer.drain()
        except Exception:
            return
        await asyncio.sleep(POLL_SECONDS)


async def _traiter(ligne: bytes, writer: asyncio.StreamWriter) -> None:
    """Une action reçue. Un refus est RENVOYÉ avec son motif : le boîtier doit pouvoir l'afficher,
    sinon l'opérateur appuie et ne comprend pas pourquoi rien ne se passe."""
    try:
        msg = json.loads(ligne.decode())
    except Exception:
        return
    action = msg.get("action") if isinstance(msg, dict) else None
    ok, motif = validate_action(action, msg.get("payload") if isinstance(msg, dict) else None)
    if not ok:
        log.warning("action refusée (%s) : %s", action, motif)
        writer.write((json.dumps({"refused": action, "reason": motif}) + "\n").encode())
        return
    # Les actions autorisées sont toutes des commandes d'INTERFACE : elles sont relayées à la
    # fenêtre du terminal, jamais exécutées ici. Le pont ne touche à aucun état de trading.
    writer.write((json.dumps({"accepted": action, "payload": msg.get("payload")}) + "\n").encode())


async def main() -> int:
    if os.getenv("STREAMDECK_BRIDGE", "") != "1":
        log.info("pont Stream Deck NON activé (STREAMDECK_BRIDGE=1) — c'est le défaut.")
        return 0
    serveur = await asyncio.start_server(servir, HOST, PORT)
    log.info("pont Stream Deck sur %s:%d — LOCAL uniquement, actions en liste blanche", HOST, PORT)
    async with serveur:
        await serveur.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
