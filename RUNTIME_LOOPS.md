# RUNTIME_LOOPS.md — Boucles d'exécution du terminal **cholismo**

> Les boucles réelles qui tournent *dans* le code du terminal.
> Complément de `CLAUDE.md` (qui décrit, lui, comment développer).
> Pseudocode **neutre**. Notes Python (`asyncio`) et Node ajoutées où le choix de stack change quelque chose.

---

## Note sur le stack

Le stack n'est pas encore figé. Ces patterns sont valables partout ; deux différences majeures à garder en tête :

- **Python** — l'async passe par `asyncio` ; attention à ne jamais faire d'appel bloquant (I/O synchrone, `time.sleep`) dans une coroutine → utiliser `await asyncio.sleep`, `run_in_executor` pour le bloquant.
- **Node** — la boucle d'événements est native ; le piège inverse est de **bloquer l'event loop** avec du CPU synchrone lourd → découper ou déporter dans un worker.

Règle commune : **une boucle ne doit jamais tourner à vide à 100 % de CPU** (busy-wait). On attend toujours quelque chose (événement, tick, I/O).

---

## Loop A — Boucle principale (REPL / event loop)

**But** — le cœur du terminal : lire une entrée, la traiter, afficher, recommencer, jusqu'à la sortie.

**Pattern** — boucle unique, condition d'arrêt explicite, nettoyage garanti en sortie.

```
init_terminal()
running = true
try:
    while running:
        input = read_input()            # bloquant OU await selon stack
        if input is EOF or input == "quit":
            running = false
            continue
        command = parse(input)
        result = dispatch(command)       # exécute la commande
        render(result)
finally:
    cleanup_terminal()                   # TOUJOURS exécuté (voir Loop H)
```

**Pièges à éviter**
- Oublier le `finally` → terminal laissé dans un état cassé si crash.
- Mettre la logique métier directement dans la boucle → la garder mince, déléguer à `dispatch`.
- Ignorer l'EOF (Ctrl-D) → boucle infinie si l'entrée se ferme.

---

## Loop B — Boucle de rendu / refresh *(si TUI)*

**But** — redessiner l'écran, mais **seulement quand c'est nécessaire**.

**Pattern** — *dirty flag* + cadence plafonnée. On ne redessine pas si rien n'a changé.

```
dirty = true
target_fps = 30
frame_budget = 1000ms / target_fps

loop:
    wait_for_event(timeout = frame_budget)   # réveil sur event OU timeout
    if state_changed():
        dirty = true
    if dirty:
        draw(current_state)
        dirty = false
```

**Pièges à éviter**
- Redessiner en continu même sans changement → CPU gaspillé, ventilo qui tourne.
- Redraw complet à chaque frame alors qu'une seule zone a changé → viser le rendu partiel si le framework le permet.
- Redimensionnement du terminal non géré → écouter l'événement resize et forcer `dirty = true`.

---

## Loop C — Boucle d'input non-bloquante

**But** — lire les frappes clavier sans figer le rendu ni les tâches de fond.

**Pattern** — lecture non-bloquante ou déportée dans sa propre tâche async qui pousse dans une file.

```
loop:
    key = read_key(non_blocking = true)      # retourne null si rien
    if key is not null:
        enqueue(input_queue, key)
    else:
        yield / await small_sleep             # rendre la main, PAS de busy-wait
```

- **Python** : tâche `asyncio` qui `await`s l'entrée ; ou `run_in_executor` pour l'I/O terminal bloquant.
- **Node** : `process.stdin` en mode `raw` + listener `'data'` ; pas besoin de polling manuel.

**Pièges à éviter**
- `while true: read_key()` sans pause → 100 % CPU.
- Traiter la touche directement dans le lecteur → séparer *lire* (producteur) et *traiter* (consommateur) via une file.
- Ne pas repasser le terminal en mode normal à la sortie (voir Loop H).

---

