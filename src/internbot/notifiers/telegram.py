"""Notifier Telegram (Bot API, parse_mode HTML)."""

from __future__ import annotations

import html
import logging
import os
from collections.abc import Sequence
from typing import Any

from internbot.errors import ConfigError, HttpError
from internbot.http import HttpClient
from internbot.models import Job
from internbot.notifiers.base import Notifier
from internbot.notifiers.formatting import build_grouped_messages, format_job_html, split_message

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier(Notifier):
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        http: HttpClient | None = None,
        group_threshold: int = 10,
        disable_link_preview: bool = True,
    ) -> None:
        if not token or not chat_id:
            raise ConfigError("TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID sont requis")
        self._url = API_URL.format(token=token)
        self.chat_id = chat_id
        self.group_threshold = group_threshold
        self.disable_link_preview = disable_link_preview
        # Telegram : ~1 message/s par chat conseillé, 30 msg/s global. On reste à 1/s.
        self.http = http or HttpClient(min_delay_s=1.0, max_retries=3)

    @classmethod
    def from_env(
        cls, *, group_threshold: int = 10, disable_link_preview: bool = True
    ) -> TelegramNotifier:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        missing = [
            n for n, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id)) if not v
        ]
        if missing:
            raise ConfigError(
                f"Variable(s) d'environnement manquante(s) : {', '.join(missing)}. "
                "Voir README (section Telegram) ou utilisez --dry-run."
            )
        return cls(
            token,
            chat_id,
            group_threshold=group_threshold,
            disable_link_preview=disable_link_preview,
        )

    # -- API ----------------------------------------------------------------------------------

    def notify(self, jobs: Sequence[Job]) -> list[Job]:
        delivered: list[Job] = []
        if len(jobs) <= self.group_threshold:
            for job in jobs:
                if self._send(format_job_html(job)):
                    delivered.append(job)
            return delivered
        for text, members in build_grouped_messages(jobs):
            if self._send(text):
                delivered.extend(members)
        return delivered

    def send_text(self, text: str) -> bool:
        ok = True
        for chunk in split_message(html.escape(text, quote=False)):
            ok = self._send(chunk) and ok
        return ok

    # -- interne -------------------------------------------------------------------------------

    def _send(self, text: str) -> bool:
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": self.disable_link_preview},
        }
        try:
            data = self.http.post_json(self._url, payload)
        except HttpError as exc:
            log.error("Échec d'envoi Telegram : %s", exc)
            return False
        if not isinstance(data, dict) or not data.get("ok"):
            log.error("Telegram a refusé le message : %s", data)
            return False
        return True
