"""Mise en forme des messages et découpage aux limites de Telegram."""

from __future__ import annotations

import html
from collections.abc import Sequence

from internbot.models import Job

TELEGRAM_MAX_CHARS = 4096
MAX_TITLE_CHARS = 300
STAR = "⭐ "  # offre IA (priorité du filtre v3)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def format_job_html(job: Job, *, header: bool = True) -> str:
    """Bloc HTML Telegram pour une offre (tout est échappé)."""
    star = STAR if job.priority else ""
    lines = []
    if header:
        lines.append(f"{star}🆕 <b>{esc(job.company)}</b>")
    else:
        lines.append(f"{star}<b>{esc(job.company)}</b>")
    lines.append(esc(_clip(job.title, MAX_TITLE_CHARS)))
    if job.location:
        lines.append(f"📍 {esc(_clip(job.location, 300))}")
    if job.posted_at:
        lines.append(f"📅 {esc(job.posted_at)}")
    lines.append(f'🔗 <a href="{html.escape(job.url, quote=True)}">Voir l\'offre</a>')
    return "\n".join(lines)


def format_job_plain(job: Job) -> str:
    lines = [f"{STAR if job.priority else ''}🆕 {job.company}", job.title]
    if job.location:
        lines.append(f"📍 {job.location}")
    if job.posted_at:
        lines.append(f"📅 {job.posted_at}")
    lines.append(f"🔗 {job.url}")
    return "\n".join(lines)


def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Découpe un texte trop long : d'abord sur les paragraphes, puis les lignes, puis en dur.

    Attention : à n'utiliser en HTML que sur du texte dont les balises tiennent sur une ligne
    (c'est le cas de tous les messages générés ici).
    """
    if limit <= 0:
        raise ValueError("limit doit être > 0")
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        pieces = [para] if len(para) <= limit else _split_lines(para, limit)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _split_lines(text: str, limit: int) -> list[str]:
    out: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # ligne monstrueuse : découpe brute
            if current:
                out.append(current)
                current = ""
            out.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
        else:
            out.append(current)
            current = line
    if current:
        out.append(current)
    return out


def build_grouped_messages(
    jobs: Sequence[Job], *, limit: int = TELEGRAM_MAX_CHARS
) -> list[tuple[str, list[Job]]]:
    """Regroupe plusieurs offres par message sans jamais couper une offre en deux.

    Retourne une liste (texte, offres contenues) pour pouvoir marquer « vues » uniquement
    les offres des messages effectivement envoyés.
    """
    total = len(jobs)
    blocks = [(format_job_html(j, header=False), j) for j in jobs]
    messages: list[tuple[str, list[Job]]] = []
    body: list[str] = []
    members: list[Job] = []
    reserve = 80  # place pour l'en-tête

    def flush() -> None:
        if members:
            part = len(messages) + 1
            header = f"🆕 <b>{total} nouvelles offres de stage</b> (partie {part})"
            messages.append((header + "\n\n" + "\n\n".join(body), list(members)))
            body.clear()
            members.clear()

    size = 0
    for block, job in blocks:
        block = _clip(block, limit - reserve)
        added = len(block) + 2
        if members and size + added > limit - reserve:
            flush()
            size = 0
        body.append(block)
        members.append(job)
        size += added
    flush()
    if len(messages) == 1:  # pas besoin de « partie 1 » s'il n'y en a qu'une
        text, members_ = messages[0]
        messages[0] = (text.replace(" (partie 1)", "", 1), members_)
    return messages


def build_listing_messages(
    jobs: Sequence[Job], *, subtitle: str = "", limit: int = TELEGRAM_MAX_CHARS
) -> list[str]:
    """Liste compacte de TOUTES les offres, groupées par entreprise (HTML Telegram).

    Les offres IA (⭐) d'abord, puis les autres. Une ligne par offre, jamais coupée ;
    l'en-tête d'entreprise est répété (« suite ») quand un groupe déborde sur le message suivant.
    """
    groups: dict[tuple[bool, str], list[Job]] = {}
    for job in jobs:
        groups.setdefault((not job.priority, job.company), []).append(job)

    header = f"📋 <b>{len(jobs)} offre(s) ouverte(s)</b> correspondant à tes filtres"
    if subtitle:
        header += f"\n<i>{esc(subtitle)}</i>"
    if not jobs:
        return [header + "\n\nAucune offre ne correspond actuellement."]

    messages: list[str] = []
    current = header
    for not_priority, company in sorted(groups, key=lambda k: (k[0], k[1].casefold())):
        group = groups[(not_priority, company)]
        star = "" if not_priority else STAR
        company_line = f"{star}<b>{esc(company)}</b> ({len(group)})"
        block_start = f"\n\n{company_line}"
        if len(current) + len(block_start) + 200 > limit:
            messages.append(current)
            current = company_line
        else:
            current += block_start
        for job in group:
            line = (
                f'\n• {star}<a href="{html.escape(job.url, quote=True)}">'
                f"{esc(_clip(job.title, 150))}</a>"
            )
            if job.location:
                line += f" — {esc(_clip(job.location, 80))}"
            if len(current) + len(line) > limit:
                messages.append(current)
                current = f"{star}<b>{esc(company)}</b> (suite)" + line
            else:
                current += line
    messages.append(current)
    return messages


def build_digest_messages(
    header: str, jobs: Sequence[Job], *, limit: int = TELEGRAM_MAX_CHARS
) -> list[str]:
    """Résumé compact : une ligne par offre (entreprise, titre + lien, lieu, raison).

    Sert au résumé quotidien « à vérifier » et au récap unique du passage au filtre v3.
    Offres IA (⭐) en tête. `header` est du HTML déjà échappé.
    """
    ordered = sorted(jobs, key=lambda j: (not j.priority, j.company.casefold(), j.title))
    messages: list[str] = []
    current = header
    for job in ordered:
        line = (
            f"\n• {STAR if job.priority else ''}<b>{esc(job.company)}</b> — "
            f'<a href="{html.escape(job.url, quote=True)}">{esc(_clip(job.title, 150))}</a>'
        )
        if job.location:
            line += f" — 📍 {esc(_clip(job.location, 80))}"
        if job.reason:
            line += f" — <i>{esc(_clip(job.reason, 120))}</i>"
        if len(current) + len(line) > limit:
            messages.append(current)
            current = f"{header} (suite)" + line
        else:
            current += line
    messages.append(current)
    return messages
