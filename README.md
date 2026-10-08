# internbot 🆕 — alertes Telegram pour les nouvelles offres de stage

Un bot qui surveille les sites carrières d'une liste d'entreprises et vous envoie un message
Telegram **dès qu'une nouvelle offre de stage correspondant à vos filtres est publiée**.
Il tourne tout seul sur GitHub Actions (votre ordinateur peut rester éteint).

```
🆕 Salesforce
Summer 2027 Intern - Software Engineer
📍 California - San Francisco · California - Palo Alto · New York - New York · …
📅 2026-08-31
🔗 Voir l'offre
```

**Plateformes supportées** : Workday (Salesforce, NVIDIA, Adobe…), Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, et un mode Playwright générique de dernier recours.

**Garanties** :
- **pas de spam au premier lancement** : la première fois qu'une entreprise est vue, toutes ses
  offres existantes sont enregistrées *sans* notification (seed silencieux) ;
- **pas de doublon** : chaque offre est identifiée par `(entreprise, id)` ;
- **pas d'offre perdue** : une offre n'est marquée « vue » qu'**après** l'envoi réussi du message
  Telegram (sinon elle est renvoyée au run suivant) ;
- **isolation** : si une entreprise échoue (site en panne, format modifié), les autres continuent,
  l'erreur est résumée en fin de run, et vous êtes alerté après 3 échecs consécutifs.

---

## Sommaire

