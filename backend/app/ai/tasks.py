"""AI wiring (Étape 10) — ALL async, NEVER in the live hot path (CLAUDE §2.8/§7).

- Groq (LLaMA 3.3 70B): Phase 0 ADVISORY. Budget < 100 ms, fail-closed: timeout, error or
  missing key -> advisory = UNAVAILABLE and Phase 0 is UNCHANGED (the lock is the
  deterministic rules engine, never this).
- Claude (scoring): periodic, out of hot path; cost/latency bounded and logged to ai_calls.
- Gemini (audit): every 20 reconciled trades, async; logged.

Without API keys every provider degrades to an explicit SKIPPED/UNAVAILABLE status —
nothing is silently faked (D-014).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

import httpx

from .. import config, projections, settings
from ..event_store import get_store

log = logging.getLogger("cholismo.ai")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GROQ_PERIOD_SECONDS = 30.0


class AITasks:
    """Owns the three background loops; engine reads advisory text via a callback."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self._tasks: list[asyncio.Task] = []
        self._last_audit_marker = 0

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._groq_loop()),
            asyncio.create_task(self._claude_loop()),
            asyncio.create_task(self._gemini_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # -- Groq advisory (Phase 0) --

    async def _groq_loop(self) -> None:
        store = get_store()
        if not config.GROQ_API_KEY:
            self.engine.schema.session_identity.phase0_advisory = "UNAVAILABLE"
            store.log_ai_call("groq", "phase0_advisory", "SKIPPED_NO_KEY")
            return
        while True:
            started = time.time()
            try:
                blockers = [b.rule for b in self.engine.schema.session_identity.phase0_blockers]
                async with httpx.AsyncClient(timeout=config.GROQ_TIMEOUT_SECONDS) as client:
                    res = await client.post(GROQ_URL,
                        headers={"authorization": f"Bearer {config.GROQ_API_KEY}"},
                        json={"model": "llama-3.3-70b-versatile", "max_tokens": 40,
                              "messages": [{"role": "user", "content":
                                  "One short French sentence, advisory only, on this Phase 0 state: "
                                  + json.dumps({"phase0": self.engine.schema.session_identity.phase0.value,
                                                "blockers": blockers})}]})
                latency = (time.time() - started) * 1000
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"][:120]
                    self.engine.schema.session_identity.phase0_advisory = f"OK: {text}"
                    store.log_ai_call("groq", "phase0_advisory", "OK", latency_ms=latency)
                else:
                    self.engine.schema.session_identity.phase0_advisory = "UNAVAILABLE"
                    store.log_ai_call("groq", "phase0_advisory", f"HTTP_{res.status_code}", latency_ms=latency)
            except Exception as exc:  # timeout > 100 ms included -> fail-closed advisory
                self.engine.schema.session_identity.phase0_advisory = "UNAVAILABLE"
                store.log_ai_call("groq", "phase0_advisory", f"FAIL_{type(exc).__name__}",
                                  latency_ms=(time.time() - started) * 1000)
            await asyncio.sleep(GROQ_PERIOD_SECONDS)

    # -- Claude scoring (periodic, out of hot path) --

    async def _claude_loop(self) -> None:
        store = get_store()
        if not config.ANTHROPIC_API_KEY:
            store.log_ai_call("claude", "scoring", "SKIPPED_NO_KEY")
            return
        while True:
            # Period from the settings projection (bounded 60-3600 server-side, D-023) —
            # re-read each cycle so a change applies without restart; never < 60 s.
            await asyncio.sleep(float(settings.value("ai.claude_scoring_period_seconds")))
            started = time.time()
            try:
                snapshot = self.engine.schema.model_dump(mode="json")
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(ANTHROPIC_URL,
                        headers={"x-api-key": config.ANTHROPIC_API_KEY,
                                 "anthropic-version": "2023-06-01"},
                        json={"model": "claude-opus-4-8", "max_tokens": 300,
                              "messages": [{"role": "user", "content":
                                  "Commente (français, bref) la cohérence de ce snapshot de "
                                  "signal — méta-scoring hors hot path, aucune décision: "
                                  + json.dumps(snapshot["unified_signal_output"])}]})
                latency = (time.time() - started) * 1000
                usage = res.json().get("usage", {}) if res.status_code == 200 else {}
                store.log_ai_call("claude", "scoring",
                                  "OK" if res.status_code == 200 else f"HTTP_{res.status_code}",
                                  latency_ms=latency,
                                  detail=json.dumps(usage))
            except Exception as exc:
                store.log_ai_call("claude", "scoring", f"FAIL_{type(exc).__name__}",
                                  latency_ms=(time.time() - started) * 1000)

    # -- Gemini audit (every 20 reconciled trades, async) --

    async def _gemini_loop(self) -> None:
        store = get_store()
        while True:
            await asyncio.sleep(60.0)
            n = projections.sharpe(store)["n"]
            marker = n // config.GEMINI_AUDIT_EVERY_N_TRADES
            if marker > self._last_audit_marker:
                self._last_audit_marker = marker
                if not config.GEMINI_API_KEY:
                    store.log_ai_call("gemini", "audit_20_trades", "SKIPPED_NO_KEY",
                                      detail=f"n_trades={n}")
                    continue
                store.log_ai_call("gemini", "audit_20_trades", "QUEUED", detail=f"n_trades={n}")
                # Real call intentionally deferred: audit content depends on /reference/
                # AUTORITÉ blocks that do not exist yet (MANIFEST.md).
