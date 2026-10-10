# internbot 🆕 — alertes Telegram pour les nouvelles offres de stage

Un bot qui surveille les sites carrières d'une liste d'entreprises et vous envoie un message
Telegram **dès qu'une nouvelle offre de stage correspondant à vos filtres est publiée**.
Il tourne tout seul sur GitHub Actions (votre ordinateur peut rester éteint).

Exemple de message reçu sur Telegram :

```
🆕 Salesforce
Summer 2027 Intern - Software Engineer
📍 California - San Francisco · California - Palo Alto · New York - New York · …
📅 2026-08-31
🔗 Voir l'offre
```

**Plateformes supportées** : Workday (Salesforce, NVIDIA, Adobe…), Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, Eightfold, Oracle HCM, Avature, Gestmax, sitemaps publics, endpoints JSON
configurables, le site maison d'Apple et un mode Playwright générique de dernier recours.

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

Le classement des offres est fait par le **filtre v3** (`src/internbot/filters_v3.py`, listes de
mots-clés en tête de fichier). Chaque offre tombe dans un seau :

| Seau | Quoi | Ce que fait le bot |
|---|---|---|
| `notify` | stage software / data / IA / FDE dans une zone voulue | alerte Telegram immédiate, **⭐ si offre IA** |
| `review` | ambigu (titre flou, hardware + IA, IA + non-tech, lieu inconnu…) | **résumé quotidien « à vérifier »** (une ligne par offre avec la raison), au premier passage après 9 h (heure de Paris) |
| `drop` | hardware pur, non-tech, PhD uniquement, quant research, hors zone, pas un stage | ignorée (raison visible avec `-v`) |

Les réglages se font dans `config.yaml` :

```yaml
filters:
  regions: [us, canada, uk, europe, asia, australia]  # dispo aussi : israel, japan, uae
  include_data: true
  include_fde: true               # forward deployed / solutions / customer engineer
  include_quant_research: false   # quant research pur (trader, QR)
  # Appliqués AVANT le filtre v3 :
  title_exclude: ["senior", "staff", "principal", "manager", "director", "high school"]
  year_hint: ["2027"]
  year_hint_mode: prefer    # prefer | require | off
```

Règles principales :
- **un signal software explicite gagne toujours contre le hardware** : « GPU Software Performance
  Intern » est gardé, « Performance Engineer Intern » est écarté ;
- hardware + IA sans software (« Hardware Machine Learning Research Intern ») → `review` ;
- **PhD écarté seulement si l'offre est réservée aux PhD** : « BS/MS/PhD » passe ;
- IA + non-tech (« AI Solution Architect Intern ») → `review` ;
- remote / hybrid → gardé ; lieu inconnu (« Multiple Locations ») → `review` ; une offre
  multi-lieux est gardée si **un** de ses lieux est dans une zone ;
- **France : Île-de-France uniquement.** Une offre dont le lieu cite une ville française hors
  Île-de-France (Toulouse, Nantes, Lyon, Marseille, Sophia Antipolis…) sans aucune ville
  d'Île-de-France est `drop` (« France hors Île-de-France »), y compris dans `/offres`. Toute l'Île-de-France
  (75, 77, 78, 91, 92, 93, 94, 95 : villes ou « (92) ») est reconnue même sans « France » ; « France »
  seul ou « Paris ; Toulouse » sont gardés (listes `FRANCE_HORS_IDF` / `ILE_DE_FRANCE`) ;
- matching **insensible à la casse et aux accents**, par **mots entiers** : `intern` ne matche
  pas « Internal », `ml` ne matche pas « HTML », la ponctuation compte comme un espace
  (« Co-op » == « co op ») ;
- `year_hint_mode: prefer` (défaut) écarte les titres qui mentionnent **seulement une autre
  année** (« Summer 2026 Intern ») mais garde ceux sans année ; `require` exige l'année ;
