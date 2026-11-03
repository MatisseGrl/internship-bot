# Mission parallèle pour Claude — export ciblé des annonces

Ce document sert de passage de relais. Il n'autorise aucune candidature.

## Contexte

Codex construit l'agent local de candidatures sur la branche **`codex/agent-candidatures`**, dans une copie isolée du dépôt. Claude travaille sur **sa propre branche** à partir de `main`, sans modifier `agent_local/` ni la base privée. Le bot actuel collecte et note les offres, mais beaucoup de lignes du registre de l'agent n'ont pas le texte complet de l'annonce. Le module `src/internbot/descriptions.py` sait déjà récupérer un texte par plateforme. La commande `--a-noter` dans `src/internbot/main.py` l'utilise, mais saute les offres déjà notées ; elle ne répond donc pas à ce besoin.

## Ce que Claude doit lire avant de coder

1. `AGENTS.md` et `docs/STATUS.md` — règles du dépôt et état de production.
2. `src/internbot/main.py` — en particulier `cmd_a_noter`, les arguments et `read_jsonl`.
3. `src/internbot/descriptions.py` — `DescriptionFetcher`, erreurs et limite des pages protégées.
4. `src/internbot/snapshot.py` — format `current.json` version 1 et `snapshot_jobs`.
5. `tests/test_descriptions.py`, `tests/test_main.py` — style des tests existants.
6. `agent_local/README.md` **seulement si la branche Codex est accessible en lecture** ; ne pas copier ni modifier ce dossier.

## Une seule tâche à réaliser

Ajouter une commande locale **d'export ciblé pour l'agent**. Elle reçoit une liste explicite de couples `company` / `job_id` et le `current.json` existant ; elle récupère le texte uniquement pour ces offres, **même si elles figurent déjà dans `notation/notes.json`**. Réutiliser `DescriptionFetcher` et le client HTTP poli existants. Aucune récupération en masse des ~1 200 offres dans le cron GitHub Actions.

Le format de sortie attendu est un JSONL UTF-8, une ligne par offre demandée :

```json
{"company":"Exemple","job_id":"42","title":"Stage IA","location":"Paris","url":"https://...","texte":"Texte intégral","source":"api greenhouse"}
```

En cas d'échec de lecture, conserver la ligne et écrire `erreur` au lieu de `texte`. Ne pas inventer de texte et ne pas contourner les protections des sites. Un `job_id` absent du snapshot doit être signalé clairement, sans arrêter les autres lignes. L'agent Codex importe ce JSONL avec `sync-bot --archives export.jsonl`. La commande doit être idempotente ou documenter précisément sa règle de reprise, pour éviter les téléchargements répétés après interruption.

## Ce qu'il ne faut pas toucher

- Ne pas changer les seuils, la grille de notation, les filtres, Telegram, le cron ni `current.json` de production.
- Ne pas ouvrir ni modifier les CV, Gmail, Simplify, les fichiers du dossier Codex privé ou les secrets.
- Ne pas postuler, créer de compte ou automatiser un formulaire.
- Ne pas modifier ni fusionner la branche `codex/agent-candidatures`.

## Vérification et livraison

- Tests hors réseau pour : offre déjà notée exportée, identifiant absent, erreur de récupération, relance sans doublon.
- `pytest`, `ruff`, `mypy` verts selon `AGENTS.md` ; vérification réelle ciblée sur une seule offre accessible avec un dossier de sortie temporaire.
- Mettre à jour `docs/STATUS.md` et la documentation de la nouvelle commande.
- Travailler et committer sur une branche propre, par exemple `claude/export-agent-descriptions`, puis communiquer le nom de la branche, le commit, la commande exacte et un exemple de ligne JSONL. Ne pas fusionner ni pousser en production.
