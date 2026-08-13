/* live.js — raccordement de la maquette v17 au backend réel (P4, D-088).
 *
 * `COMMANDS.md` §4 : « Conserver l'IHM » signifie conserver le DESIGN tout en REMPLAÇANT les
 * générateurs `Math.random()` par des flux réels. Ce fichier ne touche à aucun style, aucun
 * layout, aucune structure DOM : il n'écrit que dans des éléments existants.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * TROIS RÈGLES, héritées du backend et non négociables côté écran :
 *
 * 1. **Aucune valeur inventée (§3).** Sans backend joignable, les champs affichent « — », pas
 *    une dernière valeur figée ni un zéro. Un chiffre à l'écran doit toujours venir d'une mesure.
 * 2. **La péremption se VOIT.** Le backend distingue OK / STALE / VENDOR_DOWN / UNAVAILABLE ;
 *    l'écran doit refléter cette distinction, sinon il transforme une donnée morte en donnée
 *    fraîche — le mensonge que tout le back-end s'emploie à empêcher.
 * 3. **Le rendu est cadencé, pas événementiel.** Les événements SSE arrivent quand ils veulent ;
 *    on marque « sale » et on redessine à 250 ms (RUNTIME_LOOPS Loop B, dirty flag). Redessiner
 *    à chaque message ferait battre le DOM au rythme du réseau.
 *
 * ⚠ Ce fichier N'A PAS été exécuté dans un navigateur : `vitest` et un `tsc` épinglé sont
 * absents de l'environnement de développement (npm hors ligne). Il est écrit avec soin mais
 * reste NON VÉRIFIÉ — à ouvrir et à corriger au premier lancement réel.
 */
