"""Notifier Telegram (Bot API, parse_mode HTML)."""

from __future__ import annotations

import html
import logging
import os
import re
from collections.abc import Sequence
from typing import Any

from internbot.errors import ConfigError, HttpError
from internbot.http import HttpClient
from internbot.models import Job
from internbot.notifiers.base import Notifier
from internbot.notifiers.formatting import (
    build_grouped_messages,
    build_listing_messages,
    format_job_html,
    split_message,
)

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
GET_ME_URL = "https://api.telegram.org/bot{token}/getMe"

_TOKEN_FORMAT = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
_CHAT_ID_FORMAT = re.compile(r"^(-?\d+|@[A-Za-z0-9_]{4,})$")


def clean_secret(value: str) -> str:
    """Corrige les erreurs de copier-coller courantes (espaces, guillemets, préfixe « bot »)."""
    value = value.strip().strip("'\"").strip()
    if value.lower().startswith("bot") and value[3:4].isdigit():
        value = value[3:]
    return value


def check_secrets(token: str, chat_id: str) -> list[str]:
    """Problèmes de FORMAT détectables sans réseau (sans jamais afficher les valeurs)."""
    problems = []
    if ":" in chat_id and _TOKEN_FORMAT.match(chat_id):
        problems.append("TELEGRAM_CHAT_ID ressemble à un token : les deux secrets sont inversés ?")
    elif not _CHAT_ID_FORMAT.match(chat_id):
        problems.append(
            f"TELEGRAM_CHAT_ID mal formé ({len(chat_id)} caractères) : attendu un nombre, "
            "ex: 987654321 (ou -100… pour un groupe)"
        )
    if not _TOKEN_FORMAT.match(token):
        problems.append(
            f"TELEGRAM_BOT_TOKEN mal formé ({len(token)} caractères"
            f"{', contient un espace' if ' ' in token else ''}) : attendu "
            "« 123456789:AAH… » tel que donné par @BotFather, sans rien d'autre"
        )
    return problems


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
        token = clean_secret(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        chat_id = clean_secret(os.environ.get("TELEGRAM_CHAT_ID", ""))
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

    def diagnose(self) -> list[str]:
        """Vérifie format + validité du token (getMe). Liste vide = tout va bien côté token."""
        token = self._url.split("/bot", 1)[1].split("/", 1)[0]
        problems = check_secrets(token, self.chat_id)
        if any("TOKEN" in p or "inversés" in p for p in problems):
            return problems
        try:
            data = self.http.get_json(GET_ME_URL.format(token=token))
        except HttpError as exc:
            if exc.status in (401, 404):
                problems.append(
                    "Telegram ne reconnaît pas TELEGRAM_BOT_TOKEN (révoqué, régénéré ou mal "
                    "copié) : recopiez le token actuel depuis @BotFather (/mybots → API Token)"
                )
            else:
                problems.append(f"Vérification du token impossible : {exc}")
            return problems
        username = (data.get("result") or {}).get("username") if isinstance(data, dict) else None
        if username:
            log.info("Token valide : bot @%s", username)
        return problems

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

    def send_listing(self, jobs: Sequence[Job], *, subtitle: str = "") -> bool:
        ok = True
        for message in build_listing_messages(jobs, subtitle=subtitle):
            ok = self._send(message) and ok
        return ok

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
