# STATUS — internship-bot

Source de vérité sur l'avancement. À lire au début de chaque session, à mettre à jour à la fin de chaque action.

Dernière mise à jour : 3 novembre 2026 (tri automatique TF-IDF branché dans le bot + notation des 1 966 offres non notées + Supabase `offres` à jour ; commité et poussé le 3 novembre). Avant : 2 novembre 2026 (recherche sur les faux positifs de `/offres`, rapport `docs/RECHERCHE_FAUX_POSITIFS.md`). Avant : 11 octobre 2026 (fin de la session 6 : notation des offres avec la grille de Matisse, EN PROD, commits `9d11959` et `c0e77de`).

## État actuel (prod)

Le bot **tourne en production** et Matisse reçoit les alertes sur Telegram.

| Élément | État |
|---|---|
| Dépôt | https://github.com/MatisseGrl/internship-bot — **public** |
| Dossier local | `C:\Users\mgarl\Documents\internship-bot` (hors OneDrive, comme aero-rag) |
| Bot Telegram | `@Alertes_stages_matisse_bot` |
| Passage automatique | `.github/workflows/check.yml`, cron `17,47 * * * *` (toutes les 30 min), ~11 min par passage depuis la session 3 (mesuré en local ; ~7 min avant), `timeout-minutes: 20` |
| Mémoire du bot | branche `state` : `state.json` (offres vues, ~13 700) + `current.json` (offres ouvertes filtrées, 502 dont 25 Apple, au 8 oct. 22:51 UTC) |
| Relais Telegram | Cloudflare Worker `internbot-relay` : https://internbot-relay.internbot-relay.workers.dev (webhook branché, menu des commandes installé) |
| Commandes Telegram | `/offres [mots]`, `/refresh`, `/statut`, `/aide` |
| Entreprises surveillées | 89 actives (+ Bosch désactivée), toutes vérifiées en réel (47 ajoutées en session 3, Apple en session 4) |
| Tests | 185 pytest + 13 `node --test` (worker) sur `main` ; 217 pytest + 15 `node --test` sur la branche du filtre v3. ruff + mypy strict verts. CI `tests.yml` sur Python 3.11 / 3.12 / 3.13 |

