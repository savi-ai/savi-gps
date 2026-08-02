"""Slack connector for Savi — post / ask (T5 thin slice)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SaviConnectorBinding
from app.core.logger import logger
from app.services.connectors.base import ConnectorResult
from app.services.connectors.binding_service import SaviConnectorBindingService


class SaviSlackConnector:
    def __init__(self, db: Session, binding: SaviConnectorBinding):
        self.db = db
        self.binding = binding
        self.config = dict(binding.config_json or {})
        self._bindings = SaviConnectorBindingService(db)

    def _token(self) -> str:
        token = self._bindings.get_secret(self.binding) or self.config.get("bot_token")
        if not token:
            raise ValueError("Slack binding needs a bot token secret")
        return token

    def _channel(self) -> str:
        ch = self.config.get("channel_id") or self.config.get("channel")
        if not ch:
            raise ValueError("Slack binding needs config.channel_id")
        return ch

    async def _post_chat(
        self, text: str, thread_ts: Optional[str] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "channel": self._channel(),
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    raise ValueError(data.get("error") or "Slack API error")
                return data

    async def post_message(
        self, *, text: str, thread_ts: Optional[str] = None
    ) -> ConnectorResult:
        if not settings.SLACK_ENABLED and not self.config.get("force_live"):
            return ConnectorResult(
                ok=True,
                stubbed=True,
                data={"text": text, "thread_ts": thread_ts, "stub": True},
            )
        try:
            data = await self._post_chat(text, thread_ts)
            return ConnectorResult(
                ok=True,
                data={"ts": data.get("ts"), "channel": data.get("channel")},
            )
        except Exception as e:
            logger.warning("Slack post_message failed: %s", e)
            return ConnectorResult(ok=False, error=str(e)[:500])

    async def ask_question(
        self, *, text: str, thread_ts: Optional[str] = None
    ) -> ConnectorResult:
        prompt = f":question: *Savi needs input*\n{text}"
        return await self.post_message(text=prompt, thread_ts=thread_ts)
