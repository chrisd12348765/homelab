# REFERENCE COPY — the live version is installed in Open WebUI's webui.db (function id
# `nerd_stats`, Admin Panel -> Functions) on CT 111. Nothing deploys this file; if you edit
# it, re-install by pasting into the Functions editor or re-running the DB insert.
#
"""
title: Nerd Stats
description: Shows elapsed time, token counts and tok/s under every assistant reply.
version: 0.1.0
"""

import time
from typing import Optional

from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=10, description="Filter priority (lower runs first)"
        )
        chars_per_token: float = Field(
            default=4.0,
            description="Fallback chars-per-token ratio when the backend returns no usage data",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._starts: dict = {}

    def _key(self, metadata: Optional[dict]) -> str:
        md = metadata or {}
        return str(md.get("message_id") or md.get("chat_id") or "last")

    def inlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        now = time.perf_counter()
        self._starts[self._key(__metadata__)] = now
        self._starts["last"] = now
        # keep the stash from growing unbounded across many chats
        if len(self._starts) > 256:
            self._starts.clear()
            self._starts["last"] = now
        return body

    async def outlet(
        self,
        body: dict,
        __event_emitter__=None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        start = self._starts.pop(self._key(__metadata__), None)
        if start is None:
            start = self._starts.get("last")
        elapsed = (time.perf_counter() - start) if start else None

        messages = body.get("messages") or []
        last = messages[-1] if messages else {}
        content = last.get("content") or ""
        if isinstance(content, list):  # multimodal content parts
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )

        # real usage if the backend returned it (requires the model's
        # "Usage" capability to be enabled), otherwise estimate
        usage = last.get("usage") or {}
        info = last.get("info") or {}
        prompt_tokens = usage.get("prompt_tokens") or info.get("prompt_eval_count")
        completion_tokens = usage.get("completion_tokens") or info.get("eval_count")
        estimated = False
        if not completion_tokens:
            estimated = True
            completion_tokens = max(
                1, round(len(content) / max(self.valves.chars_per_token, 1.0))
            )

        parts = []
        if elapsed is not None:
            parts.append(f"{elapsed:.1f}s")
        if prompt_tokens:
            parts.append(f"↑ {prompt_tokens:,} tok in")
        suffix = " (est)" if estimated else ""
        parts.append(f"↓ {completion_tokens:,} tok{suffix}")
        if elapsed and elapsed > 0.05:
            parts.append(f"⚡ {completion_tokens / elapsed:.1f} tok/s{suffix}")

        if __event_emitter__ and parts:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": " • ".join(parts), "done": True},
                }
            )
        return body
