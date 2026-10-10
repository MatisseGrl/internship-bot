"""Point d'entrée CLI.

    python -m internbot run [--dry-run] [--seed] [--company NAME] [-v]
    python -m internbot --test-notify
    python -m internbot --list-companies
    python -m internbot --discover "Anthropic" "Slack=https://salesforce.wd12.myworkdayjobs.com/Slack"

Codes de sortie : 0 OK (même si certaines sources échouent), 1 toutes les sources ont échoué
ou le message de test n'est pas parti, 2 configuration invalide.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any

from internbot import __version__
from internbot.config import AppConfig, CompanyConfig, HttpConfig, load_config
from internbot.descriptions import DescriptionError, DescriptionFetcher
from internbot.discover import render_report, run_discovery
from internbot.errors import ConfigError
from internbot.http import HttpClient
from internbot.models import Job
from internbot.notation import Notation, importer, load_entreprises
from internbot.notifiers import ConsoleNotifier, Notifier, TelegramNotifier
from internbot.providers import get_provider_class
from internbot.runner import Runner
from internbot.snapshot import build_health, load_snapshot, snapshot_jobs
from internbot.storage import StateStore

log = logging.getLogger("internbot")

EXIT_OK, EXIT_FAILURE, EXIT_CONFIG = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="internbot",
        description="Alertes Telegram pour les nouvelles offres de stage.",
    )
    p.add_argument("command", nargs="?", default="run", choices=["run"], help="(défaut : run)")
    p.add_argument("-c", "--config", default=os.environ.get("INTERNBOT_CONFIG", "config.yaml"))
    p.add_argument(
        "--state",
        default=os.environ.get("INTERNBOT_STATE", "state/state.json"),
        help="fichier d'état JSON (défaut : state/state.json)",
    )
    p.add_argument("--dry-run", action="store_true", help="affiche sans notifier ni écrire l'état")
    p.add_argument("--seed", action="store_true", help="enregistre l'existant sans notifier")
    p.add_argument(
        "--send-all",
        action="store_true",
        help="envoie aussi la liste de TOUTES les offres ouvertes qui passent les filtres",
    )
    p.add_argument("--test-notify", action="store_true", help="envoie un message de test")
    p.add_argument("--list-companies", action="store_true", help="liste les entreprises")
    p.add_argument(
        "--status",
        action="store_true",
        help="santé de chaque entreprise (dernier succès, offres, NOTIFY/REVIEW, erreur)",
    )
    p.add_argument(
        "--discover",
        nargs="+",
        metavar="NOM|URL",
        help="trouve la plateforme d'entreprises (nom, URL « Apply », ou Nom=URL)",
    )
    p.add_argument("--discover-file", metavar="PATH", help="liste d'entreprises, une par ligne")
    p.add_argument("--discover-out", metavar="PATH", help="écrit le YAML découvert dans ce fichier")
    p.add_argument(
        "--a-noter",
        metavar="DOSSIER",
        help="exporte le texte des offres ouvertes pas encore notées (DOSSIER/offres.jsonl)",
    )
    p.add_argument(
        "--importer-notes",
        metavar="DOSSIER",
        help="applique les notes DOSSIER/notes*.jsonl à notation/notes.json",
    )
    p.add_argument(
        "--simulation",
        action="store_true",
        help="avec --importer-notes : vérifie les notes et affiche les verdicts sans rien écrire",
    )
    p.add_argument("--company", metavar="NAME", help="ne traiter qu'une entreprise (debug)")
    p.add_argument("-v", "--verbose", action="store_true", help="logs détaillés (DEBUG)")
    p.add_argument("--version", action="version", version=f"internbot {__version__}")
    return p


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def load_dotenv(path: Path = Path(".env")) -> None:
    """Mini-chargeur .env (KEY=VALUE) pour l'usage local ; n'écrase pas l'environnement."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def make_http(cfg: AppConfig) -> HttpClient:
    h = cfg.http
    return HttpClient(
        user_agent=h.user_agent,
        timeout_s=h.timeout_s,
        min_delay_s=h.min_delay_s,
        max_retries=h.max_retries,
        backoff_base_s=h.backoff_base_s,
    )


def make_notifier(cfg: AppConfig, *, dry_run: bool) -> Notifier:
    if dry_run or cfg.notifier.type == "console":
        return ConsoleNotifier(prefix="[dry-run] " if dry_run else "")
    return TelegramNotifier.from_env(
        group_threshold=cfg.notifier.group_threshold,
        disable_link_preview=cfg.notifier.disable_link_preview,
    )


def select_companies(cfg: AppConfig, name: str | None) -> list[CompanyConfig]:
    if name:
        matches = [c for c in cfg.companies if c.name.casefold() == name.casefold()]
        if not matches:
            known = ", ".join(c.name for c in cfg.companies)
            raise ConfigError(f"Entreprise '{name}' absente de la config (connues : {known})")
        manual = [c for c in matches if not is_automated(c)]
        if manual:
            raise ConfigError(
                f"{manual[0].name} est suivie à la main ({manual[0].opt('reason')}) : "
                f"{manual[0].opt('careers_url')}"
            )
        return matches  # --company force même une entreprise désactivée
    return [c for c in cfg.companies if c.enabled and is_automated(c)]


