from __future__ import annotations

import pytest
import requests
import responses

from internbot.errors import HttpError
from internbot.http import HttpClient, redact
from tests.conftest import make_http

URL = "https://api.example.com/jobs"


@responses.activate
def test_retries_on_5xx_with_exponential_backoff() -> None:
    responses.get(URL, status=503)
    responses.get(URL, status=502)
    responses.get(URL, json={"ok": 1})
    http = make_http(max_retries=3, backoff_base_s=2.0)
    assert http.get_json(URL) == {"ok": 1}
    assert len(responses.calls) == 3
    first, second = http.sleeps  # type: ignore[attr-defined]
    assert 2.0 <= first < 2.6 and 4.0 <= second < 4.6


@responses.activate
def test_gives_up_after_max_retries() -> None:
    responses.get(URL, status=500)
    with pytest.raises(HttpError) as exc:
        make_http(max_retries=2).get_json(URL)
    assert exc.value.status == 500
    assert len(responses.calls) == 3


@responses.activate
def test_no_retry_on_404() -> None:
    responses.get(URL, status=404, body="not found")
    with pytest.raises(HttpError, match="HTTP 404"):
        make_http().get_json(URL)
    assert len(responses.calls) == 1


@responses.activate
def test_retry_after_header_respected() -> None:
    responses.get(URL, status=429, headers={"Retry-After": "7"})
    responses.get(URL, json=[])
    http = make_http()
    http.get_json(URL)
    assert http.sleeps == [7.0]  # type: ignore[attr-defined]


@responses.activate
def test_network_error_retried() -> None:
    responses.get(URL, body=requests.ConnectionError("boom"))
    responses.get(URL, json={"a": 1})
    assert make_http().get_json(URL) == {"a": 1}


@responses.activate
def test_non_json_response() -> None:
    responses.get(URL, body="<html>captcha</html>", content_type="text/html")
    with pytest.raises(HttpError, match="non-JSON"):
        make_http().get_json(URL)


@responses.activate
def test_user_agent_and_post_headers() -> None:
    responses.post(URL, json={})
    HttpClient(user_agent="my-bot/1.0", min_delay_s=0, sleep=lambda s: None).post_json(
        URL, {"x": 1}
    )
    req = responses.calls[0].request
    assert req.headers["User-Agent"] == "my-bot/1.0"
    assert req.headers["Content-Type"] == "application/json"


def test_min_delay_between_requests() -> None:
    sleeps: list[float] = []
    now = [0.0]
    http = HttpClient(min_delay_s=1.0, sleep=sleeps.append, clock=lambda: now[0])
    http._throttle("https://a.wd5.myworkdayjobs.com/x")
    now[0] = 0.3
    http._throttle("https://b.wd12.myworkdayjobs.com/y")  # même domaine : attend
    assert sleeps == [pytest.approx(0.7)]
    http._throttle("https://boards-api.greenhouse.io/z")  # autre domaine : pas d'attente
    assert len(sleeps) == 1


def test_redact_hides_telegram_token() -> None:
    url = "https://api.telegram.org/bot123456:ABC-def_ghi/sendMessage"
    assert redact(url) == "https://api.telegram.org/bot***/sendMessage"


@responses.activate
def test_error_message_never_contains_token() -> None:
    url = "https://api.telegram.org/bot123456:SECRET/sendMessage"
    responses.post(url, status=401, json={"ok": False})
    with pytest.raises(HttpError) as exc:
        make_http().post_json(url, {})
    assert "SECRET" not in str(exc.value)
