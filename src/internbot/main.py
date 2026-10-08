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
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from internbot import __version__
from internbot.config import AppConfig, CompanyConfig, HttpConfig, load_config
from internbot.discover import render_report, run_discovery
from internbot.errors import ConfigError
from internbot.http import HttpClient
from internbot.notifiers import ConsoleNotifier, Notifier, TelegramNotifier
from internbot.runner import Runner
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
    p.add_argument("--test-notify", action="store_true", help="envoie un message de test")
    p.add_argument("--list-companies", action="store_true", help="liste les entreprises")
    p.add_argument(
        "--discover",
        nargs="+",
        metavar="NOM|URL",
        help="trouve la plateforme d'entreprises (nom, URL « Apply », ou Nom=URL)",
    )
    p.add_argument("--discover-file", metavar="PATH", help="liste d'entreprises, une par ligne")
    p.add_argument("--discover-out", metavar="PATH", help="écrit le YAML découvert dans ce fichier")
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
        return matches  # --company force même une entreprise désactivée
    return [c for c in cfg.companies if c.enabled]


def cmd_list(cfg: AppConfig) -> int:
    for c in cfg.companies:
        opts = ", ".join(f"{k}={v}" for k, v in c.options.items())
        status = "" if c.enabled else "  [désactivée]"
        print(f"{c.name:<24} {c.provider:<16} {opts}{status}")
    return EXIT_OK


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
    runner = Runner(cfg, state, notifier, http, dry_run=args.dry_run, force_seed=args.seed)
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
        if args.test_notify:
            return cmd_test_notify(cfg)
        return cmd_run(cfg, args)
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    except RuntimeError as exc:  # état corrompu, etc.
        log.error("%s", exc)
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