def is_automated(company: CompanyConfig) -> bool:
    return get_provider_class(company.provider).automated


def cmd_list(cfg: AppConfig) -> int:
    for c in cfg.companies:
        opts = ", ".join(f"{k}={v}" for k, v in c.options.items())
        status = "" if c.enabled else "  [désactivée]"
        if not is_automated(c):
            status = "  [manuel]"
        print(f"{c.name:<24} {c.provider:<16} {opts}{status}")
    return EXIT_OK


def cmd_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Lit current.json (écrit à chaque run) : aucune requête réseau."""
    snapshot = load_snapshot(Path(args.state).with_name("current.json"))
    # Recalculée sur la config actuelle : entreprises ajoutées (pending), manuelles, désactivées.
    previous = snapshot.get("health") or {}
    failures = {name: int(h.get("failures") or 0) for name, h in previous.items()}
    health = build_health(previous, cfg.companies, [], failures, _now())
    order = {"error": 0, "ok": 1, "pending": 2, "manual": 3, "disabled": 4}
    rows = sorted(health.items(), key=lambda kv: (order.get(kv[1]["status"], 9), kv[0].casefold()))
    print(
        f"{'Entreprise':<28} {'Provider':<15} {'Statut':<9} {'Dernier succès':<17} "
        f"{'Offres':>6} {'NOTIFY':>6} {'REVIEW':>6}  Remarque"
    )
    for name, h in rows:
        note = h.get("error") or ""
        if h["status"] == "manual":
            note = f"{h.get('reason')} — {h.get('careers_url')}"
        elif h.get("failures"):
            note = f"{h['failures']} échec(s) d'affilée : {note}"
        last = (h.get("last_success") or "-")[:16].replace("T", " ")
        print(
            f"{name[:28]:<28} {h['provider']:<15} {h['status']:<9} {last:<17} "
            f"{_num(h.get('fetched')):>6} {_num(h.get('notify')):>6} {_num(h.get('review')):>6}"
            f"  {note[:160]}"
        )
    counts = {k: sum(1 for _, h in rows if h["status"] == k) for k in order}
    print(
        f"\n{len(rows)} entreprise(s) : "
        + ", ".join(f"{n} {k}" for k, n in counts.items() if n)
        + f". Mise à jour : {snapshot.get('updated_at') or 'jamais'}"
    )
    return EXIT_OK


def _num(value: object) -> str:
    return "-" if value is None else str(value)


def _now() -> datetime:
    return datetime.now(UTC)


def cmd_discover(args: argparse.Namespace) -> int:
    entries = list(args.discover or [])
    if args.discover_file:
        path = Path(args.discover_file)
        if not path.is_file():
            raise ConfigError(f"Fichier introuvable : {path}")
        entries += path.read_text(encoding="utf-8").splitlines()
    try:  # on reprend le User-Agent de la config si elle existe
        http_cfg = load_config(args.config).http
    except ConfigError:
        http_cfg = HttpConfig()
    # Découverte : beaucoup de sondes vouées à l'échec -> ni retry, ni long timeout.
    http = HttpClient(user_agent=http_cfg.user_agent, timeout_s=10, min_delay_s=1.0, max_retries=0)
    findings = run_discovery(entries, http)
    report = render_report(findings)
    if args.discover_out:
        Path(args.discover_out).write_text(report, encoding="utf-8")
        log.info("YAML écrit dans %s", args.discover_out)
    print(report)
    found = sum(f.found for f in findings)
    log.info(
        "%d/%d entreprise(s) trouvée(s), %d requête(s).", found, len(findings), http.request_count
    )
    return EXIT_OK if found else EXIT_FAILURE


def cmd_test_notify(cfg: AppConfig) -> int:
    notifier = make_notifier(cfg, dry_run=False)
    if isinstance(notifier, TelegramNotifier):
        problems = notifier.diagnose()
        for problem in problems:
            log.error("%s", problem)
        if problems:
            return EXIT_FAILURE
    ok = notifier.send_text(
        f"✅ internbot {__version__} : test de notification réussi. "
        f"{sum(c.enabled for c in cfg.companies)} entreprise(s) surveillée(s)."
    )
    if ok:
        log.info("Message de test envoyé.")
        return EXIT_OK
    log.error(
        "Échec de l'envoi du message de test. Token valide : le problème vient de "
        "TELEGRAM_CHAT_ID, ou vous n'avez pas appuyé sur « Démarrer » dans la conversation "
        "avec votre bot."
    )
    return EXIT_FAILURE


def notation_dir(args: argparse.Namespace) -> Path:
    """`notation/` vit à côté de config.yaml (versionné sur main, lu par le bot en CI)."""
    return Path(args.config).resolve().parent / "notation"


def cmd_a_noter(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Exporte le texte des offres ouvertes (current.json) pas encore notées.

    Reprend là où il s'était arrêté : les offres déjà présentes dans offres.jsonl sont sautées.
    Les offres sont parcourues entreprise par entreprise en alternance, pour que le délai de
    politesse par domaine ne bloque pas tout l'export sur un seul site.
    """
    out_dir = Path(args.a_noter)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "offres.jsonl"
    done = {(o["company"], o["job_id"]) for o in read_jsonl(out)}
    notation = Notation.load(notation_dir(args) / "notes.json")
    snapshot = load_snapshot(Path(args.state).with_name("current.json"))
    by_company: dict[str, list[Job]] = {}
    for job in snapshot_jobs(snapshot):
        if args.company and job.company.casefold() != args.company.casefold():
            continue
        if notation.est_notee(*job.key) or job.key in done:
            continue
        by_company.setdefault(job.company, []).append(job)
    queue = [j for group in zip_longest(*by_company.values()) for j in group if j is not None]
    log.info("%d offre(s) à exporter (%d déjà dans %s).", len(queue), len(done), out)
    fetcher = DescriptionFetcher(make_http(cfg), {c.name: c for c in cfg.companies})
    failures = 0
    with out.open("a", encoding="utf-8", newline="\n") as fh:
        for i, job in enumerate(queue, 1):
            row: dict[str, object] = {
                "company": job.company,
                "job_id": job.job_id,
                "title": job.title,
                "location": job.location,
                "url": job.url,
            }
            try:
                description = fetcher.fetch(job)
                row.update(texte=description.text, source=description.source)
            except DescriptionError as exc:
                failures += 1
                row["erreur"] = str(exc)[:300]
                log.warning("%s — %s : %s", job.company, job.title, row["erreur"])
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 50 == 0:
                log.info("%d/%d offres exportées (%d illisibles).", i, len(queue), failures)
    log.info("Export terminé : %d offre(s), dont %d illisible(s).", len(queue), failures)
    return EXIT_OK