1. [Démarrage rapide (local)](#1-démarrage-rapide-local)
2. [Créer le bot Telegram](#2-créer-le-bot-telegram)
3. [Configuration](#3-configuration-configyaml)
4. [Trouver la plateforme d'une entreprise / en ajouter une](#4-trouver-la-plateforme-dune-entreprise-et-lajouter)
5. [Déploiement GitHub Actions pas à pas](#5-déploiement-github-actions-pas-à-pas)
6. [Ligne de commande](#6-ligne-de-commande)
7. [Fonctionnement et choix techniques](#7-fonctionnement-et-choix-techniques)
8. [Dépannage](#8-dépannage)
9. [Limites connues](#9-limites-connues)
10. [Développement](#10-développement)

---

## 1. Démarrage rapide (local)

Prérequis : Python 3.11+ et git.

```bash
git clone https://github.com/<vous>/internship-bot.git
cd internship-bot
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml # puis adaptez filtres et entreprises
cp .env.example .env               # puis mettez votre token et chat_id (section 2)

python -m internbot --list-companies   # vérifie la config
python -m internbot run --dry-run      # montre ce qui serait envoyé, sans rien écrire
python -m internbot --test-notify      # envoie un message Telegram de test
python -m internbot run                # vrai run (1er run = seed silencieux)
```

> Le fichier `.env` n'est lu qu'en local (et n'écrase jamais une variable déjà définie). Il est
> ignoré par git. En CI, les secrets viennent des *GitHub Secrets*.

## 2. Créer le bot Telegram

1. Dans Telegram, ouvrez une conversation avec **[@BotFather](https://t.me/BotFather)**.
2. Envoyez `/newbot`, choisissez un nom puis un identifiant finissant par `bot`
   (ex: `mon_internbot`).
3. BotFather vous répond avec un **token** du type `123456789:AAH...` → c'est
   `TELEGRAM_BOT_TOKEN`. Gardez-le secret (quiconque l'a peut parler en son nom).
4. **Ouvrez une conversation avec votre nouveau bot et envoyez-lui un message** (ex: `/start`).
   Un bot ne peut pas écrire à quelqu'un qui ne lui a jamais écrit.
5. Récupérez votre **chat_id** : ouvrez dans un navigateur
   `https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates`
   et repérez `"chat":{"id":123456789,...}` → c'est `TELEGRAM_CHAT_ID`.
   - Si la liste `result` est vide, renvoyez un message au bot et rechargez la page.
   - Pour un **groupe** : ajoutez le bot au groupe, écrivez un message dans le groupe, le
     `chat.id` est alors négatif (ex: `-100123...`).
6. Testez : `python -m internbot --test-notify`.

## 3. Configuration (`config.yaml`)

Tout se règle dans `config.yaml` (aucun secret dedans, il peut être commité).
`config.example.yaml` est entièrement commenté. Les points clés :

### Filtres

```yaml
filters:
  title_include: ["intern", "interns", "internship", "stage", "stagiaire", "co-op", "working student"]
  title_exclude: ["senior", "staff", "principal", "manager", "director", "high school"]
  locations_include: []     # vide = toutes ; ex: ["France", "Paris", "Remote", "Europe"]
  locations_exclude: []
  keywords_any: ["software", "engineer", "data", "ml", "backend", "full stack"]  # vide = aucun
  year_hint: ["2027"]
  year_hint_mode: prefer    # prefer | require | off
```

Règles de matching :
- **insensible à la casse et aux accents** : `stagiaire` matche « STAGIAIRE », `zurich` matche
  « Zürich » ;
- **mots entiers** : `intern` ne matche **pas** « Internal » ni « International »… ni
  « Internship » (d'où `internship` dans la liste). `ml` ne matche pas « HTML » ;
- la ponctuation compte comme un espace : `co-op` matche « Co-op » et « CO OP », `full stack`
  matche « Full-Stack » ;
- une offre est retenue si son titre contient **un** terme de `title_include`, **aucun** terme
  de `title_exclude`, **un** terme de `keywords_any` (si la liste n'est pas vide), et si son lieu
  passe `locations_include` / `locations_exclude` ;
- `year_hint_mode: prefer` (défaut) écarte les titres qui mentionnent **seulement une autre
  année** (« Summer 2026 Intern ») mais garde ceux sans année ; `require` exige l'année ;
- un **lieu inconnu ou partiel** (Workday affiche parfois « 8 Locations ») n'est **jamais**
  rejeté : mieux vaut une alerte de trop qu'une offre manquée. Pour Workday, le bot va de toute
  façon chercher la liste complète des lieux pour les offres candidates.

Filtres spécifiques à une entreprise (surcharge champ par champ) :

```yaml
  - name: Doctolib
    provider: workable
    account: doctolib
    filters:
      locations_include: ["France"]
```

> ⚠️ Les offres qui ne passent pas les filtres sont quand même enregistrées comme « vues ».
> Si vous élargissez vos filtres plus tard, seules les **futures** offres seront notifiées (pas
> d'avalanche d'anciennes offres). Pour voir ce que donnent de nouveaux filtres sur l'existant :
> `python -m internbot run --dry-run --state /chemin/vide.json`.

### Autres sections

| Section | Rôle |
|---|---|
| `notifier.type` | `telegram` (défaut) ou `console` |
| `notifier.group_threshold` | au-delà de N nouvelles offres dans un run (défaut 10), envoi en messages groupés (≤ 4096 caractères, jamais une offre coupée en deux) |
| `http.user_agent` | **mettez-y un contact** (ex: l'URL de votre dépôt) |
| `http.min_delay_s` | délai entre deux requêtes (≥ 1 s imposé, défaut 1,5 s) |
| `alerts.failure_threshold` | alerte Telegram quand une entreprise échoue N runs d'affilée (défaut 3, 0 = off) |
| `digest.enabled` / `every_days` | récapitulatif périodique (désactivé par défaut) |
| `companies[].enabled` | `false` pour mettre une entreprise en pause sans la supprimer |

Une erreur de config (champ manquant, provider inconnu, faute de frappe dans un nom de champ,
nom d'entreprise en double…) est signalée **au démarrage** avec un message clair, par exemple :

```
Configuration invalide (config.yaml) :
  - companies[0] (Salesforce) : champ(s) obligatoire(s) manquant(s) pour provider 'workday' : site
  - companies[3] (Foo) : provider inconnu 'taleo'. Disponibles : ashby, greenhouse, lever, ...
```

## 4. Trouver la plateforme d'une entreprise et l'ajouter

### Automatiquement : `--discover`

```bash
python -m internbot --discover "Anthropic" "Scale AI" "Capital One"
python -m internbot --discover "Slack=https://salesforce.wd12.myworkdayjobs.com/Slack"
python -m internbot --discover-file entreprises.txt --discover-out trouve.yaml
```

Pour chaque entrée (un nom, une URL de candidature, ou `Nom=URL`), le bot **interroge
réellement** Greenhouse, Ashby, Lever (US et EU), Workable, SmartRecruiters puis, en dernier
recours, Workday, et ne retient que ce qui renvoie des offres. Il affiche un bloc YAML prêt à
coller sous `companies:` :

```yaml
- name: Scale AI  # 181 offres
  provider: greenhouse
  board: scaleai
# --- Non trouvées automatiquement :
# - DoorDash : introuvable sur ... -> donnez l'URL « Apply » (Nom=URL)
```

- Les identifiants **approchés** (« Epic Games » trouvé sous `epic`) ou dont le nom
  d'organisation ne correspond pas sont marqués **« à vérifier »** : un même identifiant peut
  appartenir à une autre entreprise.
- Un compte **existant mais vide** est signalé (souvent un ancien compte après migration).
- **Workday** : le bot trouve le `wdN` grâce aux codes d'erreur (422 = mauvais tenant/wdN,
  404 = bon tenant mais mauvais site), puis essaie les noms de site usuels (`External`,
  `Careers`, `{Nom}Careers`…). Si le site a un nom exotique, donnez l'URL `Nom=URL` : c'est
  instantané et fiable.
- Les entreprises sur SuccessFactors, Avature, Eightfold, Oracle HCM ou un site maison ne sont
  pas détectées (voir *Limites*).

### Manuellement

Ouvrez une offre sur le site carrières de l'entreprise et cliquez sur **« Postuler / Apply »**.
L'URL de la page de candidature trahit la plateforme :

| URL de candidature | `provider` | Champ(s) à renseigner |
|---|---|---|
| `https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/...` | `workday` | `tenant: salesforce`, `wd: wd12`, `site: External_Career_Site` |
| `boards.greenhouse.io/stripe` ou `job-boards.greenhouse.io/stripe` | `greenhouse` | `board: stripe` |
| `jobs.lever.co/spotify/...` (ou `jobs.eu.lever.co/...`) | `lever` | `company: spotify` (+ `region: eu`) |
| `jobs.ashbyhq.com/openai/...` | `ashby` | `board: openai` |
| `jobs.smartrecruiters.com/BoschGroup/...` | `smartrecruiters` | `company_id: BoschGroup` |
| `apply.workable.com/huggingface/...` | `workable` | `account: huggingface` |

Puis ajoutez un bloc dans `companies:` et vérifiez :

```bash
python -m internbot run --dry-run --company "Nom" -v
```

Le dry-run affiche le nombre d'offres récupérées et celles qui passent vos filtres.

### Cas Workday : retrouver tenant / wd / site

Beaucoup de grandes entreprises ont une « vitrine » (ex: `salesforce.com/company/careers/...`)
devant Workday. Un identifiant d'offre du type `JR340771` est un bon indice. Pour trouver le
vrai tenant :

1. Cliquez sur **Apply** d'une offre : vous arrivez sur `https://{tenant}.{wdN}.myworkdayjobs.com/{site}/...`
   (parfois `/{locale}/{site}/...`, ex: `/en-US/External_Career_Site/...` : la locale ne fait pas
   partie du `site`).
2. Sinon : outils de développement du navigateur (F12) → onglet *Réseau* → filtrez sur `cxs` :
   la requête `POST .../wday/cxs/{tenant}/{site}/jobs` donne les trois valeurs.
3. Vérifiez :
   ```bash
   curl -s -X POST -H "Content-Type: application/json" -H "Accept: application/json" \
     -d '{"appliedFacets":{},"limit":20,"offset":0,"searchText":"intern"}' \
     https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs | head -c 300
   ```
   Une réponse `{"total":..., "jobPostings":[...]}` = c'est bon. Un `HTTP 422` ou `404` = mauvais
   `wd` ou `site`.

**Salesforce (vérifié le 2026-10-08)** : `tenant: salesforce`, `wd: wd12`,
`site: External_Career_Site`. L'offre `JR340771` « Summer 2027 Intern - Software Engineer » y est
bien retrouvée. NVIDIA (`nvidia` / `wd5` / `NVIDIAExternalCareerSite`) et Adobe (`adobe` / `wd5`
/ `external_experienced`) ont été vérifiés le même jour.

Options Workday : `search_text` (défaut `intern`, pré-filtre plein texte côté Workday),
`max_pages` (défaut 100 × 20 offres), `applied_facets` (filtres Workday bruts, avancé),
`fetch_details` (défaut `true`), `max_details` (défaut 25 requêtes de détail par run).

### Site sans API (dernier recours)

```bash
pip install -e ".[playwright]" && playwright install chromium
```
```yaml
  - name: MaBoite
    provider: playwright
    url: https://exemple.com/careers
    item_selector: "li.job"        # un élément par offre
    title_selector: "h3"
    link_selector: "a"
    location_selector: ".location" # optionnel
```
Une page chargée par run, sans clic ni contournement : si le site affiche un CAPTCHA ou une
protection anti-bot, le provider échoue proprement. En CI, ajoutez l'installation de Playwright
au workflow (`pip install ".[playwright]" && playwright install --with-deps chromium`).

### Ajouter une nouvelle plateforme (développeurs)

Créez `src/internbot/providers/maplateforme.py` avec une classe décorée par `@register`
(`name`, `required_fields`, `fetch_jobs()`). Le registre importe automatiquement tous les modules
du package : aucun autre fichier à modifier. Ajoutez une fixture JSON et un test.

## 5. Déploiement GitHub Actions pas à pas

1. **Créez un dépôt GitHub** et poussez le projet :
   ```bash
   git remote add origin https://github.com/<vous>/internship-bot.git
   git push -u origin main
   ```
   💡 **Dépôt public recommandé** : les minutes Actions y sont illimitées. Sur un dépôt privé, le
   quota gratuit est de 2 000 min/mois ; un run dure ~5 min avec 40 entreprises (une minute entamée est
   facturée), donc un cron toutes les 30 min le dépasse. En privé, passez le cron à
   `17 */2 * * *` (toutes les 2 h) ou réduisez la liste d'entreprises. Le dépôt ne contient
   aucun secret ; la branche `state` ne contient que des titres d'offres publiques.
2. **Ajoutez les secrets** : *Settings → Secrets and variables → Actions → New repository
   secret* :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. **Autorisez l'écriture** : *Settings → Actions → General → Workflow permissions* → cochez
   **Read and write permissions** (le workflow pousse l'état sur la branche `state`).
4. **Testez Telegram** : onglet *Actions* → *Check internships* → *Run workflow* avec
   `args` = `--test-notify`.
5. **Premier vrai run** : *Run workflow* sans argument. Il crée la branche `state` et fait le
   seed silencieux (aucun message, c'est normal). Les runs suivants partent tout seuls toutes
   les 30 min et ne notifient que les nouvelles offres.

Le workflow `tests.yml` lance lint + typage + tests à chaque push sur `main`.

### Persistance de l'état : pourquoi une branche `state`

- L'état est un **fichier JSON trié** (`state.json`), donc les diffs sont lisibles : vous voyez
  dans l'historique de la branche `state` quelles offres sont apparues et quand.
- Il est commité sur une **branche orpheline dédiée** `state` (montée dans `.state/` via
  `git worktree`), jamais sur `main` : votre historique de code reste propre.
- **Pas de boucle de déclenchement** : le workflow ne réagit qu'à `schedule` et
  `workflow_dispatch`, jamais à un `push` ; les commits portent en plus `[skip ci]`.
- **Pas de conflit** : `concurrency` garantit un seul run à la fois, et c'est le seul writer.
- **Pas de commit inutile** : le fichier ne contient aucune donnée qui change à chaque run
  (pas de « last_seen ») ; on ne committe que si une offre apparaît/disparaît ou si une source
  échoue.
- L'état est sauvegardé **même si le run échoue** (`if: always()`), pour conserver les compteurs
  d'échec.
- Pourquoi pas `actions/cache` : un cache est évincé après 7 jours sans accès et est immuable
  par clé ; une perte d'état provoquerait un re-seed (silencieux, donc des offres manquées pendant
  ce run). Un commit git est durable et auditable.

### ⚠️ Particularités des workflows planifiés

- GitHub **ne garantit pas l'heure** des crons : des retards de 5 à 30 min (voire plus aux heures
  de pointe) sont courants, et un run peut exceptionnellement sauter.
- Sur un dépôt public, GitHub **désactive les workflows planifiés après 60 jours sans activité**
  sur le dépôt. Les commits du bot sur la branche `state` ne sont pas garantis compter comme
  activité : GitHub vous prévient par e-mail avant ; il suffit alors de cliquer sur
  *Enable workflow* dans l'onglet Actions, ou de faire un commit de temps en temps sur `main`.
- Si **toutes** les sources échouent (ou si la config est invalide), le run est marqué en échec :
  GitHub vous envoie un e-mail.

## 6. Ligne de commande

```
python -m internbot [run] [options]

  run                 exécution normale (commande par défaut)
  --dry-run           affiche dans la console ce qui serait envoyé ; n'écrit pas l'état
  --seed              enregistre l'existant sans notifier (re-seed explicite)
  --test-notify       envoie un message de test Telegram
  --list-companies    liste les entreprises configurées
  --discover X [Y…]   trouve la plateforme (nom, URL « Apply » ou Nom=URL)
  --discover-file F   idem, une entreprise par ligne (# = commentaire)
  --discover-out F    écrit le YAML trouvé dans F
  --company NAME      ne traite qu'une entreprise (même désactivée) — debug
  -v, --verbose       logs détaillés (requêtes, raisons de rejet de chaque offre)
  -c, --config PATH   défaut : config.yaml (ou $INTERNBOT_CONFIG)
  --state PATH        défaut : state/state.json (ou $INTERNBOT_STATE)
```

Codes de sortie : `0` OK (même si certaines entreprises échouent), `1` toutes les sources ont
échoué / le test Telegram a échoué, `2` configuration invalide (dont secrets manquants).

## 7. Fonctionnement et choix techniques

Pour chaque entreprise, dans l'ordre :

1. **Récupération** via l'API JSON de la plateforme (pagination gérée, limite de sécurité).
2. **Dédoublonnage** par `job_id` (Workday : le numéro de réquisition `JR...`, stable ; sinon
   l'identifiant de la plateforme).
3. **Première fois ?** → seed silencieux, fin.
4. **Détection des offres disparues** (simple log ; elles restent connues pour ne pas être
   re-notifiées si elles réapparaissent, et sont purgées après 180 jours).
5. **Nouvelles offres** → filtre sur le titre → *enrichissement* (Workday : lieux complets et
   date réelle, seulement pour les candidates, max 25 requêtes) → filtre sur le lieu.
6. Les offres rejetées sont marquées vues ; les retenues sont mises en attente.

En fin de run, toutes les offres retenues sont envoyées (individuellement jusqu'à
`group_threshold`, groupées au-delà), puis **seules celles effectivement envoyées** sont marquées
vues. L'état est écrit de façon atomique (fichier temporaire + renommage) après chaque entreprise.

**Politesse envers les sites** : User-Agent explicite et configurable, requêtes strictement
séquentielles, ≥ 1 s entre deux requêtes vers un même domaine (1,5 s par défaut), timeouts, retries avec backoff
exponentiel (2 s, 4 s, 8 s + aléa) uniquement sur erreurs réseau / 429 / 5xx, respect de
`Retry-After`. Aucune retry sur les autres 4xx (inutile d'insister sur une erreur de
paramétrage). **LinkedIn n'est pas supporté** (CGU), et aucun contournement de CAPTCHA ou de
protection anti-bot n'est tenté.

**Sécurité** : secrets uniquement via variables d'environnement ; le token Telegram est masqué
dans tous les logs et messages d'erreur ; tout contenu inséré dans les messages Telegram (HTML)
est échappé.

Choix par défaut (modifiables) :
- **Telegram en HTML** plutôt que MarkdownV2 : l'échappement est bien plus simple et robuste.
- Workday `search_text: intern` : réduit fortement le nombre de pages tout en ratissant large
  (la recherche Workday est plein texte, le filtrage fin est fait par le bot). Si une entreprise
  publie ses stages sous un autre mot (« Praktikum », « apprenti »…), adaptez `search_text` ou
  mettez `""` pour tout récupérer.
- Liens Workday : forme canonique sans locale (`.../External_Career_Site/job/...`), identique à
  l'`externalUrl` renvoyée par Workday (vérifié : les deux formes, avec ou sans `en-US/`,
  répondent 200).
- Date affichée : date ISO quand elle est connue ; pour Workday, « Posted Today » est converti
  en date, et la vraie date de publication est récupérée lors de l'enrichissement.
- `keywords_any` est renseigné dans l'exemple (profil ingénieur logiciel / tech) : sans lui,
  vous recevriez aussi les stages en vente, marketing, RH… Videz la liste pour tout recevoir.

## 8. Dépannage

| Symptôme | Cause probable / solution |
|---|---|
| `Variable(s) d'environnement manquante(s)` | Secrets non définis (`.env` en local, GitHub Secrets en CI). |
| Le test Telegram échoue avec `chat not found` | Vous n'avez pas envoyé de message au bot, ou mauvais `chat_id`. |
| `HTTP 401 Unauthorized` (Telegram) | Token invalide ou régénéré : mettez à jour le secret. |
| Workday : `HTTP 422` / `404` + « vérifiez tenant/wd/site » | Mauvais `wd` ou `site` : refaites la section 4. |
| `format de réponse inattendu` / `format modifié ?` | La plateforme a changé son API. L'erreur est isolée à cette entreprise. Adaptez le provider. |
| `0 offre alors que N étaient actives` | Recherche ou format modifié côté site, ou toutes les offres ont été retirées. |
| Aucune notification depuis longtemps | Normal s'il n'y a pas de nouvelle offre ! Vérifiez avec `--dry-run -v` (raisons de rejet) et l'onglet Actions (workflow désactivé ?). |
| Je veux repartir de zéro en CI | Supprimez la branche `state` sur GitHub : le prochain run refera un seed silencieux. |
| Le workflow ne tourne plus | 60 jours d'inactivité : *Actions → Check internships → Enable workflow*. |
| `Fichier d'état corrompu` | Corrigez ou supprimez `state.json` (re-seed silencieux). |
| `push` refusé dans l'étape *Save state* | *Workflow permissions* n'est pas en *Read and write* (section 5, étape 3). |

Logs détaillés : `python -m internbot run --dry-run -v --company Salesforce`.

## 9. Limites connues

- **L'endpoint Workday (`/wday/cxs/...`) n'est pas une API officielle** : c'est celui qu'utilise
  le site carrières lui-même. Workday peut le modifier sans préavis ; le bot le détectera
  (erreur de format isolée + alerte après 3 échecs) mais il faudra adapter le provider. Même
  remarque, à moindre degré, pour le widget Workable.
- Greenhouse, Lever, Ashby et SmartRecruiters exposent des API publiques documentées, a priori
  stables.
- Une offre publiée puis retirée entre deux runs (< 30 min) peut être manquée.
- Les crons GitHub peuvent être retardés : comptez une alerte dans l'heure, pas à la minute.
- La détection repose sur les filtres de titre : une offre de stage dont le titre ne contient
  aucun mot-clé (ex: « Software Engineer, New Grad 2027 ») ne sera pas détectée ; ajustez
  `title_include`.
- **Plateformes non couvertes** : sites maison avec API JSON propre (Amazon, Microsoft,
  Tencent, Atlassian, Uber), Eightfold (Netflix, PayPal), Oracle HCM, SuccessFactors (SAP),
  Avature (Bloomberg)… Chacun demanderait un provider dédié (un fichier dans `providers/`).
  Google, Apple, Meta, Tesla, TikTok n'ont pas d'API exploitable proprement : utilisez leurs
  **alertes e-mail natives**.
- Workday plafonne la recherche à 20 offres par page ; `max_pages: 100` limite à 2 000 offres
  par entreprise (un warning apparaît si la limite est atteinte).

## 10. Développement

```bash
pip install -e ".[dev]"
pytest              # tests unitaires, sans aucun accès réseau (fixtures JSON + `responses`)
ruff check . && ruff format --check .
mypy                # typage strict
```

Structure :

```
src/internbot/
├── main.py            # CLI (argparse)
├── runner.py          # orchestration d'un run
├── config.py          # chargement + validation (pydantic)
├── filters.py         # matching mots entiers / accents / casse
├── storage.py         # état JSON (seed, vues, disparues, échecs)
├── http.py            # client HTTP poli (délai, retries, backoff, masquage token)
├── models.py          # Job
├── notifiers/         # telegram, console, formatage + découpage 4096
└── providers/         # registre + workday, greenhouse, lever, ashby, smartrecruiters,
                       #   workable, playwright_generic
tests/                 # tests unitaires, fixtures dans tests/fixtures/
```
