from __future__ import annotations

import io
import json

import pytest
import responses

from internbot.errors import ConfigError
from internbot.notifiers import ConsoleNotifier, TelegramNotifier
from internbot.notifiers.formatting import (
    TELEGRAM_MAX_CHARS,
    build_grouped_messages,
    format_job_html,
    split_message,
)
from tests.conftest import job, make_http

TOKEN = "123456:ABC-def_ghi"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def telegram(threshold: int = 10) -> TelegramNotifier:
    return TelegramNotifier(TOKEN, "42", http=make_http(max_retries=2), group_threshold=threshold)


# -- formatage -----------------------------------------------------------------------------------


def test_format_job_html_escapes_everything() -> None:
    j = job("1", title="Intern <C++> & Rust", company_name="AT&T", location="Paris <FR>")
    j = j.with_updates(url='https://x.com/?a=1&b="2"', posted_at="2026-10-08")
    text = format_job_html(j)
    assert text.startswith("🆕 <b>AT&amp;T</b>\nIntern &lt;C++&gt; &amp; Rust\n📍 Paris &lt;FR&gt;")
    assert "📅 2026-10-08" in text
    assert 'href="https://x.com/?a=1&amp;b=&quot;2&quot;"' in text


def test_split_message_short_untouched() -> None:
    assert split_message("hello") == ["hello"]


def test_split_message_on_paragraphs_and_limit() -> None:
    paras = [f"para {i} " + "x" * 50 for i in range(10)]
    chunks = split_message("\n\n".join(paras), limit=130)
    assert all(len(c) <= 130 for c in chunks)
    assert "\n\n".join(chunks) == "\n\n".join(paras)


def test_split_message_huge_single_line() -> None:
    chunks = split_message("y" * 10_000)
    assert [len(c) for c in chunks] == [4096, 4096, 1808]


def test_split_message_long_paragraph_with_lines() -> None:
    text = "\n".join(f"line {i:04d} " + "z" * 40 for i in range(300))
    chunks = split_message(text, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).count("line ") == 300


def test_grouped_messages_never_split_a_job_and_respect_limit() -> None:
    jobs = [job(str(i), title=f"Software Engineer Intern #{i} " + "w" * 120) for i in range(80)]
    messages = build_grouped_messages(jobs)
    assert len(messages) > 1
    assert all(len(text) <= TELEGRAM_MAX_CHARS for text, _ in messages)
    assert sum(len(m) for _, m in messages) == 80
    assert "80 nouvelles offres" in messages[0][0] and "(partie 1)" in messages[0][0]


def test_grouped_single_message_has_no_part_suffix() -> None:
    messages = build_grouped_messages([job("1"), job("2")])
    assert len(messages) == 1 and "partie" not in messages[0][0]


# -- console -------------------------------------------------------------------------------------


def test_console_notifier_prints_and_delivers_all() -> None:
    out = io.StringIO()
    jobs = [job("1"), job("2")]
    assert ConsoleNotifier(out).notify(jobs) == jobs
    assert out.getvalue().count("🆕 Acme") == 2


# -- telegram ------------------------------------------------------------------------------------


@responses.activate
def test_telegram_individual_messages_below_threshold() -> None:
    responses.post(URL, json={"ok": True, "result": {}})
    delivered = telegram().notify([job("1"), job("2")])
    assert len(delivered) == 2
    assert len(responses.calls) == 2
    body = json.loads(responses.calls[0].request.body)
    assert body["chat_id"] == "42" and body["parse_mode"] == "HTML"
    assert body["text"].startswith("🆕 <b>Acme</b>")


@responses.activate
def test_telegram_grouped_above_threshold() -> None:
    responses.post(URL, json={"ok": True})
    delivered = telegram(threshold=3).notify([job(str(i)) for i in range(5)])
    assert len(delivered) == 5
    assert len(responses.calls) == 1
    assert "5 nouvelles offres" in json.loads(responses.calls[0].request.body)["text"]


@responses.activate
def test_telegram_failure_returns_only_delivered() -> None:
    responses.post(URL, json={"ok": True})
    responses.post(URL, status=400, json={"ok": False, "description": "Bad Request"})
    delivered = telegram().notify([job("1"), job("2")])
    assert [j.job_id for j in delivered] == ["1"]


@responses.activate
def test_telegram_ok_false_counts_as_failure() -> None:
    responses.post(URL, json={"ok": False, "description": "chat not found"})
    assert telegram().notify([job("1")]) == []


@responses.activate
def test_telegram_429_retry_after_then_success() -> None:
    responses.post(URL, status=429, json={"ok": False, "parameters": {"retry_after": 3}})
    responses.post(URL, json={"ok": True})
    t = telegram()
    assert len(t.notify([job("1")])) == 1
    assert 3.0 in t.http.sleeps  # type: ignore[attr-defined]


@responses.activate
def test_telegram_send_text_escapes_and_splits() -> None:
    responses.post(URL, json={"ok": True})
    assert telegram().send_text("a < b\n\n" + "c" * 5000)
    texts = [json.loads(c.request.body)["text"] for c in responses.calls]
    assert texts[0].startswith("a &lt; b")
    assert all(len(t) <= TELEGRAM_MAX_CHARS for t in texts)


def test_telegram_from_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        TelegramNotifier.from_env()
