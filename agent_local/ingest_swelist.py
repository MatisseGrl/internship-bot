"""Add SWElist email job links to the private inventory without duplicates.

Input JSON is a list of {id, date, subject, html} objects obtained from the
authorized Gmail account. This program never connects to Simplify or an ATS.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

FIELDS = [
    "date_mail",
    "id_mail",
    "entreprise",
    "intitule",
    "lien_simplify",
    "premier_filtre",
    "raison",
]


class InternshipParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jobs: list[tuple[str, str, str]] = []
        self.in_job = False
        self.tag: str | None = None
        self.company = ""
        self.title = ""
        self.href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "p" and "internship" in (attributes.get("class") or "").split():
            self.in_job = True
            self.company = self.title = self.href = ""
        elif self.in_job and tag in {"strong", "a"}:
            self.tag = tag
            if tag == "a":
                self.href = attributes.get("href") or ""

    def handle_data(self, data: str) -> None:
        if self.in_job and self.tag == "strong":
            self.company += data
        elif self.in_job and self.tag == "a":
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if not self.in_job:
            return
        if tag == self.tag:
            self.tag = None
        if tag == "p":
            company = self.company.strip().removesuffix(":").strip()
            title = self.title.strip()
            if company and title and self.href:
                self.jobs.append((company, title, self.href))
            self.in_job = False
            self.tag = None


def canonical_simplify_url(raw: str) -> str | None:
    parts = urlsplit(raw)
    if parts.scheme != "https" or parts.hostname != "simplify.jobs":
        return None
    if not re.fullmatch(r"/p/[0-9a-fA-F-]{36}(?:/[^/?#]+)?", parts.path):
        return None
    # The UUID is stable; slugs and tracking parameters are presentation only.
    return urlunsplit(("https", "simplify.jobs", "/p/" + parts.path.split("/")[2].lower(), "", ""))


def title_filter(title: str) -> tuple[str, str]:
    t = title.casefold()
    tech = re.search(
        r"\bai\b|\bml\b|machine learning|software|data|computer vision|artificial intelligence|llm",
        t,
    )
    if re.search(r"\bphd\b|doctor(?:al|ate)", t):
        mixed = re.search(
            r"(?:ms|masters?|master's|bs|bachelor)[/\s,&-]*phd|phd[/\s,&-]*(?:ms|masters?)", t
        )
        return (
            ("a_revoir", "Master ou doctorat mentionnes")
            if mixed
            else ("ecarter_titre", "doctorat explicite")
        )
    if re.search(
        r"\baudit\b|\bassurance\b|\bvaluation\b|\bfinance\b|\bmarketing\b|\bsales\b"
        r"|product management|product manager|product operations|product intern"
        r"|external manufacturing|\bsafety\b|technical artist|ui/ux",
        t,
    ):
        return "ecarter_titre", "fonction hors cible probable"
    hardware = re.search(
        r"\bmechanical\b|\bcivil\b|\bchemical\b|\boptical\b|\bphotonics?\b|optoelectronic"
        r"|\bhardware\b|\basic\b|\brtl\b|\bvlsi\b|signal integrity|display array"
        r"|integrated circuit|\belectronics?\b|\belectrical\b|\bmanufacturing\b"
        r"|\btechnician\b|\bsemiconductor\b",
        t,
    )
    if hardware:
        if tech:
            return "a_revoir", "melange IA ou logiciel avec un domaine materiel"
        return "ecarter_titre", "domaine materiel hors cible probable"
    if re.search(
        r"software|machine learning|data scien|applied scien|\bai\b|artificial intelligence"
        r"|computer vision|business intelligence|\bquant|full stack|analytics|data analy"
        r"|developer|\bllm\b|agentic|recommendation|knowledge graph|data engineer"
        r"|research engineer|research scientist|frontend|backend|mobile engineer|firmware"
        r"|robot learning|data management",
        t,
    ):
        return "retenir_titre", "logiciel, IA ou donnees dans l'intitule"
    return "a_revoir", "intitule insuffisant pour conclure"


def ingest(messages: list[dict], inventory: Path) -> dict[str, int]:
    old: list[dict[str, str]] = []
    if inventory.exists():
        with inventory.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != FIELDS:
                raise ValueError("Schema CSV inattendu")
            old = list(reader)
    seen = {row["lien_simplify"] for row in old}
    incoming: list[dict[str, str]] = []
    for message in messages:
        message_id = str(message["id"])
        date = str(message["date"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"Date invalide pour le mail {message_id}")
        parser = InternshipParser()
        parser.feed(str(message["html"]))
        claimed = re.search(r"(\d+) New Internship", str(message.get("subject", "")))
        if claimed and len(parser.jobs) != int(claimed.group(1)):
            raise ValueError(f"Nombre d'annonces inattendu pour le mail {message_id}")
        if not parser.jobs:
            raise ValueError(f"Aucune annonce dans le mail {message_id}")
        for company, title, href in parser.jobs:
            url = canonical_simplify_url(href)
            if not url:
                raise ValueError(f"Lien inattendu dans le mail {message_id}")
            if url in seen:
                continue
            seen.add(url)
            status, reason = title_filter(title)
            incoming.append(
                dict(
                    zip(
                        FIELDS, [date, message_id, company, title, url, status, reason], strict=True
                    )
                )
            )
    if incoming:
        inventory.parent.mkdir(parents=True, exist_ok=True)
        temp_name = inventory.with_name(inventory.name + f".{os.getpid()}.tmp")
        try:
            with temp_name.open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(old + incoming)
            os.replace(temp_name, inventory)
        finally:
            if temp_name.exists():
                temp_name.unlink()
    return {
        "messages": len(messages),
        "annonces_ajoutees": len(incoming),
        "total": len(old) + len(incoming),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages-json", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    messages = json.loads(args.messages_json.read_text(encoding="utf-8"))
    if not isinstance(messages, list):
        raise ValueError("La source doit etre une liste de mails")
    print(json.dumps(ingest(messages, args.inventory), ensure_ascii=False))


if __name__ == "__main__":
    main()
