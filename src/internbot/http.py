"""Client HTTP « poli » partagé par tous les providers et le notifier Telegram.

- User-Agent explicite ;
- délai minimal entre deux requêtes vers un même domaine (séquentiel, aucun parallélisme) ;
- timeouts systématiques ;
- retries avec backoff exponentiel sur erreurs réseau, 429 et 5xx (respect de Retry-After) ;
- aucune retry sur les autres 4xx (erreur de paramétrage : inutile d'insister).
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import requests

from internbot import __version__
from internbot.errors import HttpError

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    f"internbot/{__version__} (personal internship alert bot; low-frequency polling; "
    "+https://github.com/)"
)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_S = 120.0

_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def redact(text: str) -> str:
    """Masque les tokens Telegram qui pourraient apparaître dans une URL ou un message."""
    return _TOKEN_RE.sub("bot***", text)


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: float = 20.0,
        min_delay_s: float = 1.0,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout_s = timeout_s
        self.min_delay_s = min_delay_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: dict[str, float] = {}
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.request_count = 0

    # -- API publique -------------------------------------------------------------------------

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        resp = self.request("GET", url, params=params, headers=headers)
        return self._decode(resp)

    def post_json(
        self,
        url: str,
        body: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        resp = self.request("POST", url, json_body=body, headers=hdrs)
        return self._decode(resp)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response:
        safe_url = redact(url)
        attempt = 0
        while True:
            self._throttle(url)
            self.request_count += 1
            log.debug("HTTP %s %s (tentative %d)", method, safe_url, attempt + 1)
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=dict(headers) if headers else None,
                    timeout=self.timeout_s,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.max_retries:
                    raise HttpError(
                        f"{method} {safe_url} : échec réseau après {attempt + 1} tentatives "
                        f"({redact(type(exc).__name__)})",
                        url=safe_url,
                    ) from None
                self._backoff(attempt, None, f"erreur réseau {type(exc).__name__}")
                attempt += 1
                continue
            except requests.RequestException as exc:
                raise HttpError(f"{method} {safe_url} : {redact(str(exc))}", url=safe_url) from None

            if resp.status_code < 400:
                return resp

            if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                self._backoff(attempt, _retry_after(resp), f"HTTP {resp.status_code}")
                attempt += 1
                continue

            snippet = redact(resp.text[:300].replace("\n", " "))
            raise HttpError(
                f"{method} {safe_url} : HTTP {resp.status_code} — {snippet}",
                status=resp.status_code,
                url=safe_url,
            )

    # -- interne -------------------------------------------------------------------------------

    def _throttle(self, url: str) -> None:
        # Délai par domaine enregistrable (ex: tous les tenants *.myworkdayjobs.com partagent
        # le même compteur) : on ménage chaque opérateur sans attendre en changeant de site.
        domain = _domain(url)
        last = self._last_request_at.get(domain)
        if last is not None:
            wait = self.min_delay_s - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at[domain] = self._clock()

    def _backoff(self, attempt: int, retry_after: float | None, reason: str) -> None:
        if retry_after is not None:
            delay = min(retry_after, MAX_RETRY_AFTER_S)
        else:
            delay = self.backoff_base_s * (2**attempt) + random.uniform(0, 0.5)
        log.warning("%s — nouvelle tentative dans %.1f s", reason, delay)
        self._sleep(delay)

    @staticmethod
    def _decode(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            raise HttpError(
                f"Réponse non-JSON depuis {redact(resp.url)} "
                f"(Content-Type: {resp.headers.get('Content-Type')})",
                status=resp.status_code,
                url=redact(resp.url),
            ) from None


def _domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return ".".join(host.split(".")[-2:])


def _retry_after(resp: requests.Response) -> float | None:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            return None
    # Telegram renvoie parfois le délai uniquement dans le corps JSON.
    try:
        data = resp.json()
    except ValueError:
        return None
    if isinstance(data, dict):
        params = data.get("parameters")
        if isinstance(params, dict) and isinstance(params.get("retry_after"), int | float):
            return float(params["retry_after"])
    return None