def cmd_importer_notes(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Valide les notes (citations comprises) et met à jour notation/notes.json."""
    src = Path(args.importer_notes)
    folder = notation_dir(args)
    notation = Notation.load(folder / "notes.json")
    entreprises = load_entreprises(folder / "entreprises.yaml")
    notes = [n for path in sorted(src.glob("notes*.jsonl")) for n in read_jsonl(path)]
    report = importer(notation, read_jsonl(src / "offres.jsonl"), notes, entreprises)
    for error in report.erreurs:
        log.error("Note refusée : %s", error)
    if args.simulation:
        for company, title, statut, score in report.verdicts:
            print(f"{statut:<11} {'' if score is None else score:>3}  {company} — {title}")
    else:
        notation.save()
    log.info(
        "%d note(s) lue(s) ; verdicts %s : %s ; %d refusée(s).%s",
        len(notes),
        "calculés" if args.simulation else "appliqués",
        ", ".join(f"{k} {v}" for k, v in sorted(report.statuts.items())) or "aucun",
        len(report.erreurs),
        " Simulation : rien n'a été écrit."
        if args.simulation
        else f" {len(notation)} offre(s) dans {notation.path}.",
    )
    return EXIT_FAILURE if report.erreurs else EXIT_OK


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ConfigError(f"{path}:{n} : ligne JSON invalide ({exc})") from None
    return rows


def cmd_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    companies = select_companies(cfg, args.company)
    if not companies:
        log.error("Aucune entreprise activée dans la configuration.")
        return EXIT_CONFIG
    notifier = make_notifier(cfg, dry_run=args.dry_run)
    state = StateStore.load(args.state)
    if args.dry_run:
        state.path = None  # garde-fou : impossible d'écrire l'état en dry-run
    http = make_http(cfg)
    runner = Runner(
        cfg,
        state,
        notifier,
        http,
        dry_run=args.dry_run,
        force_seed=args.seed,
        send_all=args.send_all,
        # current.json vit à côté de state.json (branche `state` en CI).
        snapshot_path=Path(args.state).with_name("current.json"),
        notation=Notation.load(notation_dir(args) / "notes.json"),
    )
    report = runner.run(companies)
    log.info("%s", report.summary())
    log.info("%d requête(s) HTTP effectuée(s).", http.request_count)
    return EXIT_FAILURE if report.all_failed else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # console Windows (cp1252) : accents et emojis
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    load_dotenv()
    try:
        if args.discover or args.discover_file:
            return cmd_discover(args)
        cfg = load_config(args.config)
        if args.list_companies:
            return cmd_list(cfg)
        if args.status:
            return cmd_status(cfg, args)
        if args.test_notify:
            return cmd_test_notify(cfg)
        if args.a_noter:
            return cmd_a_noter(cfg, args)
        if args.importer_notes:
            return cmd_importer_notes(cfg, args)
        return cmd_run(cfg, args)
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    except RuntimeError as exc:  # état corrompu, etc.
        log.error("%s", exc)
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
