# Sites bloqués ou non surveillés

**Document unique** : tout site que le bot ne lit pas, ou pas en entier, est listé ici, quel que
soit le type de blocage. Le reste de la doc renvoie ici.

Règle du projet : le bot ne contourne aucun CAPTCHA ni aucune protection anti-bot. Une page
bloquée donne une erreur, et l'offre ou l'entreprise est suivie à la main.

Dernière vérification : 15 octobre 2026 (`config.yaml` : 216 entreprises, dont 190 automatiques
et 26 suivies à la main ; `notation/notes.json` : 126 offres illisibles).

## Résumé

| Type | Ce que ça veut dire | Combien |
|---|---|---|
| [1. Interdit par le site (robots.txt)](#1-interdit-par-le-site-robotstxt) | le site demande aux robots de ne pas lire ses offres | 9 entreprises |
| [2. Protection anti-bot](#2-protection-anti-bot) | le site renvoie « accès refusé » (HTTP 403) aux robots | 4 entreprises |
| [3. Conditions d'utilisation](#3-conditions-dutilisation) | lecture automatique interdite par les CGU | 1 entreprise |
| [4. Pas de source exploitable](#4-pas-de-source-exploitable) | liste chargée en JavaScript, pas d'API publique ni d'ATS connu | 10 entreprises |
| [5. Déjà couvertes ailleurs](#5-déjà-couvertes-ailleurs) | pas bloquées : leurs offres arrivent par une autre entreprise | 2 entreprises |
| [6. Liste lue, texte des offres bloqué](#6-liste-lue-texte-des-offres-bloqué) | le bot voit l'offre mais ne peut pas lire l'annonce | 126 offres (IBM, RTX) |
| [7. Accès partiel, passage par le sitemap](#7-accès-partiel-passage-par-le-sitemap) | une partie du site est interdite, le bot lit le sitemap autorisé | 4 entreprises |
| [8. Pas encore trouvées](#8-pas-encore-trouvées) | aucune source trouvée pour l'instant, pas dans `config.yaml` | 16 entreprises |

Les types 1 à 5 sont les entreprises `provider: manual` de `config.yaml` : aucune requête, elles
apparaissent dans `--status` et `/status` avec leur raison.

## 1. Interdit par le site (robots.txt)

`robots.txt` est le fichier où un site dit aux robots ce qu'ils ont le droit de lire. Ici, le
site l'interdit pour ses offres.

| Entreprise | Ce qui est interdit | Que faire |
|---|---|---|
| [Google](https://www.google.com/about/careers/applications/jobs/results?q=intern) | `/about/careers/applications/jobs/results` | Bouton « Get job alerts » sur la page de résultats (compte Google) |
| [Meta](https://www.metacareers.com/jobs?q=intern) | toute collecte sans autorisation écrite (metacareers.com) | « Create job alert » sur metacareers.com (profil candidat) |
| [ByteDance](https://jobs.bytedance.com/en/position?keywords=intern) | tout lifeattiktok.com ; en plus, l'API jobs.bytedance.com exige un jeton de session ; compte SmartRecruiters « Bytedance » abandonné | Alerte e-mail du site (compte candidat) ; voir aussi https://lifeattiktok.com/search?keyword=intern |
| [Valve](https://www.valvesoftware.com/en/jobs) | `/jobs` | Vérification manuelle mensuelle (Valve publie rarement des stages) |
| [Shopify](https://www.shopify.com/careers/search?keywords=intern) | tout shopify.com (`Disallow: /`) ; Workday « shopify » non public | Page https://internships.shopify.com (inscription aux annonces de la prochaine promo) |
| [Walmart Global Tech](https://careers.walmart.com/results?q=intern) | `/api` et `/results` ; le sitemap ne donne que des ID sans titre | « Job Alerts » sur careers.walmart.com |
| [Eviden](https://eviden.com/careers/) | `/api/` (source de la liste d'offres) | Alerte e-mail sur le portail carrières Eviden |
| [OVHcloud](https://careers.ovhcloud.com/fr/) | tout careers.ovhcloud.com (`Disallow: /`) | Alerte e-mail SuccessFactors (« Recevez les offres par e-mail ») |
| [Renault](https://www.renaultgroup.com/carrieres/nos-offres/) | `/api/` (source de la liste d'offres) | Alerte e-mail depuis l'espace candidat Renault Group |

## 2. Protection anti-bot

| Entreprise | Blocage | Que faire |
|---|---|---|
| [Tesla](https://www.tesla.com/careers/search/?query=intern) | Akamai, HTTP 403 « Access Denied » | Pas d'alerte e-mail publique : vérification manuelle hebdomadaire |
| [Akamai](https://www.akamai.com/careers) | HTTP 403 ; Workday non public | Alerte d'emploi du portail carrières (compte candidat) |
| [Safran](https://www.safran-group.com/fr/offres) | HTTP 403 sur safran-group.com | Compte candidat + « alerte emploi » (mot-clé stage) |
| [EDF](https://www.edf.fr/edf-recrute/offres) | HTTP 403 | Alerte (mot-clé stage) depuis l'espace candidat EDF Recrute |

## 3. Conditions d'utilisation

| Entreprise | Blocage | Que faire |
|---|---|---|
| [LinkedIn](https://www.linkedin.com/jobs/search/?keywords=intern&f_C=1337) | offres publiées uniquement sur linkedin.com, dont les CGU interdisent la lecture automatique ; le compte Lever « linkedin » est un bac à sable de test | Alerte d'emploi LinkedIn (bouton « Créer une alerte » sur cette recherche) |

## 4. Pas de source exploitable

Pas d'interdiction ici : le site affiche ses offres en JavaScript via une API non documentée, et
aucun ATS public (Workday, Greenhouse, Lever…) n'a été trouvé. Piste possible pour chacune : un
provider dédié qui appelle la même API que la page, s'il n'y a ni interdiction robots.txt ni
anti-bot.

| Entreprise | Détail | Que faire |
|---|---|---|
| [SAP](https://jobs.sap.com/search/?q=intern) | site Next.js, offres chargées côté navigateur | « Job alerts » / Talent Community sur jobs.sap.com |
| [HubSpot](https://www.hubspot.com/careers/jobs?q=intern) | API non documentée ; Workday « hubspot » non public (HTTP 401) | « Join our Talent Network » sur hubspot.com/careers |
| [Wayfair](https://www.wayfair.com/careers/jobs) | Workday « wayfair » non public (HTTP 401) ; compte SmartRecruiters avec 1 seule offre | « Job alerts » sur la page carrières Wayfair |
| [Naval Group](https://www.naval-group.com/en/candidates) | aucune API ni ATS public trouvé | Alerte e-mail depuis l'espace candidat |
| [Capgemini](https://www.capgemini.com/fr-fr/carrieres/rejoignez-nous/nos-offres-demploi/) | API non documentée ; pas de sitemap d'offres | « Créer une alerte » sur la page des offres |
| [Amadeus](https://jobs.amadeus.com/) | sitemap vide, aucun ATS public trouvé | « Job alert » sur jobs.amadeus.com |
| [Klarna](https://www.klarna.com/careers/) | aucun ATS public (Greenhouse, Ashby, Lever, Workday testés) | Alerte e-mail sur klarna.com/careers |
| [Nokia](https://jobs.nokia.com/) | les endpoints Oracle HCM supposés répondent 404 | « Job alerts » sur jobs.nokia.com |
| [DeepSeek](https://www.deepseek.com/) | pas d'ATS public (recrutement via plateformes chinoises) ; postes en Chine, exclue par les filtres | Rien à faire tant que la Chine est exclue |
| [Moonshot AI](https://www.moonshot.cn/) | pas d'ATS public ; le compte Workable « moonshot » est une autre entreprise ; postes en Chine | Rien à faire tant que la Chine est exclue |

## 5. Déjà couvertes ailleurs

| Entreprise | Pourquoi | Que faire |
|---|---|---|
| [X](https://x.ai/careers) | careers.x.com redirige vers x.ai/careers, déjà suivi via xAI (Greenhouse « xai ») | Rien |
| [Splunk](https://cisco.wd5.myworkdayjobs.com/Cisco_Careers?q=splunk) | filiale de Cisco, offres publiées sur le Workday de Cisco, déjà surveillé | Rien |

## 6. Liste lue, texte des offres bloqué

Le bot trouve ces offres (elles sont dans `/offres`), mais la page de l'annonce ne se lit pas.
Elles ont le statut `illisible` dans `notation/notes.json` et restent visibles, à trier à la main.
Le même cas donne une ligne `erreur` dans `--a-noter` et `--exporter-textes`.

| Entreprise | Offres | Blocage | Que faire |
|---|---|---|---|
| IBM | 124 | page `careers.ibm.com/careers/JobDetail` protégée (anti-bot AWS WAF) : 0 caractère lisible | Ouvrir le lien dans un navigateur et lire l'annonce |
| RTX | 2 | HTTP 410 : offre retirée du site | Rien : l'offre n'existe plus |

## 7. Accès partiel, passage par le sitemap

La page de recherche est interdite aux robots par robots.txt, mais le sitemap (publié pour les
robots, et autorisé) liste toutes les offres. Le bot lit donc le sitemap (`provider: sitemap`).
Ces entreprises sont surveillées normalement.

| Plateforme | Partie interdite | Entreprises |
|---|---|---|
| Radancy / TalentBrew | `/search-jobs/` | Intuit, Arm |
| SuccessFactors (RMK) | `/services/` | Engie, Seagate |

## 8. Pas encore trouvées

Absentes de `config.yaml` : aucune source supportée trouvée pour l'instant (site maison ou
plateforme non supportée). Pour en ajouter une, trouvez l'URL « Apply » d'une offre et lancez
`python -m internbot --discover "Nom=URL"`.

| Entreprise | Ce qu'on sait |
|---|---|
| Bank of America | Workday `ghr` / wd1 / `Lateral-US` trouvé, mais seulement des postes expérimentés (aucun stage le 9 oct. 2026) ; les stages passent a priori par campus.bankofamerica.com |
| Millennium | Workday `mlp` / wd5 existe, mais le site `mlpcareers` est vide ; vrai site inconnu |
| Bloomberg | tenant Workday `bloomberg` (wd1) existant, aucun site trouvé |
| Electronic Arts | jobs.ea.com / ea.gr8people.com (Avature / gr8people, non supporté) |
| Rippling | ATS maison (Rippling ATS) |
| JPMorgan Chase | Oracle HCM, tenant non trouvé |
| American Express, Citadel, Citadel Securities, Two Sigma, D. E. Shaw, Susquehanna (SIG), Goldman Sachs, BNP Paribas, Société Générale, UBS | site carrières maison |

## Mettre ce document à jour

- Nouvelle entreprise suivie à la main : l'ajouter dans `config.yaml` (`provider: manual`, avec
  `careers_url`, `reason`, `alert`) **et** dans la bonne section ici. Un test
  (`tests/test_docs.py`) échoue si une entreprise `manual` de `config.yaml` manque ici.
- Entreprise de la section 8 ajoutée à `config.yaml` : la retirer d'ici.
- Offres illisibles : recompter avec le statut `illisible` de `notation/notes.json`.
