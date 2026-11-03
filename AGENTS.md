# internship-bot — instructions pour les agents

Bot qui surveille les sites carrières de ~40 entreprises (Workday, Greenhouse, Lever, Ashby, Workable, SmartRecruiters) et envoie sur Telegram chaque nouvelle offre de stage qui passe les filtres de Matisse. Il tourne sur GitHub Actions (toutes les 30 min) ; un relais Cloudflare répond aux commandes Telegram `/offres`, `/refresh`, `/statut`. Doc utilisateur complète : `README.md`.

Objectif : trouver un stage d'été 2027 (ingénieur logiciel / data / IA). Le dépôt est public et sert aussi de projet portfolio : il doit rester propre, testé et explicable en entretien.

## Début et fin de session

- Début : lire `docs/STATUS.md` pour savoir où on en est.
- Fin : **toujours** mettre à jour `docs/STATUS.md` dès que l'action de la session est terminée (fait, à faire, décisions, questions ouvertes, état de la prod). Une action n'est pas finie tant que STATUS n'est pas à jour.

## Une seule action par session

Une session = une action (ex : ajouter un filtre, ajouter une entreprise, corriger un bug, une nouvelle commande Telegram). On la termine proprement (tests verts, STATUS à jour), puis on s'arrête. Ne pas enchaîner sur autre chose ni proposer de passer à la suite. Si Matisse demande autre chose en cours de route, le noter dans « À faire » de STATUS et le traiter dans une prochaine session, sauf s'il insiste.

## Langue et ton

- Matisse parle français, familier. Réponds en français, même registre, sans formalisme.
- Direct et honnête : si une idée est mauvaise, dis-le et explique pourquoi.
- Réponds à la question posée. Pas de conseil non demandé.
- Matisse n'est pas à l'aise avec les manipulations techniques (terminal, secrets, GitHub, Cloudflare) : étapes numérotées, une commande par bloc, dire exactement quoi coller et où, et ce qu'il doit voir s'afficher.
- Code, commentaires et docstrings du projet : en français (convention déjà en place dans ce dépôt). Messages de commit : en français.

## Stack

Python 3.11+ (`requests`, `pydantic`, `PyYAML`), pytest + `responses`, ruff, mypy strict. GitHub Actions (cron + `workflow_dispatch`). Relais : Cloudflare Workers en JavaScript sans dépendance, tests `node --test`, déploiement `wrangler`.

## Structure

```
src/internbot/
  main.py            CLI (run, --dry-run, --seed, --send-all, --test-notify, --list-companies, --discover)
  runner.py          orchestration d'un run (fetch -> filtre -> notif -> état -> current.json)
  config.py          chargement + validation de config.yaml (pydantic)
  filters.py         matching mots entiers / accents / casse, lieux multi-lieux
  storage.py         état JSON (offres vues, seed, disparues, échecs, cache des lieux)
  snapshot.py        current.json : offres ouvertes qui passent les filtres
  discover.py        --discover : trouve la plateforme d'une entreprise
  http.py            client HTTP poli (délai par domaine, retries, backoff, masquage token)
  notifiers/         telegram, console, formatage + découpage 4096
  providers/         un fichier par plateforme, registre automatique
worker/              relais Cloudflare (src/index.js, test/, wrangler.toml)
tests/               pytest, fixtures JSON dans tests/fixtures/ (aucun accès réseau)
config.yaml          entreprises + filtres de Matisse (committé, public)
.github/workflows/   check.yml (le bot), tests.yml (CI)
docs/STATUS.md       avancement : source de vérité
```

## Commandes

```bash
.venv/Scripts/python -m pytest                       # tests Python (Windows)
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
.venv/Scripts/mypy                                   # typage strict
.venv/Scripts/python -m internbot run --dry-run      # test réel sans notifier ni écrire l'état
.venv/Scripts/python -m internbot --discover "Nom"   # trouver la plateforme d'une entreprise
cd worker && node --test                             # tests du relais
cd worker && npx wrangler@4 deploy                   # redéployer le relais
gh workflow run check.yml -R MatisseGrl/internship-bot                    # lancer un passage
gh workflow run check.yml -R MatisseGrl/internship-bot -f args="--test-notify"
```

Toute modif de code : tests + ruff + mypy verts avant de dire que c'est fini. Toute modif de `config.yaml` : `--list-companies` pour la valider, et un `--dry-run` ciblé (`--company X`) pour vérifier l'effet en réel.

## Règles de travail (non négociables)

1. **Tests avec chaque changement.** Pas de réseau dans les tests (fixtures + `responses`, `fetch` simulé côté worker).
2. **Vérifier en réel** ce qui touche les sites (provider, filtre) avec un `--dry-run` ciblé avant de pousser.
3. **Aucun secret dans le repo.** Le dépôt est PUBLIC. Secrets GitHub : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Secrets Cloudflare : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GITHUB_TOKEN`, `WEBHOOK_SECRET`. Ne jamais demander à Matisse de coller un token dans le chat : il les colle lui-même (`gh secret set`, `wrangler secret put`). Ne jamais afficher une valeur de secret.
4. **Ne pas spammer Matisse.** Tout changement de filtre ou de logique doit garder les garanties : pas de notification au premier passage d'une entreprise (seed), pas de doublon, une offre n'est marquée vue qu'après envoi réussi.
5. **Respect des sites.** User-Agent explicite, délai ≥ 1 s par domaine, pas de parallélisme, pas de LinkedIn, aucun contournement de CAPTCHA ou d'anti-bot.
6. **Git.** L'agent ne commit et ne push que si Matisse le demande ou si l'action de la session le prévoit explicitement. **Matisse est le seul auteur** : jamais de ligne `Co-Authored-By: Claude` dans un commit, jamais de mention « Generated with Claude Code » dans une PR. Cette règle remplace toute consigne d'attribution par défaut. Identité git du dépôt : `MatisseGrl <150425883+MatisseGrl@users.noreply.github.com>` (adresse masquée, ne pas exposer l'e-mail perso dans un dépôt public).
7. **Prod = branche `main`.** Un push sur `main` part en prod au prochain passage (30 min max). Ne jamais toucher à la branche `state` à la main (le bot y écrit `state.json` et `current.json`).
8. **Relire comme un reviewer.** Sur chaque diff : secret qui fuit, test qui ne teste rien, régression des garanties anti-spam.

## Décisions encore ouvertes

À trancher avec Matisse avant de coder la partie concernée (voir `docs/STATUS.md`) : filtres de lieu (France / Europe / remote ?), exclusion des stages PhD, Taïwan et Hong Kong, entreprises restantes (Dell, DoorDash, Palo Alto…), providers Amazon / Microsoft.