(function () {
  'use strict';

  var API = (window.CHOLISMO_API || 'http://localhost:8000');
  var RENDER_MS = 250;          // cadence UI validée en D-074 (le worker publie toutes les 5 s)
  var ABSENT = '—';             // marque unique de l'absence — jamais un 0, jamais un vide

  // État local : dernier message reçu par type. Aucune fusion, aucune extrapolation.
  var state = { options: null, o5: null, loops: null, gates: [], px: null, connected: {} };

  /* Magasin partagé lu par la maquette (D-089). Elle ne connaît pas SSE : elle lit un objet.
   * `null` signifie « pas de donnée », JAMAIS « donnée vide » — c'est cette distinction qui
   * permet à `buildDom` d'afficher des tirets au lieu de tailles inventées. */
  window.CHOLISMO_LIVE = { book: null, tape: null, heatmap: null, ts: null };
  var dirty = true;

  function $(sel) { return document.querySelector(sel); }
  function setText(sel, value) {
    var el = $(sel);
    if (el) el.textContent = (value === null || value === undefined) ? ABSENT : value;
  }
  function num(value, digits) {
    return (typeof value === 'number' && isFinite(value)) ? value.toFixed(digits) : null;
  }

  /* ── Santé : la traduction backend → écran ─────────────────────────────────
   * `OK` est le SEUL état sain. `NOT_IMPLEMENTED` est délibérément « non sain » côté backend
   * (D-073) : une capacité annoncée et absente n'est pas un état neutre. On conserve ce choix
   * plutôt que de le repeindre en vert à l'écran. */
  function healthClass(status) {
    if (status === 'OK' || status === 'RUNNING') return 'ok';
    if (status === 'STALE' || status === 'STALLED') return 'warn';
    return 'bad';                                   // DEAD, VENDOR_DOWN, UNAVAILABLE, NOT_IMPLEMENTED
  }

  /* ── Rendu (appelé à cadence fixe, jamais depuis un handler SSE) ─────────── */
  function render() {
    if (!dirty) return;
    dirty = false;

    // Prix — canal `fast`. Absent = « — », jamais la dernière valeur figée.
    setText('#px', state.px === null ? null : state.px.toFixed(2));

    // Contexte options → Gamma / murs. La SANTÉ prime : un contexte STALE n'affiche pas ses
    // niveaux comme s'ils étaient frais.
    var opt = state.options;
    var optOk = opt && opt.health === 'OK';
    setText('#g4', optOk ? num(opt.gamma_zero_es, 2) : null);
    setText('#w1', optOk ? num(opt.put_wall_es, 2) : null);
    setText('#w2', optOk ? num(opt.call_wall_es, 2) : null);
    setText('#w3', opt ? opt.health : null);
    setText('#w4', opt && typeof opt.age_s === 'number' ? Math.round(opt.age_s) + ' s' : null);
    var w3 = $('#w3');
    if (w3) w3.className = 'badge ' + healthClass(opt ? opt.health : null);

    // O5 — kurtosis. `null` sous l'échantillon minimal : le backend refuse de le calculer, et
    // l'écran doit refuser de l'afficher plutôt que de montrer un 0 rassurant.
    var o5 = state.o5;
    setText('#s1', o5 ? o5.status : null);
    setText('#s2', o5 ? num(o5.excess_kurtosis, 3) : null);
    setText('#s3', o5 ? (o5.sample_size + ' éch.') : null);
    var s1 = $('#s1');
    if (s1) s1.className = 'badge ' + (o5 && o5.status === 'PASS' ? 'ok'
      : o5 && o5.status === 'FLAG_HIDDEN_TAIL' ? 'bad' : 'warn');

    renderLoops();
    renderGates();
  }

  /* ── Boucles L1-L5 ─────────────────────────────────────────────────────────
   * Sans superviseur joignable, on n'affiche RIEN plutôt qu'un vert par défaut : « je ne sais
   * pas » et « tout va bien » ne sont pas la même chose (doctrine D-073). */
  function renderLoops() {
    var host = $('#p6') || $('#con');
    if (!host || !state.loops || !state.loops.loops) return;
    host.innerHTML = state.loops.loops.map(function (loop) {
      return '<span class="badge ' + healthClass(loop.status) + '" title="'
        + (loop.purpose || '').replace(/"/g, '') + '">' + loop.name + ' · ' + loop.status
        + '</span>';
    }).join(' ');
  }

  /* ── Blotter + balises O1-O5 ───────────────────────────────────────────────
   * Une entrée sans issue reste `PENDING` : elle n'est jamais affichée comme un résultat nul
   * (D-082). */
  function renderGates() {
    var table = $('#jTable');
    if (!table || !state.gates.length) return;
    table.innerHTML = state.gates.slice(0, 50).map(function (row) {
      return '<tr><td>' + (row.setup_id || ABSENT) + '</td>'
        + '<td>' + (row.side || ABSENT) + '</td>'
        + ['o1', 'o2', 'o3', 'o4', 'o5'].map(function (g) {
          var st = row[g + '_status'] || ABSENT;
          return '<td class="' + (st === 'PASS' ? 'ok' : st.indexOf('FLAG') === 0 ? 'bad' : 'warn')
            + '">' + st + '</td>';
        }).join('')
        + '<td>' + (row.outcome_status || 'PENDING') + '</td></tr>';
    }).join('');
  }

  /* ── SSE : deux canaux, résurrection automatique ───────────────────────────
   * Le canal `options` porte le Pont Options + la santé des boucles ; `fast` porte le prix.
   * Une coupure ne fige pas l'écran : `connected` bascule et le rendu affiche « — ». */
  function subscribe(channel, handlers) {
    var source;
    function open() {
      try {
        source = new EventSource(API + '/sse/' + channel);
      } catch (err) {
        state.connected[channel] = false;
        return;
      }
      source.onopen = function () { state.connected[channel] = true; dirty = true; };
      source.onerror = function () {
        state.connected[channel] = false;
        dirty = true;
        try { source.close(); } catch (e) { /* déjà fermée */ }
        // Reconnexion différée : marteler un backend qui redémarre ne le fait pas revenir plus
        // vite (RUNTIME_LOOPS Loop E).
        setTimeout(open, 2000);
      };
      Object.keys(handlers).forEach(function (event) {
        source.addEventListener(event, function (message) {
          try {
            handlers[event](JSON.parse(message.data));
          } catch (err) {
            // Message malformé : ignoré SEUL. L'écran garde son état ; il ne se vide pas sur
            // une trame corrompue, et ne crashe pas non plus.
            return;
          }
          dirty = true;
        });
      });
    }
    open();
  }

  function boot() {
    subscribe('options', {
      options_context: function (data) { state.options = data; },
      o5_tail_risk: function (data) { state.o5 = data; },
      loops_health: function (data) { state.loops = data; },
      options_gates: function (data) { state.gates.unshift(data); state.gates.length = Math.min(state.gates.length, 200); }
    });
    subscribe('fast', {
      s1_state: function (data) {
        // Le prix vient du tape (D-026, plus récent en tête). Absent → on n'invente pas.
        var tape = data && data.tape;
        var prints = tape && tape.freshness === 'FRESH' ? tape.value : null;
        state.px = (prints && prints.length) ? prints[0].price : null;

        // Carnet, tape et heatmap alimentent la maquette (D-089). Seul le FRESH passe : un
        // carnet périmé affiché comme courant annoncerait une liquidité qui n'est plus là.
        var book = data && data.order_book;
        window.CHOLISMO_LIVE.book =
          (book && book.freshness === 'FRESH' && book.value) ? book.value : null;
        window.CHOLISMO_LIVE.tape = prints;
        var heat = data && data.liquidity_heatmap;
        window.CHOLISMO_LIVE.heatmap =
          (heat && heat.freshness === 'FRESH' && heat.value) ? heat.value : null;
        window.CHOLISMO_LIVE.ts = Date.now();
      }
    });

    // Instantanés au démarrage : le canal ne pousse la santé que sur CHANGEMENT (D-075), et le
    // blotter n'est pas poussé du tout. Sans ces deux appels, l'écran resterait vide jusqu'au
    // prochain événement — potentiellement plusieurs minutes sur un système sain.
    fetch(API + '/loops/health').then(function (r) { return r.json(); })
      .then(function (d) { state.loops = d; dirty = true; })
      .catch(function () { /* superviseur absent : les badges restent vides, pas verts */ });
    fetch(API + '/setups?limit=50').then(function (r) { return r.json(); })
      .then(function (d) { state.gates = d.setups || []; dirty = true; })
      .catch(function () { /* journal illisible : le blotter reste vide, jamais inventé */ });

    setInterval(render, RENDER_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
