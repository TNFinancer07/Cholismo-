# OPERATING_MANUAL — procédures d'exploitation

> Pour l'opérateur, en séance. Court par construction : un manuel qu'on lit à 09h35 avec le
> marché ouvert doit tenir en quelques lignes par situation.
>
> **Règle qui prime sur tout ce document** : le terminal ne passe aucun ordre (`CLAUDE.md` §2.1).
> Aucune panne de ce manuel ne peut donc provoquer un trade. La question n'est jamais « suis-je
> exposé ? » mais « est-ce que je vois juste ? ». En cas de doute : **fermer NinjaTrader à la
> main**, le terminal n'a rien à voir là-dedans.

---

## Le réflexe : lire le verdict avant d'agir

```bash
curl -s localhost:8000/loops/health | python3 -m json.tool | grep -A 6 '"degraded"'
```

| Verdict | Ce que ça veut dire | Action |
|---|---|---|
| `NOMINAL` | tout tourne | aucune |
| `PARTIAL` | des boucles sont déclarées mais pas câblées | **aucune** — c'est documenté, pas une panne |
| `DEGRADED` | une boucle câblée stagne ou est morte | voir §2 |
| `HOT_PATH_DOWN` | le chemin chaud lui-même ne tourne plus | **§1 en premier** |

Le distinguo compte : `PARTIAL` est l'état normal du système aujourd'hui (`core.tick` est assurée
par `engine.py`, pas encore migrée sous le contrat). Le confondre avec `DEGRADED` ferait courir
pour rien à chaque démarrage.

---

## 1. Redémarrage — une ligne

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000
```

Le journal (`EVENT_DB_PATH`) est **append-only** : un redémarrage ne perd aucune décision, aucun
setup, aucune issue. L'état intra-session (Redis) se reconstruit tout seul.

Le worker options est **autonome** — il ne redémarre pas avec le terminal, et c'est voulu
(D-075) :

```bash
cd backend && PYTHONPATH=workers .venv/bin/python workers/options_worker.py
```

Sans lui, `options.sync` passe `STALLED` après ~90 s et le contexte devient `STALE`. **C'est le
comportement attendu, pas une panne à réparer dans l'urgence** : les gates O1-O4 sont
consultatifs, ils annotent, ils ne bloquent rien.

## 2. Une boucle est `DEGRADED`

Lire d'abord **pourquoi**, avant de redémarrer quoi que ce soit :

```bash
curl -s localhost:8000/loops/health | python3 -c "
import sys, json
for e in json.load(sys.stdin)['loops']:
    if e['status'] != 'RUNNING':
        print(e['name'], e['status'], '| échecs:', e['failures'], '| dernier:', e['last_error'])"
```

- **`options.sync`** → le worker est tombé, ou Redis. Le terminal continue ; O1-O4 passent
  `O*_DATA_UNAVAILABLE`. Redémarrer le worker suffit.
- **`o5.kurtosis`** → le tape n'est plus `FRESH`. Hors séance, c'est normal.
- **`ui.broadcast`** → l'écran ne se met plus à jour, mais le moteur tourne. **Ne rien décider
  sur un écran figé** : recharger la page, puis vérifier `/loops/health` en ligne de commande.

**Une boucle morte ne tue jamais les autres** — chaque tick est isolé (D-073). Un redémarrage
complet est presque toujours excessif.

## 3. Flush des verrous

Les verrous vivent dans **Redis** (état intra-session), jamais dans le journal. Les vider ne
réécrit donc aucune décision.

```bash
redis-cli --scan --pattern 'cholismo:*' | xargs -r redis-cli del   # TOUT l'état de session
redis-cli del cholismo:decision_cooldown                            # le seul cooldown C3
redis-cli del cholismo:selfcheck:SONY                               # forcer un nouveau self-check
```

⚠ Vider `cholismo:streak_ack:*` **efface un audit de série déjà fait** — l'audit sera réclamé à
nouveau. C'est une gêne, pas un danger. Ne jamais toucher à `EVENT_DB_PATH` : le journal est
immuable **par triggers SQLite**, une tentative d'`UPDATE`/`DELETE` échouera de toute façon.

## 4. Bascule manuelle en mode consultatif

Il n'y a **rien à basculer** : O1-O5 sont déjà consultatifs, et par construction
(`COMMANDS.md` §2). Aucun évaluateur ne retourne de booléen, aucun ne lève, l'entrée de journal
n'a ni `blocked` ni `allowed`. Il n'existe **aucun chemin de blocage à désactiver**.

Ce qui bloque, ce sont les 30 contrôles déterministes du moteur LSR et Phase 0 — et **ceux-là ne
se désactivent pas**. C'est le point de tout le système : la discipline est dans l'infra, pas
dans la volonté (`CLAUDE.md` §6).

Pour couper le Pont Options entièrement (par exemple si un fournisseur émet n'importe quoi) :
arrêter le worker. Le contexte devient `UNAVAILABLE`, les gates annotent `DATA_UNAVAILABLE`, et
**rien d'autre ne change**.

## 5. Passer en mode dégradé volontaire

Pour une séance où l'on veut le terminal sans les sources externes :

```bash
EXTERNAL_DATA=0 .venv/bin/uvicorn app.main:app --port 8000
```

Le mock reprend `vix` et `macro_releases`. **À n'utiliser qu'en démonstration** : un VIX de mock
sur une séance réelle est un chiffre inventé qui a l'air d'une mesure, exactement ce que §3
interdit.

---

## Ce qui ne doit JAMAIS être fait

- **Modifier `EVENT_DB_PATH` à la main.** Le journal est la seule trace de la calibration. Les
  triggers refuseront, mais l'intention est déjà le problème.
- **Redémarrer pour « débloquer » Phase 0.** Si Phase 0 bloque, c'est qu'une donnée manque ou
  qu'un verrou est actif. Redémarrer ne fabrique pas la donnée — ça remet juste le compteur à
  zéro sur un système qui avait raison.
- **Interpréter un écran figé comme un marché calme.** C'est la panne que tout le back-end
  s'emploie à rendre visible : vérifier `/loops/health`, pas l'écran.
- **Ajouter des identifiants de courtier à la configuration.** Voir `.env.production.example` —
  le terminal n'exécute pas, et lui en donner les moyens est une décision d'architecture (ADR),
  pas un réglage.

## Diagnostic en une commande

```bash
curl -s localhost:8000/health && \
curl -s localhost:8000/loops/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('verdict :', d['degraded']['verdict'])
print('cassées :', d['degraded']['broken'] or '—')
print('attendues (non câblées) :', d['degraded']['expected'] or '—')"
```
