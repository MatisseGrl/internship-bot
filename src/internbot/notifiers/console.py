"""Notifier console : utilisé par --dry-run et pour le débogage."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from internbot.models import Job
from internbot.notifiers.base import Notifier
from internbot.notifiers.formatting import format_job_plain


class ConsoleNotifier(Notifier):
    def __init__(self, stream: TextIO | None = None, *, prefix: str = "") -> None:
        self.stream = stream or sys.stdout
        self.prefix = prefix

    def notify(self, jobs: Sequence[Job]) -> list[Job]:
        for job in jobs:
            self._write(format_job_plain(job))
        return list(jobs)

    def send_text(self, text: str) -> bool:
        self._write(text)
        return True

    def _write(self, text: str) -> None:
        sep = "─" * 60
        print(f"{sep}\n{self.prefix}{text}", file=self.stream, flush=True)