Secrets en place (noms seulement) :
- GitHub Actions : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Cloudflare (worker) : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GITHUB_TOKEN`, `WEBHOOK_SECRET`

## Fait

### Session 1 (8 octobre 2026) : construction, déploiement, premières évolutions

Session longue, faite avant la règle « une action par session ».

- [x] Projet Python complet : modèles, config validée (pydantic), filtres, état JSON, notifiers Telegram + console, CLI (`run`, `--dry-run`, `--seed`, `--test-notify`, `--list-companies`, `--company`, `-v`).
- [x] Providers : Workday (endpoint non officiel `/wday/cxs/…`), Greenhouse, Lever (US + EU), Ashby, SmartRecruiters, Workable, Playwright générique (optionnel, non testé en réel). Registre automatique : une plateforme = un fichier.
- [x] Salesforce : vrai tenant trouvé et vérifié (`salesforce` / `wd12` / `External_Career_Site`), offre `JR340771` retrouvée.
- [x] Garanties anti-spam : seed silencieux au 1er passage d'une entreprise, clé `(entreprise, id)`, offre marquée vue seulement après envoi réussi, regroupement des messages au-delà de 10 offres, découpage à 4096 caractères.
- [x] Workflow GitHub Actions avec état persisté sur une branche orpheline `state` (pas de boucle de déclenchement, `concurrency`, sauvegarde même en cas d'échec).
- [x] `--discover` : trouve la plateforme d'une entreprise (nom, URL « Apply » ou `Nom=URL`). Workday : `wdN` trouvé via les codes d'erreur (422 = mauvais tenant/wd, 404 = bon tenant, mauvais site), puis noms de site usuels.
- [x] Liste d'entreprises de Matisse passée à `--discover` : 40 trouvées et configurées (voir `config.yaml`).
- [x] Délai de politesse par domaine (plutôt que global).
- [x] Dépôt GitHub créé, commits avec l'adresse masquée de Matisse, permissions du workflow en écriture.
- [x] Telegram : bot créé, secrets en place, diagnostic des secrets dans `--test-notify` (format du token, inversion token/chat_id, `getMe`). Bug rencontré : le token collé ne contenait que les 10 chiffres avant `:` (copie partielle sur téléphone).
- [x] Premier passage (seed) en prod : 40 entreprises, 0 échec, 13 753 offres enregistrées sans notification.
- [x] Dépôt passé en privé (cron 2 h pour tenir dans 2 000 min/mois), puis **repassé en public** (minutes illimitées, cron 30 min). Historique vérifié avant publication : aucun secret ni e-mail perso.
- [x] Nouvelle fonctionnalité : liste complète des offres ouvertes. Chaque passage écrit `current.json` ; `--send-all` envoie la liste ; relais Cloudflare (`worker/`) pour `/offres [mots]` (instantané), `/refresh` (relance un passage `--send-all`), `/statut`. Le relais n'accepte que `TELEGRAM_CHAT_ID` + secret de webhook.
- [x] Filtre : Chine exclue (pays + grandes villes). Une offre multi-lieux n'est écartée que si TOUS ses lieux sont exclus. Les lieux des offres Workday « N Locations » sont récupérés (détail, 25 max par passage et par entreprise) et mis en cache dans `state.json`. Effet : 221 → 185 offres dans `/offres`.
- [x] Projet déplacé dans `C:\Users\mgarl\Documents\internship-bot`, venv recréé. Ajout de `CLAUDE.md` / `AGENTS.md` (règles, dont « une action par session ») et de ce `docs/STATUS.md`.

### Session 2 (8 octobre 2026) : ajout de Cisco

- [x] `/offres cisco` ne renvoyait rien : Cisco n'était pas dans `config.yaml` (pas un bug du relais).
- [x] Ajouté via `--discover` : Workday `cisco` / `wd5` / `Cisco_Careers`. Dry-run : 615 offres lues, 0 échec, nombreux stages SWE/ML/Data qui passent les filtres. Commit `5f59621` poussé sur `main`.
- [x] Passage lancé à la main (21:26 UTC) : seed silencieux de Cisco, 42 offres Cisco dans `current.json` (227 au total). Seules les nouvelles offres Cisco seront notifiées.
- [x] Bug `/offres` : le mot-clé était cherché comme sous-chaîne (« cisco » matchait « San Francisco », 32 offres d'autres entreprises). Désormais chaque mot doit être le début d'un mot de l'offre (« nvid » trouve toujours NVIDIA). Test ajouté, relais redéployé, commit `e410dec`.
- [!] Constat : **le cron de `check.yml` ne s'est encore jamais déclenché** (tous les passages du 8 octobre sont des `workflow_dispatch`). Probablement le délai de GitHub sur un dépôt neuf / passé en public ; à revérifier.

### Session 3 (9 octobre 2026) : 47 entreprises ajoutées

- [x] `--discover-file` sur 70 entreprises (liste de Matisse, Cisco retiré car déjà présent ; Palantir, Anduril, Cloudflare, Robinhood, HRT, Jump passées en `Nom=URL`, indications vérifiées). Durée : ~17 min.
- [x] Résultat brut de discover : 34 trouvées, 36 non trouvées (dont 7 avec tenant Workday trouvé mais site inconnu). Sondes manuelles ciblées ensuite (noms de site Workday usuels, tenants alternatifs, slugs Greenhouse) : 15 de plus trouvées.
- [x] Chaque compte vérifié à la main (nom d'organisation renvoyé par l'API, exemples d'offres) :
  - Workday (12) : Broadcom, Expedia, Intel, Snap (`snapchat`/`snap`), Mastercard, PayPal, Visa, Barclays, BlackRock, Citi (site `2`), Deutsche Bank (`db`), Morgan Stanley (`ms`, organisation « MS Services Group », offres MSIM / Parametric).
  - Greenhouse (27) : Airtable, Anduril, Cloudflare, Instacart, Samsara, Twilio, Vercel, Zscaler, xAI, Block, Brex, Chime, Gusto, Robinhood, Akuna Capital, Bridgewater (`bridgewater89`), DRW (`drweng`), Hudson River Trading (`wehrtyou`), IMC (`imc`), Jane Street, Jump Trading, Optiver (`optiverus` ; le compte `optiver` est vide), Point72, Qube RT, Squarepoint (`squarepointcapital`), Tower Research, XTX Markets (`xtxmarketstechnologies`).
  - Ashby (6) : Linear, Replit, Supabase, Cohere, Plaid, Ramp. Lever (1) : Palantir. SmartRecruiters (1) : ServiceNow.
- [x] Écartées après vérification : Uber (compte SmartRecruiters avec une seule offre « Test UAT »), Qualcomm (Workday `qualcomm`/wd12/`External` existe mais 0 offre), Millennium (Workday `mlp`/wd5/`mlpcareers` existe mais 0 offre), Bank of America (voir « À faire »).
- [x] Durée : premier dry-run complet à **18 min** (1 087 s), trop près du `timeout-minutes: 20` du job (un job coupé avant la sauvegarde de l'état renverrait des offres déjà notifiées). Cause : la recherche plein texte « intern » de Workday ramène des centaines d'« International » chez les banques (Citi : 2 000, le plafond, 153 s pour 0 offre retenue). `search_text: internship` mis pour Citi, Mastercard, Visa, Barclays, Morgan Stanley après vérification qu'aucun titre de stage n'est perdu (pas pour Deutsche Bank : 13 titres perdus). Second dry-run : **11,3 min** (678 s), 440 requêtes au lieu de 660, 0 échec, aucune offre retenue perdue.
- [x] Dry-runs ciblés : Jane Street (Greenhouse, 232 offres, aucun stage publié en ce moment), Citi (Workday), ServiceNow (SmartRecruiters), plus Squarepoint, HRT, Akuna, IMC, Anduril (un ReadTimeout passager au premier dry-run complet, 2 s au test suivant).
- [x] Contrôle des filtres (inchangés) sur de vrais titres : « Quantitative Trader Intern » (IMC, Jump) et « Quantitative Trading Internship » (Optiver) sont bien écartés ; « Software Engineer Intern » passe chez IMC, Akuna, HRT, Squarepoint. Mais voir « À faire » : beaucoup de stages quant passent quand même.
- [x] Dry-run complet : 484 offres passent les filtres (240 pour les 41 anciennes entreprises, 244 pour les 47 nouvelles). Les nouvelles seront enregistrées en silence au premier passage.
- [x] Tests (pytest, ruff, mypy) verts. Commit `ee45ef8` (`config.yaml` seul) poussé sur `main` : en prod au prochain passage, seed silencieux des 47 nouvelles.

### Session 4 (9 octobre 2026) : Apple (et Meta écarté)

- [x] `/offres apple` et `/offres meta` vides : les deux n'étaient pas surveillés (sites maison).
- [x] **Apple** : nouveau provider `apple` (`src/internbot/providers/apple.py`). Pas d'API publique : la page `jobs.apple.com/en-us/search?team=internships-STDNT-INTRN&page=N` embarque les résultats dans `window.__staticRouterHydrationData = JSON.parse("…")` (`loaderData.search` : `searchResults`, `totalRecords`, 20 par page). ID = `id` (ex. `200687446-1731`, propre à chaque publication pays), lien `/en-us/details/{id}/{slug}`. Pas de robots.txt (redirige vers une page 404). 4 tests + 2 fixtures.
- [x] Filtre : ajout de **`internships`** (pluriel) à `title_include` (`config.yaml` et `config.example.yaml`) : Apple publie ses offres US sous « Software Engineering Masters Internships », « Machine Learning and AI Undergrad Internships »… Effet sur Apple : 7 → 25 offres retenues sur 97. Sans risque d'avalanche (les offres déjà vues restent vues). Test sur la vraie config.
- [x] Dry-run Apple : 97 offres, 5 requêtes, 0 échec. README mis à jour (plateformes, tableau, limites). Commit `ca5f33f` poussé, passage lancé à la main (seed silencieux d'Apple).
- [x] **Meta écarté** : `metacareers.com/robots.txt` interdit explicitement la collecte automatisée sans autorisation écrite de Facebook. Règle « respect des sites » : on ne le fait pas. Alternative pour Matisse : alertes e-mail du site Meta Careers.
- Travail en parallèle avec la session 3 (même dossier) : commit limité aux modifs Apple, la session 3 avait déjà committé ses 47 entreprises.

### Session 5 (9 octobre 2026) : filtre v3 (worktree `claude/worktree-simultaneous-sessions-43a75e`, non commité)

- [x] `src/internbot/filters_v3.py` ajouté tel que fourni par Matisse (exclu de `ruff format` pour rester identique, lint OK). Seaux `notify` / `review` / `drop` + priorité IA ⭐.
- [x] `filters.py` : `JobFilter` remplacé par `JobClassifier` = `title_exclude` + `year_hint` de la config, puis filtre v3. Lieu Workday non résolu (« 3 Locations ») -> `review`.
- [x] Config : nouvelles clés `regions`, `include_data`, `include_fde`, `include_quant_research`. Anciennes clés `title_include`, `keywords_any`, `locations_include`, `locations_exclude` ignorées avec un avertissement (une vieille config se charge encore). `config.yaml` / `config.example.yaml` / README mis à jour.
- [x] `notify` -> alerte immédiate, ⭐ et en premier si IA. `review` -> file `review_queue` dans `state.json`, résumé « 🔎 À vérifier » envoyé au premier passage après 9 h (Paris), une ligne par offre (entreprise, titre + lien, lieu, raison), vidé seulement si l'envoi réussit. `drop` -> raison en `-v`. Dépendance `tzdata` ajoutée sous Windows seulement.
- [x] Migration : au premier run COMPLET en v3 (`meta.filter_version` absent), les offres ouvertes déjà vues, jamais notifiées, absentes du `current.json` précédent et classées `notify` sont envoyées UNE fois dans un récap « 🔁 Nouveau filtre » (stocké dans `meta.recap_pending` jusqu'à envoi réussi). Rien d'autre n'est renotifié.
- [x] `current.json` : offres `notify` + `review` avec `status`, `reason`, `priority`. Relais : `/offres` utilise un portage JS exact de `matches_query` (nom d'entreprise connu -> champ entreprise seulement ; sinon mot/expression entière), offres IA ⭐ d'abord.
- [x] Dry-run complet sur une copie de l'état de prod : 89 entreprises, 0 échec, 390 requêtes, ~10 min. 306 `notify` (53 IA ⭐ en comptant les `review`), 179 `review`, 574 stages `drop` (+ ~23 000 non-stages). Récap de migration : 24 offres. Avant : 502 offres dans `/offres` ; après : 485.

### Session 6 (9-11 octobre 2026) : notation des offres avec la grille de Matisse (EN PROD)

- [x] Grille fournie par Matisse (kit de notation v2) recopiée telle quelle dans `notation/GRILLE.md` ; `notation/CONSIGNES.md` explique la notation en série. Poids/seuil du Barème : Fit 45, Éco 20, Pont 20, App 15, seuil 65 ; variantes SF-first et Apprentissage pour le verdict « limite ».
- [x] `notation/entreprises.yaml` : Éco + Pont hors US des 123 entreprises qui ont des offres (recherches web pour les présences US incertaines). Règle Pont : 3 = siège US ou bureau SF/NYC/Seattle, 2 = présence US ailleurs, 1 = aucune ; 5 = stage aux US (offre par offre).
- [x] Export du texte des 2 892 offres de `/offres` (`--a-noter`) : 2 779 lisibles, 113 illisibles (111 IBM anti-bot AWS WAF, 2 RTX HTTP 410) gardées pour tri manuel.
- [x] Notation de chaque offre par sous-agents (63 lots, texte lu en entier), validateur : toute citation absente du texte est refusée. Pilote relu à la main, échantillons vérifiés, passe d'harmonisation (début imposé avant avril -> `dates` ; M2 / dernière année exigés -> `fin_etudes` ; « préparer un Bac+5 » = OK). Corrections dans le dossier de travail (`notes-zz-corrections.jsonl`).
- [x] Résultat dans `notation/notes.json` : 389 retenues, 18 limites, 10 à trancher (Werkstudent / temps partiel), 113 illisibles, 2 362 écartées (seuls les ID sont gardés). `/offres` passe de 2 892 à ~530 offres.
- [x] Runner : offres écartées retirées de `current.json` et du résumé « à vérifier ». Les nouvelles offres (non notées) restent visibles et notifiées comme avant.
- [x] Décisions de Matisse : pas de clé API (nouvelles offres « à noter » en session) ; offres écartées supprimées ; inaccessibles gardées ; BS et MS valides pour les offres US ; aucune exclusion par lieu ; grille publiée dans le dépôt public.
- [x] 313 pytest + 18 node --test, ruff, mypy verts ; CI verte sur `main` ; vérifié en réel (Amazon 78 -> 21, Thales 185 -> 13, Waymo 36 -> 31 sur une copie de l'état).
- [x] Premier passage filtré en prod : `/offres` 3 003 -> 759.
- [x] Décision de Matisse : **aucun poste de recherche** (motif `recherche`, intitulé = preuve ; Research Engineer / Applied Scientist / Data Scientist gardés). 41 offres écartées.
- [x] 256 offres apparues depuis l'export : 57 notées (2 lots), 23 IBM illisibles, le reste écarté par la règle France. Airbus ajoutée à `entreprises.yaml` (Éco 3 « Airbus AI », Pont 3 Acubed).
- [x] Règle « France = Île-de-France seulement » : faite par une session parallèle dans `filters_v3.py` (commits `ef57ec4`, `a1aa4c5`) ; j'ai retiré mon doublon et ajouté les villes manquantes (Lannion, Brest, Colomiers…). Leurs commits cassaient la CI (`ruff format`), corrigé.
- [x] Pages HTML sans charset décodées en UTF-8 (accents « Ã© » dans les textes exportés).
- [x] `/offres` attendu après `c0e77de` : ~487 offres (355 retenues, 20 limites, 10 à trancher, 102 IBM illisibles). 344 pytest verts, CI verte.

### Session du 2 novembre 2026 : point candidatures + /offres sans les offres postulées

- [x] Point mails / candidatures : 65 candidatures dans Supabase (13 refusées, 52 envoyées). Refus Microsoft 200061386 (28/10) et CoreAI 200046156 (30/10) ajoutés (table `mails` + statut `refusee`). Waymo : candidature jamais partie (bug Waymo, mail du 28/10), à refaire par Matisse.
- [x] Projet Supabase relancé (il était en pause pour inactivité).
- [x] `/offres` masque les offres déjà postulées (tous statuts) : le relais lit `candidatures -> offres` dans Supabase. Rapprochement : même entreprise + même identifiant d'offre ; si l'identifiant vient du suivi (`tracker-`, `mail-`, `portail-`), même entreprise + même intitulé (tous lieux). Base injoignable -> liste complète + avertissement. Testé sur le vrai `current.json` : 2 274 -> 2 259 (15 masquées, dont les 2 « Web Engineer Intern » d'Epic Games, lieu de la candidature inconnu). 4 tests ajoutés (22 `node --test` verts), relais redéployé.
- [x] Secret Cloudflare `SUPABASE_URL` en place. **Reste à Matisse** : `SUPABASE_KEY` (clé secrète du projet, Supabase -> Project Settings -> API Keys), à coller lui-même avec `npx wrangler@4 secret put SUPABASE_KEY`. Sans elle, `/offres` marche comme avant.
- Refus de l'outil : créer une fonction SQL lisible avec la clé publique (accès « anon ») a été refusé ; on passe par la clé secrète, rangée dans Cloudflare comme les autres secrets.
- Non commité (`worker/src/index.js`, `worker/test/index.test.mjs`, `worker/wrangler.toml`, ce fichier).

## Session du 2-3 novembre 2026 : tri automatique + notation + Supabase

- [x] Choix de Matisse après le test des pistes : **TF-IDF dans le bot + juge LLM (grille) en session**, et mise à jour de `notes.json` et de Supabase.
- [x] **Tri automatique** (`src/internbot/tri.py`, modèle `notation/tri_tfidf.json.gz`, 1,1 Mo) : TF-IDF mots 1-2 + caractères 3-5 + régression logistique, appris sur les 2 842 offres notées (393 pertinentes), seuil hors pli −1,441 (94 % des pertinentes gardées, 30 % des offres affichées). Calcul sans scikit-learn, identique à scikit-learn (écart max 6e-6 sur 400 vraies offres, 0 décision différente). Le runner trie toute offre `notify`/`review` **non notée** : nouvelle offre sous le seuil = ni notification ni `/offres` (marquée vue) ; texte illisible = gardée ; score en cache dans `state.json` (`tri`) ; anciennes offres triées au fil des runs (60 par run, nouvelles 200). La grille prime toujours. 12 tests (`tests/test_tri.py`). Dry-run réel : une offre Amazon « Hardware Development Engineer Intern, Winter 2027 » masquée.
- [x] **Notation** des 1 966 offres non notées (`--a-noter`, 58 illisibles) : 1 512 écartées par le tri (`ecartees`, `motif: tri_auto`, score + version du modèle), 41 pages supprimées (HTTP 410 / Greenhouse « Job not found ») écartées `motif: fermee`, les 396 gardées par le tri notées avec la grille par 12 sous-agents (validateur : 0 erreur) : 122 retenues, 16 limites, 13 à trancher, 245 écartées. Harmonisation : contrats `PART_TIME` (Intel Gdansk/Munich, ASML San Diego) = `stage: false`. 9 entreprises ajoutées à `entreprises.yaml` (ArianeGroup, Booking.com, Duolingo, Nintendo, Pigment, ServiceNow, Snap, Unity, Visa).
- [x] **`/offres` attendu après push : 484 offres** (377 retenues, 26 limites, 20 à trancher, 61 illisibles) au lieu de 2 274.
- [x] **Supabase** : table `offres` seulement mise à jour (5 433 lignes, upsert par `cle`, 484 `dans_snapshot`). **`candidatures` et `mails` non touchées** : elles sont maintenant écrites directement dans Supabase (65 et 76 lignes, plus récentes que le registre local à 37 et 63). C'est pour ça que l'ancien `sync_supabase.py` échoue depuis le 17 oct. (« comptes divergents ») ; le relancer écraserait des statuts récents. Script utilisé : `maj_supabase_offres.py` + lanceur DPAPI, archivés dans `C:\Users\mgarl\Documents\internship-bot-archives\notation-2026-11-02\`.
- [x] **Commit + push sur `main`** (3 novembre, demandé par Matisse) : tout le dossier de travail, plus les 3 commits locaux d'octobre (export des textes, règles d'accès, `SITES_BLOQUES.md`) et la fusion des 10 commits d'`origin/main` (agent local, SWElist, Supabase). Lint `agent_local` corrigé (la CI Tests était rouge depuis le 16 oct.). Le tri part en prod au prochain passage.
- [x] `docs/Regles_pour_sites_bloqués.md` (écrit par une autre session) **non poussé, sur décision de Matisse** : il affirme que le bot « contourne tous les CAPTCHA » et que Meta autorise « toute collecte », ce qui est faux. Il reste sur le PC (ignoré via `.git/info/exclude`) ; `docs/SITES_BLOQUES.md` restauré, `test_docs` vert.
- [ ] Relais : les modifs de `worker/` (autre session) sont poussées mais **pas redéployées** (`cd worker && npx wrangler@4 deploy`).
- [ ] À relire par Matisse (hésitations des agents) : offres Dassault Systèmes au texte tronqué (JSON-LD coupé après 1-2 phrases, notées « non précisé » : Munich AI Development, Ingénieur IA ML NLP, Werkstudent AI Agents) ; Siemens Agentic AI (« 6-month internship starts from January 2027 », exclue `dates`) ; Samsara London (candidatures closes le 30 oct., exclue `fermee`) ; offres « Visa sponsorship is not available » (Nintendo, EA, TI, Visa, Siemens) gardées car le J-1 n'est pas exclu explicitement ; Thales « Votre priorité est de réaliser un stage de fin d'études » gardées éligibles.
- [ ] Le registre local de l'agent (SQLite Codex) et `quotidien.py` ne sont plus alignés sur Supabase : décider qui est la source de vérité des candidatures avant de relancer `Lancer quotidien.ps1`.

## À faire ensuite

- [ ] **Supabase ne suit plus le bot** : tables `offres` / `classement` figées au 16-21/10 (4 123 offres) alors que `/offres` en affiche 2 274 aujourd'hui. Matisse veut une mise à jour : resynchro manuelle ou écriture automatique par le bot à chaque passage (session dédiée). Les nouvelles candidatures doivent aussi y être ajoutées pour que `/offres` les masque.
- [ ] **Cadence du cron** : GitHub lance `check.yml` toutes les 4 à 7 h (au lieu de 30 min) et chaque passage dure ~31 min (contre ~11 min avant) : à regarder.

- [ ] **Faux positifs de `/offres` (2 274 offres au 2 nov. 2026)** : lire [`docs/RECHERCHE_FAUX_POSITIFS.md`](RECHERCHE_FAUX_POSITIFS.md) (recherche du 2 nov. : ce que font Simplify et les autres, ce qui a déjà été essayé ici, dont le Tri ML). Constat : 1 554 offres sont des `review` (surtout Thales/Orange/Engie lus par sitemap, sans lieu, titres français non reconnus) et 1 952 n'ont jamais été notées. Pistes classées : 1) règles (masquer les `review` de `/offres`, mots français, lieu des offres sitemap, Werkstudent à trancher) ; 2) critères lus dans le texte (éligibilité, saison, offres fermées) ; 3) grille par LLM, contraire à la décision « pas de clé API ». **Testé le 2 nov.** sur 1 192 offres notées (découpage par entreprise, section « Test des pistes » du rapport) : juge LLM le plus performant (rappel 97 %, précision ~80 %, MCC 0,86, mais avantagé car les étiquettes viennent du même juge) ; sans LLM, modèle TF-IDF sur le texte (rappel 97 %, 40 % affichées, MCC 0,48) ; règles seules = 1 bonne offre perdue sur 6 ; embeddings faibles (AUC 0,73). Scripts et résultats d'essai hors dépôt, dans `C:\Users\mgarl\Documents\internship-bot-archives\test-faux-positifs-2026-11-02\` (non branchés au bot ; le venv ML n'y est pas : `pip install numpy scikit-learn fastembed`). À choisir par Matisse, une piste par session.
- [ ] **Filtre v3 : mise en prod** (à faire par Matisse ou sur sa demande) : relire le diff, commit + push sur `main`, puis `cd worker && npx wrangler@4 deploy` pour le nouveau `/offres`. Le premier passage complet enverra le récap (24 offres environ, 2 messages Telegram à cause de la limite de 4 096 caractères).
- [ ] **Filtre v3 : listes à ajuster (à trancher par Matisse)**, vu au dry-run :
  - lieux manquants -> vrais stages tech écartés « hors zone » : Barclays Glasgow, Knutsford, Northampton, « Canary Wharf » (Londres), Whippany (NJ) ; Palantir FDE « Honolulu, HI » ; Cloudflare « In-Office » (3 stages SWE ; à mettre dans `UNKNOWN_LOC` -> review). Ajouter `glasgow`, `knutsford`, `northampton`, `canary wharf`, `whippany`, `hi`/`hawaii`, `fl`, `in office`.
  - « stage » (mot de stage FR) matche l'anglais « Stage Systems » / « Stage 0 » chez SpaceX : 1 faux `notify` (« Propulsion Engineer, Stage Systems »), 2 faux `review` (soudeurs).
  - « Operations Research Engineer Intern » (Intel) écarté par `operations` (non-tech) alors que `operations research` est dans DATA.
  - « Quant Performance Engineer Intern » (IMC) écarté par `performance engineer` (hardware) alors que c'est un poste dev.
  - « Quantitative Researcher - Intern » (Point72) en `review` (« researcher » absent de QUANT).
  - « Internal Audit Analytics Intern », « People Analytics Intern » (Coinbase) en `notify` via « analytics » malgré le non-tech.
  - `engineer (générique)` notifie des postes mécaniques chez Anduril (Warhead, Propulsion, Harness).
  - 154 `review` « titre ambigu », souvent non-tech (« Account Development Representative », « Global Markets Intern ») : le résumé quotidien risque d'être bruyant.
- [ ] `/offres` : la recherche ne fait plus de préfixe (« nvid » ne trouve plus NVIDIA) et une requête de plusieurs mots est cherchée comme une expression (« stripe london » ne trouve rien, « machine learning » oui). Voulu par la spec v3 ; à revoir si gênant.
- [ ] Une fois le v3 en prod et le récap envoyé : le code de migration (`_migration_candidates`, `recap_pending`) pourra être retiré.

- [ ] **Noter les nouvelles offres** (pas de clé API) : dans une session, `python -m internbot --a-noter travail/ --state .state/state.json`, noter selon `notation/CONSIGNES.md`, `--importer-notes travail/ --simulation` puis sans `--simulation`, commit de `notation/notes.json`. Ajouter à `entreprises.yaml` toute entreprise sans note (l'import le signale).
- [ ] **Offres à vérifier par Matisse** (gardées) : 18 « limite », 10 « à trancher » ; Palo Alto Networks SWE (annonce de janvier 2026, saison 2026 probable) ; offres « Winter 2027 » sans dates (Cloudflare, Vercel, Cohere, Robinhood, Capital One) ; Palantir (habilitation US « appréciée », annonces anciennes) ; AMD Calgary (12 mois imposés) ; Microsoft Research Audio, Czech/Prague, Londres (annonces sans missions) ; 13 retenues à Fit 2 (front-end/mobile en grosse boîte US, passent à 66 par la grille).
- [ ] Rivian « Applied AI Co-op » (US, Fit 5) exclue car présence imposée janvier-août 2027 : à voir si Matisse peut négocier.
- [ ] IBM : 111 offres illisibles (anti-bot), gardées ; à trier à la main.

Une action par session. Par ordre de priorité suggéré :

- [ ] Vérifier que le cron tourne (`gh run list -R MatisseGrl/internship-bot -w check.yml` : des lignes `schedule` doivent apparaître). Si toujours rien le 9 octobre : désactiver puis réactiver le workflow (*Actions → Check internships → … → Disable / Enable*), ou pousser un petit changement de `check.yml`.

- [ ] Vérifier que les 9 offres NVIDIA encore affichées « 2 Locations » ont bien été résolues après quelques passages (`/offres nvidia`).
- [ ] Filtres de lieu : demander à Matisse ce qu'il veut (France seulement ? Europe ? remote ? US ?). Aujourd'hui : monde entier sauf Chine.
- [ ] Exclure ou non les stages PhD (`phd` dans `title_exclude`) : NVIDIA en publie beaucoup.
- [ ] Taïwan et Hong Kong : exclus ou non (pas exclus aujourd'hui).
- [ ] **Filtres et stages quant (à trancher par Matisse)** : avec les filtres actuels, ~20 « Quantitative Research Intern » passent (DRW, IMC, Optiver, Point72, Akuna, Tower, via le mot « research »), ainsi que « Algorithm Development (Quant Research & Trading) Internship » (HRT) et « Internship, Quantitative Research and Trading » (QRT). Pour les écarter : ajouter `quant`, `quantitative`, `trader` à `title_exclude` (pas `trading` : écarterait « Software Engineer Intern - Trading Systems »). Attention, ça écarterait aussi « Quantitative Developer Intern » (Tower), « Quant Performance Engineer Intern » (IMC), « Quantitative Software Developer Intern » (Point72), qui sont des postes de dev.
- [ ] **Banques et « Summer Analyst » (à trancher)** : leurs stages tech s'appellent « Technology Summer Analyst – Software Engineering », sans « intern », donc rejetés aujourd'hui. Ajouter `summer analyst` à `title_include` les ferait passer (le titre doit aussi contenir un mot de `keywords_any`, donc « Investment Banking Summer Analyst » reste écarté). Sinon, Barclays, BlackRock, Citi, Deutsche Bank, Morgan Stanley n'apporteront presque rien (11 offres aujourd'hui).
- [ ] **Bank of America (à trancher)** : trouvée sur Workday `ghr` / wd1 / `Lateral-US` (1 976 offres), mais ce site ne contient que des postes expérimentés (recherche « internship » : 9 résultats, aucun stage). Les stages passent a priori par campus.bankofamerica.com. Non ajoutée : ~50 pages par passage pour rien.
- [ ] xAI (organisation « SpaceXAI ») et SpaceX publient 6 annonces identiques (ex. « Spring 2027 Software Engineering Internship/Co-op ») avec des ID différents : possible double notification. Mineur.
- [ ] Durée d'un passage (~11 min) : à surveiller en prod (`gh run list -R MatisseGrl/internship-bot -w check.yml`). Si elle approche 20 min, relever `timeout-minutes` dans `check.yml` ou réduire `max_pages` des gros Workday.
- [ ] Entreprises introuvables en session 3 (aucune plateforme supportée ; raisons probables, non vérifiées une par une) :
  - Oracle HCM : Oracle, JPMorgan Chase.
  - SuccessFactors : SAP.
  - Avature / gr8people : Electronic Arts (jobs.ea.com, ea.gr8people.com), Bloomberg (tenant Workday `bloomberg` sur wd1 existant mais aucun site trouvé), IBM.
  - Eightfold : Qualcomm (careers.qualcomm.com ; le Workday trouvé est vide).
  - ATS propre : Rippling (Rippling ATS), Uber (site maison).
  - Site carrières maison : Atlassian, Intuit, American Express, Citadel, Citadel Securities, Two Sigma, D. E. Shaw, Susquehanna (SIG), Goldman Sachs, BNP Paribas, Société Générale, UBS.
  - Millennium : Workday `mlp`/wd5 existe mais site `mlpcareers` vide, vrai site inconnu.
  - Pour chacune : trouver l'URL « Apply » d'une offre et retenter `--discover "Nom=URL"` ; sinon un provider dédié (Oracle HCM, Eightfold, Avature) serait à étudier dans une session à part.
- [ ] Ajouter les entreprises non trouvées automatiquement, avec l'URL de leur page « Apply » (`--discover "Nom=URL"`) : Palo Alto Networks (tenant `paloaltonetworks` sur `wd5`, seul le nom du site manque), Dell, NetApp, Texas Instruments, DoorDash, Shopify, Mistral AI (compte Lever vide).
- [ ] Ajouter `.claude/worktrees/` au `.gitignore` (l'app Claude y range les worktrees des sessions parallèles ; un `git add .` les embarquerait).
- [ ] Providers dédiés pour Amazon (`amazon.jobs/en/search.json`) et Microsoft (`gcsservices.careers.microsoft.com`) : non officiels, à étudier.
- [ ] Logos non identifiés sur la capture de Matisse (SMC, cube gris, arc bleu, logo en F) : attendre leurs noms.
- [ ] Commit + push de `CLAUDE.md`, `AGENTS.md`, `docs/STATUS.md` (pas encore fait : à valider par Matisse).

## Décisions

- **Filtre v3** (session 5) : les listes de mots-clés vivent dans `filters_v3.py` (code fourni par Matisse, gardé tel quel), la config ne garde que des interrupteurs (zones, data, FDE, quant) + `title_exclude` / `year_hint`. Résumé « à vérifier » quotidien plutôt qu'une commande `/review` : rien à ajouter au relais, et l'état (`state.json`) sert déjà de file d'attente.
- **Migration v3 sans l'ancien filtre** : « auparavant filtrée » = absente du `current.json` écrit par l'ancien filtre. L'ancien `JobFilter` a donc pu être retiré tout de suite.

- **Telegram en HTML** (pas MarkdownV2) : échappement plus simple et plus robuste.
- **État en JSON trié sur une branche `state`** plutôt que SQLite ou `actions/cache` : diffs lisibles, durable (un cache est évincé après 7 jours, ce qui provoquerait un re-seed et des offres manquées), aucune donnée qui change à chaque run dans `state.json`.
- **Les offres qui ne passent pas les filtres sont marquées vues** : élargir les filtres plus tard ne déclenche pas d'avalanche d'anciennes offres (seules les futures sont notifiées).
- **Lieu inconnu ou partiel = gardé** (mieux vaut une alerte de trop qu'une offre manquée).
- **Workday** : `search_text: intern` (pré-filtre plein texte côté Workday, filtrage fin côté bot), `max_pages: 100`, ID stable = numéro de réquisition (`JR…`), lien canonique sans locale.
- **Workday, `search_text: internship`** pour Citi, Mastercard, Visa, Barclays, Morgan Stanley (session 3) : « intern » y ramène surtout des « International » (jusqu'au plafond de 2 000). Vérifié sans perte de titre de stage ; à revérifier si une de ces entreprises semble ne jamais rien envoyer. Pas pour Deutsche Bank (perte constatée).
- **Dépôt public** : minutes Actions illimitées, cron 30 min. Matisse accepte que la liste d'entreprises et les offres soient visibles (projet portfolio).
- **Relais Cloudflare pour les commandes Telegram** (option « réponse immédiate ») plutôt que lire les commandes au passage suivant : réponse en quelques secondes, quasi gratuit.
- **`/offres` lit `current.json`** (vieux de 30 min max) ; `/refresh` lance une vraie recherche (~5 min).
- **Clé GitHub du relais** : token limité au dépôt (Actions read/write, Contents read). La génération du fine-grained token a buggé côté GitHub plusieurs fois ; type et date d'expiration du token finalement créé à confirmer avec Matisse.
- Code, commentaires et commits **en français** (convention en place depuis le début, contrairement à aero-rag où le code est en anglais).
- Les commits existants portent une ligne `Co-Authored-By: Claude` (faits avant la règle). Ne pas réécrire l'historique (dépôt public, force-push) ; la règle s'applique à partir de maintenant.

## Questions ouvertes

- Filtres de lieu, PhD, Taïwan/Hong Kong (voir « À faire »).
- Expiration du `GITHUB_TOKEN` du relais : quel type de token (fine-grained ou classique) et quelle date ? À l'expiration, `/offres` et `/refresh` répondront « GITHUB_TOKEN invalide » : il faudra en recréer un et refaire `npx wrangler@4 secret put GITHUB_TOKEN` dans `worker/`.
- Student Developer Pack : demandé ? Plus nécessaire pour le bot (dépôt public), utile pour d'autres outils.

## Notes

- GitHub désactive les workflows planifiés d'un dépôt public après 60 jours sans activité : e-mail d'avertissement, puis *Actions → Check internships → Enable workflow*.
- Les crons GitHub peuvent être retardés de 5 à 30 min.
- Workday : la pagination n'est pas stable quand des offres sont publiées pendant le parcours (totaux qui varient de quelques unités d'un passage à l'autre). Sans danger : une offre « disparue » qui revient n'est pas re-notifiée, une offre sautée est rattrapée au passage suivant.
- Workday renvoie parfois une fiche vide (seulement l'ID) : ignorée, log en debug.
- Telegram répond 404 « Not Found » quand le token est faux ou incomplet (pas 401).
- `state.json` fait ~2 Mo : l'API `contents` de GitHub ne renvoie pas son contenu en JSON, utiliser `Accept: application/vnd.github.raw`.
- Commandes utiles côté Matisse : voir README, sections 5 et 5 bis.