- Workday affiche parfois « 8 Locations » : le bot va chercher la liste complète des lieux ; si
  elle reste inconnue, l'offre passe en `review` (jamais jetée à l'aveugle).

Filtres spécifiques à une entreprise (surcharge champ par champ) :

```yaml
  - name: Doctolib
    provider: workable
    account: doctolib
    filters:
      regions: [europe]
```

> ⚠️ Les offres `review` et `drop` sont quand même enregistrées comme « vues ». Si vous élargissez
> vos filtres plus tard, seules les **futures** offres seront notifiées (pas d'avalanche
> d'anciennes offres). Pour voir ce que donnent de nouveaux filtres sur l'existant :
> `python -m internbot run --dry-run --state /chemin/vide.json`.
>
> Passage de l'ancien filtre au v3 : au premier passage complet, les offres encore ouvertes que
> l'ancien filtre cachait et que le v3 classe `notify` sont envoyées **une seule fois**, dans un
> seul récap (« 🔁 Nouveau filtre : … »). Les anciennes clés `title_include`, `keywords_any`,
> `locations_include`, `locations_exclude` sont ignorées (avertissement au chargement).

### Notation des offres (grille de Matisse)

Après le filtre v3, chaque offre ouverte est notée avec la grille de `notation/GRILLE.md`
(Fit rôle ×45, Écosystème SF ×20, Pont vers SF ×20, Apprentissage ×15, score /100, seuil 65).
Le bot n'appelle aucun modèle d'IA : la notation se fait en session Claude Code, en lisant le
texte complet de chaque annonce, et le bot applique les verdicts enregistrés dans
`notation/notes.json` (versionné sur `main`) :

| Verdict | Dans `/offres` |
|---|---|
| retenue (score ≥ 65) | gardée |
| limite (passe avec un seul jeu de poids), à trancher (alternance, VIE…), illisible (page protégée) | gardée, à trier à la main |
| écartée (non éligible, ou sous le seuil) | **supprimée** de `/offres`, de `--send-all` et du résumé « à vérifier » |
| pas encore notée (nouvelle offre) | gardée |

- `notation/entreprises.yaml` : Écosystème SF et Pont vers SF hors US, une note et sa preuve
  par entreprise ;
- `notation/CONSIGNES.md` : comment noter en série (format des notes, verdicts) ;
- l'import refuse toute note dont une citation n'est pas mot pour mot dans le texte de l'offre.

```bash
python -m internbot --a-noter travail/ --state .state/state.json   # texte des offres non notées
# … notes écrites dans travail/notes*.jsonl (voir notation/CONSIGNES.md) …
python -m internbot --importer-notes travail/ --simulation         # vérifie, n'écrit rien
python -m internbot --importer-notes travail/                      # met à jour notes.json
```

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
- La découverte automatique couvre surtout les plateformes classiques. Une entreprise sur
  SuccessFactors, Avature, Eightfold, Oracle HCM ou un endpoint maison peut être ajoutée dans
  `config.yaml` après vérification de sa vraie page carrières.

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
| `jobs.apple.com/...` | `apple` | aucun (option `team`, défaut `internships-STDNT-INTRN`) |

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
`search_texts` (plusieurs recherches, offres dédupliquées par numéro de réquisition),
`max_pages` (défaut 100 × 20 offres, par recherche), `applied_facets` (filtres Workday bruts,
avancé), `fetch_details` (défaut `true`), `max_details` (défaut 25 requêtes de détail par run).

Avature : `base_url` pointe vers le portail public. `query` (défaut `intern`) ou `queries`
permettent de chercher plusieurs termes ; `max_pages` s'applique à chaque recherche. Certains
portails paginent les offres avec `jobOffset` / `jobRecordsPerPage`, Siemens avec
`folderOffset` / `folderRecordsPerPage` : les options `offset_param`, `page_size_param` et
`page_size` sont configurables. Le bot signale une pagination qui répète la même page.

Gestmax : `base_url` est la racine du portail public (par exemple
`https://mbda.gestmax.fr`). Le provider lit le tableau de `/search/index`, parcourt
`/search/index/page/N` jusqu'au total annoncé et signale une page répétée ou vide
avant la fin. `max_pages` borne le parcours (défaut 50).

### Site sans API (dernier recours)

Si le site interdit la collecte, exige une connexion ou ne fournit aucun flux public stable,
utilisez `provider: manual` avec `careers_url`, `reason` et `alert`. Cette entrée apparaît dans
`--status` et `/status`, sans requête réseau ni notification automatique. Le lien d'alerte
e-mail ou de vérification manuelle doit être indiqué pour chaque entreprise concernée.

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

### Entreprises suivies à la main

27 entreprises n'ont aucune source automatisable proprement (anti-bot, robots.txt qui
interdit la collecte, liste chargée en JavaScript par une API non documentée, ou offres déjà
couvertes par une autre entrée). Elles sont dans `config.yaml` avec `provider: manual` : aucune
requête, mais elles apparaissent dans `--status` et `/status`. Pour chacune, l'alternative :