## Loop D — Boucle de données en arrière-plan (worker async)

**But** — rafraîchir des données externes (ex. flux temps réel, API) sans bloquer l'UI.

**Pattern** — tâche indépendante, cadence contrôlée, écrit dans un état partagé lu par le rendu.

```
loop while running:
    try:
        data = await fetch()
        update_shared_state(data)
        signal_dirty()                       # prévient Loop B qu'il faut redessiner
    except transient_error:
        apply_backoff()                      # voir Loop E
    await sleep(refresh_interval)
```

**Pièges à éviter**
- **Race condition** sur l'état partagé → protéger l'écriture (lock, ou passage par une file d'événements).
- Pas de *backpressure* : si `fetch()` est plus lent que l'intervalle, les tâches s'empilent → sauter le tick si le précédent n'est pas fini.
- Fuite mémoire : un buffer de données qui grossit sans borne → borner/évincer les anciennes valeurs.
- Une exception non capturée qui tue silencieusement le worker → logger et repartir.

### Instances réelles de Loop D dans le code

| Boucle | Fichier | Cadence | Parades notables |
|---|---|---|---|
| Cadence rapide / lente du schéma | `backend/app/engine.py` | 0,25 s / 15 s | exception par tick capturée (« le schéma continue de vieillir ») |
| Poll compte NT8 | `backend/app/account_provider.py` | 1 s | I/O bloquant déporté (`asyncio.to_thread`), lecture fenêtrée O(72 Ko) |
| Poll calendrier macro | `backend/app/macro_news.py` | 1 h | cache conservé si le flux est obèse ou empoisonné |
| Évaluation LSR push-driven | `backend/app/lsr_driver.py` | 0,25 s | voir ci-dessous |

**`lsr_driver.py` cumule les quatre pièges de Loop D et les traite explicitement** (D-052, passes
`/devil` + `/polish`) — c'est le gabarit à reprendre pour toute nouvelle boucle de données :

- **Race** — un verrou unique sérialise le cycle d'état ; un `await` de persistance au milieu d'un
  read-modify-write faisait perdre un cooldown (donc autorisait un trade de revanche).
- **Backpressure** — une évaluation concurrente est **droppée**, pas empilée (deux émettraient deux
  fois le même ticket) ; l'issue de trade, elle, attend son tour.
- **Exception avalée** — filet de dernier recours autour du tick, plus un **plafond de durée** sur
  chaque callback : un `await` qui ne rend jamais la main pendait la boucle en silence, et *un
  driver mort ressemble à un driver calme*.
- **Cadence** — visée à l'**échéance** (`loop.time()` monotone), sans rattrapage : « travail puis
  sieste fixe » donne une période réelle de `poll + travail`, et une rafale de rattrapage
  évaluerait le passé.
- **Fraîcheur** — snapshot périmé ou daté du **futur** → aucune évaluation (fail-closed §3) ; une
  horloge qui recule est signalée une fois par épisode, pas à chaque tick.

---

## Loop E — Retry avec backoff exponentiel

**But** — réessayer une opération faillible (réseau, I/O) sans marteler la ressource.

**Pattern** — délai croissant + plafond + *jitter* + nombre max de tentatives.

```
attempt = 0
max_attempts = 5
base = 200ms
cap = 10s

loop:
    try:
        return do_operation()
    except retryable_error:
        attempt += 1
        if attempt >= max_attempts:
            raise / signal_failure()
        delay = min(cap, base * 2^attempt)
        delay += random(0, delay * 0.2)      # jitter anti-thundering-herd
        await sleep(delay)
```

**Pièges à éviter**
- Retry sur une erreur **non** transitoire (ex. entrée invalide) → boucle qui ne réussira jamais. Ne réessayer que le transitoire.
- Pas de plafond → délais qui explosent.
- Pas de jitter → toutes les tentatives synchronisées frappent en même temps.

---

## Loop F — Debounce / throttle

**But** — limiter la fréquence d'une action déclenchée par des événements rapides (frappe, resize, scroll).

**Pattern**
- **Debounce** : n'exécuter qu'après un silence de N ms (idéal pour « recherche pendant la frappe »).
- **Throttle** : au plus une exécution toutes les N ms (idéal pour le resize/scroll).

```
# Debounce
on_event:
    cancel(pending_timer)
    pending_timer = schedule(after = N ms) -> run_action()

# Throttle
on_event:
    if now - last_run >= N ms:
        run_action()
        last_run = now
```

**Pièges à éviter**
- Confondre les deux : debounce pour « attendre la fin », throttle pour « lisser en continu ».
- Timer non annulé → l'action se déclenche alors qu'elle n'est plus pertinente.

---

## Loop G — Watchdog / heartbeat

**But** — surveiller qu'une boucle critique (ex. worker de données) est toujours vivante.

**Pattern** — la boucle surveillée met à jour un timestamp ; un watchdog vérifie qu'il reste frais.

```
# côté boucle surveillée
loop:
    do_work()
    last_heartbeat = now

# côté watchdog
loop:
    await sleep(check_interval)
    if now - last_heartbeat > threshold:
        log_warning("worker figé")
        restart_worker()  # ou signaler à l'UI
```

**Pièges à éviter**
- Watchdog trop agressif qui redémarre alors que le travail est juste long → seuil > durée max normale.
- Boucle de redémarrage infinie si la cause persiste → limiter le nombre de redémarrages, puis abandonner proprement.

---

## Loop H — Arrêt gracieux (graceful shutdown)

**But** — quitter proprement : restaurer le terminal, fermer les tâches et ressources, ne rien laisser en suspens.

**Pattern** — capter les signaux, basculer un drapeau, laisser les boucles finir, nettoyer une seule fois.

```
on_signal(SIGINT, SIGTERM):
    running = false          # les boucles voient le drapeau et sortent

shutdown():                  # idempotent : ne s'exécute qu'une fois
    cancel_background_tasks()
    await tasks_finished(timeout)
    flush_logs()
    restore_terminal()       # curseur visible, couleurs reset, mode normal
```

**Pièges à éviter**
- Tuer brutalement au premier Ctrl-C → laisser une chance de finir, forcer seulement au second.
- `restore_terminal()` oublié → invite de commande cassée après la sortie.
- Shutdown appelé deux fois → le rendre idempotent (drapeau `already_shutting_down`).

---

## Récapitulatif : pièges communs à TOUTES les boucles

| Piège | Symptôme | Parade |
|---|---|---|
| Busy-wait | CPU à 100 %, ventilo | Toujours `await`/attendre un event ou un tick |
| Blocage de la boucle | UI figée | Déporter le lourd (executor / worker) |
| Race condition | Valeurs incohérentes | Lock ou file d'événements sur l'état partagé |
| Pas de backpressure | Tâches empilées, mémoire qui monte | Sauter/annuler le tick si le précédent n'est pas fini |
| Exception avalée | Boucle morte en silence | Logger + repartir, jamais de `catch` vide |
| Pas de sortie propre | Terminal cassé après quit | Nettoyage dans `finally` (Loop H) |
| Retry aveugle | Boucle infinie sur erreur permanente | Ne réessayer que le transitoire + plafond |

---

## Ordre d'implémentation suggéré (par jalon)

1. **Loop A** (boucle principale) — démarre + s'arrête proprement.
2. **Loop H** (arrêt gracieux) — dès qu'il y a une ressource à libérer.
3. **Loop C** (input) puis **Loop B** (rendu) si TUI.
4. **Loop D** (données) + **Loop E** (retry) quand une source externe entre en jeu.
5. **Loop F / G** (debounce/throttle, watchdog) en polish, quand le besoin réel apparaît.

> On n'ajoute une boucle que lorsqu'un besoin concret la justifie (principe « simple » de `CLAUDE.md`).