| Entreprise | Pourquoi | Que faire |
|---|---|---|
| [Google](https://www.google.com/about/careers/applications/jobs/results?q=intern) | robots.txt interdit /about/careers/applications/jobs/results | Bouton « Get job alerts » sur la page de résultats (compte Google) |
| [Meta](https://www.metacareers.com/jobs?q=intern) | robots.txt de metacareers.com interdit toute collecte sans autorisation écrite | « Create job alert » sur metacareers.com (profil candidat) |
| [LinkedIn](https://www.linkedin.com/jobs/search/?keywords=intern&f_C=1337) | offres publiées uniquement sur linkedin.com (scraping de LinkedIn exclu) ; le compte Lever « linkedin » est un bac à sable de test | Alerte d'emploi LinkedIn native (bouton « Créer une alerte » sur cette recherche) |
| [Tesla](https://www.tesla.com/careers/search/?query=intern) | protection anti-bot Akamai (HTTP 403 Access Denied) | Pas d'alerte e-mail publique : vérification manuelle hebdomadaire |
| [X](https://x.ai/careers) | careers.x.com redirige vers x.ai/careers : offres déjà suivies via xAI (Greenhouse « xai ») | Rien à faire : couvert par xAI |
| [Splunk](https://cisco.wd5.myworkdayjobs.com/Cisco_Careers?q=splunk) | filiale de Cisco : offres publiées sur le Workday de Cisco, déjà surveillé (227 offres « splunk » le 9 oct. 2026) | Rien à faire : couvert par Cisco |
| [SAP](https://jobs.sap.com/search/?q=intern) | site Next.js, offres chargées côté client par une API non documentée | « Job alerts » / Talent Community sur jobs.sap.com |
| [ByteDance](https://jobs.bytedance.com/en/position?keywords=intern) | robots.txt de lifeattiktok.com interdit tout ; API jobs.bytedance.com protégée par jeton CSRF de session ; compte SmartRecruiters « Bytedance » abandonné | Alerte e-mail du site (compte candidat) ; voir aussi https://lifeattiktok.com/search?keyword=intern |
| [Dassault Systèmes](https://www.3ds.com/careers/jobs) | offres chargées côté client par le moteur Exalead (/apisearch), format non documenté | « Join our Talent Community » sur 3ds.com/careers |
| [Akamai](https://www.akamai.com/careers) | protection anti-bot (HTTP 403) ; Workday non public | Alerte d'emploi du portail carrières Akamai (compte candidat) |
| [HubSpot](https://www.hubspot.com/careers/jobs?q=intern) | liste chargée en JavaScript par une API non documentée ; Workday « hubspot » non public (HTTP 401) | « Join our Talent Network » sur hubspot.com/careers |
| [Valve](https://www.valvesoftware.com/en/jobs) | robots.txt interdit /jobs | Pas d'alerte : vérification manuelle mensuelle (Valve publie rarement des stages) |
| [Shopify](https://www.shopify.com/careers/search?keywords=intern) | robots.txt de shopify.com interdit tout (Disallow: /) ; Workday « shopify » non public | Page https://internships.shopify.com (inscription aux annonces de la prochaine promo) |
| [Wayfair](https://www.wayfair.com/careers/jobs) | liste chargée en JavaScript ; Workday « wayfair » non public (HTTP 401) ; compte SmartRecruiters avec 1 seule offre | « Job alerts » sur la page carrières Wayfair |
| [Walmart Global Tech](https://careers.walmart.com/results?q=intern) | robots.txt interdit /api et /results ; le sitemap ne donne que des ID (R-1075582) sans titre | « Job Alerts » sur careers.walmart.com |
| [DeepSeek](https://www.deepseek.com/) | pas d'ATS public (recrutement via plateformes chinoises) ; postes en Chine, exclue par tes filtres | Rien à faire tant que la Chine est exclue |
| [Moonshot AI](https://www.moonshot.cn/) | pas d'ATS public ; le compte Workable « moonshot » est une autre entreprise ; postes en Chine, exclue par tes filtres | Rien à faire tant que la Chine est exclue |
| [Safran](https://www.safran-group.com/fr/offres) | protection anti-bot (HTTP 403) sur safran-group.com | Compte candidat + « alerte emploi » (mot-clé stage) sur safran-group.com |
| [Naval Group](https://www.naval-group.com/en/candidates) | liste chargée en JavaScript, aucune API ni ATS public trouvé | Alerte e-mail depuis l'espace candidat Naval Group |
| [Capgemini](https://www.capgemini.com/fr-fr/carrieres/rejoignez-nous/nos-offres-demploi/) | liste chargée en JavaScript par une API non documentée ; pas de sitemap d'offres | « Créer une alerte » sur la page des offres Capgemini |
| [Eviden](https://eviden.com/careers/) | robots.txt interdit /api/ (source de la liste d'offres) | Alerte e-mail sur le portail carrières Eviden |
| [Amadeus](https://jobs.amadeus.com/) | liste chargée en JavaScript, sitemap vide, aucun ATS public trouvé | « Job alert » sur jobs.amadeus.com |
| [OVHcloud](https://careers.ovhcloud.com/fr/) | robots.txt de careers.ovhcloud.com interdit tout (Disallow: /) | Alerte e-mail SuccessFactors (« Recevez les offres par e-mail ») sur careers.ovhcloud.com |
| [Klarna](https://www.klarna.com/careers/) | liste chargée en JavaScript, aucun ATS public trouvé (Greenhouse, Ashby, Lever, Workday testés) | Alerte e-mail sur klarna.com/careers |
| [Nokia](https://jobs.nokia.com/) | liste chargée en JavaScript ; les endpoints Oracle HCM supposés répondent 404 | « Job alerts » sur jobs.nokia.com |
| [Renault](https://www.renaultgroup.com/carrieres/nos-offres/) | robots.txt interdit /api/ (source de la liste d'offres) | Alerte e-mail depuis l'espace candidat Renault Group |
| [EDF](https://www.edf.fr/edf-recrute/offres) | protection anti-bot (HTTP 403) | Créer une alerte (mot-clé stage) depuis l'espace candidat EDF Recrute |

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
   💡 **Public ou privé ?** Le workflow est réglé pour un **dépôt public** (minutes Actions
   illimitées) : un run toutes les heures (~35 min par run avec 188 entreprises). En **privé**, le
   quota gratuit est de 2 000 min/mois (3 000 avec le *GitHub Student Developer Pack*) : passez
   alors le cron à `17 */2 * * *` (toutes les 2 h) et `min_delay_s` à 1.0. Le dépôt ne contient
   aucun secret ; la branche `state` ne contient que des offres publiques.
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
   les heures et ne notifient que les nouvelles offres.

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
- Sur un dépôt **public** (pas en privé), GitHub **désactive les workflows planifiés après 60 jours sans activité**
  sur le dépôt. Les commits du bot sur la branche `state` ne sont pas garantis compter comme
  activité : GitHub vous prévient par e-mail avant ; il suffit alors de cliquer sur
  *Enable workflow* dans l'onglet Actions, ou de faire un commit de temps en temps sur `main`.
- Si **toutes** les sources échouent (ou si la config est invalide), le run est marqué en échec :
  GitHub vous envoie un e-mail.

## 5 bis. Commandes Telegram (`/offres`, `/refresh`)

En plus des alertes automatiques, vous pouvez **demander au bot la liste complète** des offres
ouvertes qui passent vos filtres :

| Commande | Effet | Délai |
|---|---|---|
| `/offres` | toutes les offres ouvertes (`notify` et `review`), offres IA ⭐ d'abord, groupées par entreprise | quelques secondes |
| `/offres cisco` | les offres d'une entreprise connue | quelques secondes |
| `/offres paris` | mot ou expression entière dans l'entreprise, le titre ou le lieu | quelques secondes |
| `/refresh` | relance une vraie recherche sur tous les sites, puis envoie la liste | ~5 min |
| `/statut` | nombre d'offres et date de la dernière mise à jour | quelques secondes |
| `/status` | santé de chaque entreprise : dernier succès, offres, NOTIFY/REVIEW et erreurs | quelques secondes |

**Comment ça marche.** Le bot sur GitHub Actions tourne toutes les heures :
il ne peut pas écouter Telegram. À chaque passage (toutes les heures), il écrit donc la liste des offres ouvertes
(`current.json`, branche `state`). Un petit **relais gratuit sur Cloudflare Workers**
(`worker/`, ~200 lignes, sans dépendance) reçoit vos commandes en temps réel : `/offres` lit
cette liste (vieille d'1 h 30 au plus) et répond aussitôt ; `/refresh` déclenche le workflow
avec `--send-all`. Le relais ignore tout message qui ne vient pas de `TELEGRAM_CHAT_ID`, et
Telegram doit présenter un secret partagé à chaque appel.

**Installation (une fois)** :

1. Créez un compte gratuit sur [dash.cloudflare.com](https://dash.cloudflare.com/sign-up),
   puis : `cd worker && npx wrangler login`.
2. Créez un *fine-grained token* GitHub limité au dépôt :
   [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)
   → *Repository access : Only select repositories* → `internship-bot` → *Permissions* :
   **Actions : Read and write**, **Contents : Read-only**.
3. Déployez et ajoutez les secrets :
   ```bash
   cd worker
   npx wrangler deploy
   npx wrangler secret put TELEGRAM_BOT_TOKEN
   npx wrangler secret put TELEGRAM_CHAT_ID
   npx wrangler secret put GITHUB_TOKEN        # le token de l'étape 2
   npx wrangler secret put WEBHOOK_SECRET      # une longue chaîne aléatoire
   ```
4. Branchez Telegram sur le relais : ouvrez
   `https://internbot-relay.<votre-sous-domaine>.workers.dev/setup?key=<WEBHOOK_SECRET>`
   (doit afficher `"ok":true`). Le menu des commandes apparaît dans Telegram.

Coût : offre gratuite Cloudflare (100 000 requêtes/jour). `/refresh` consomme ~4 min de
GitHub Actions par appel. Tests : `cd worker && node --test`.

Sans relais, `python -m internbot run --send-all` (ou *Run workflow* avec `args = --send-all`)
envoie aussi la liste complète.

## 6. Ligne de commande

```
python -m internbot [run] [options]

  run                 exécution normale (commande par défaut)
  --dry-run           affiche dans la console ce qui serait envoyé ; n'écrit pas l'état
  --seed              enregistre l'existant sans notifier (re-seed explicite)
  --send-all          envoie aussi la liste de TOUTES les offres ouvertes filtrées
  --test-notify       envoie un message de test Telegram
  --list-companies    liste les entreprises configurées
  --status            santé de chaque entreprise (dernier succès, offres, NOTIFY/REVIEW,
                      erreur, entreprises manuelles) ; lit current.json, aucune requête
  --discover X [Y…]   trouve la plateforme (nom, URL « Apply » ou Nom=URL)
  --discover-file F   idem, une entreprise par ligne (# = commentaire)
  --discover-out F    écrit le YAML trouvé dans F
  --a-noter DOSSIER   exporte le texte des offres ouvertes pas encore notées
                      (DOSSIER/offres.jsonl, reprend là où il s'est arrêté)
  --importer-notes D  applique les notes D/notes*.jsonl à notation/notes.json
  --simulation        avec --importer-notes : vérifie et affiche les verdicts sans écrire
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
5. **Nouvelles offres** → filtre v3 sur le titre → *enrichissement* (Workday : lieux complets et
   date réelle, seulement pour les candidates, max 25 requêtes) → filtre v3 complet (titre + lieu).
6. Les offres `drop` sont marquées vues ; les `review` aussi, et rejoignent la file du résumé
   « à vérifier » (gardée dans l'état) ; les `notify` sont mises en attente.

En fin de run, toutes les offres `notify` sont envoyées (offres IA ⭐ d'abord, individuellement
jusqu'à `group_threshold`, groupées au-delà), puis **seules celles effectivement envoyées** sont
marquées vues. Au premier passage après 9 h (Paris), la file « à vérifier » part en un message
(vidée seulement si l'envoi réussit). L'état est écrit de façon atomique (fichier temporaire + renommage) après chaque entreprise.

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
- Filtre v3 : les métiers visés (software, data, IA, FDE) et les zones sont codés dans
  `filters_v3.py` ; la config ne fait qu'activer / désactiver data, FDE, quant research et les
  zones. Pour un autre profil, adaptez les listes de ce fichier (et ses tests).

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
  remarque, à moindre degré, pour le widget Workable, et pour Apple (offres lues dans les
  données embarquées dans le HTML de la page de recherche).
- Greenhouse, Lever, Ashby et SmartRecruiters exposent des API publiques documentées, a priori
  stables.
- Une offre publiée puis retirée entre deux runs (< 1 h) peut être manquée.
- Les crons GitHub peuvent être retardés : comptez une alerte dans l'heure, pas à la minute.
- La détection repose sur les filtres de titre : une offre de stage dont le titre ne contient
  aucun mot de stage (ex: « Software Engineer, New Grad 2027 ») ne sera pas détectée ; ajustez
  la liste `INTERN` de `filters_v3.py`.
- **Sitemaps** (Intuit, Arm, RTX, Thales, Orange, Engie, Seagate) : le titre et le lieu sont
  reconstruits depuis l'URL, sans date ; les sites Phenom ne mettent pas le lieu dans l'URL, donc
  leurs stages arrivent en REVIEW plutôt qu'en NOTIFY.
- **Endpoints maison** (`custom_json` : Amazon, IBM, Atlassian, AMD, Booking.com, Rivian,
  Schneider ; Eightfold, Oracle HCM, Avature) : non officiels, détectés en cas de changement
  (erreur isolée + alerte après 3 échecs).
- Les entreprises sans accès public stable sont suivies avec le provider `manual` (voir
  « Entreprises suivies à la main »).
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
└── providers/         # registre + Workday, Greenhouse, Lever, Ashby, SmartRecruiters,
                       #   Workable, Eightfold, Oracle HCM, Avature, custom_json, sitemap,
                       #   Apple, manual, playwright_generic
tests/                 # tests unitaires, fixtures dans tests/fixtures/
```
