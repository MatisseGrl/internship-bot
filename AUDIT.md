# Audit factuel d'internbot (15 octobre 2026)

Constaté dans le code, `notation/` et les fichiers de travail retrouvés. Ce qui n'est pas vérifiable
est marqué **inconnu**.

## Correction importante

Les notes des 2 460 offres écartées **ne sont pas perdues**. Les fichiers de travail des sessions
de notation du 9 au 11 octobre étaient restés dans le dossier temporaire de Claude Code. Ils ont été
copiés dans `C:\Users\mgarl\Documents\internship-bot-archives\notation-brute-2026-10\` (71 Mo,
hors dépôt) :

- 69 fichiers `notes*.jsonl` : 2 905 lignes, soit 2 870 offres distinctes. Chaque offre a ses
  notes, ses citations et ses conditions, ou bien son motif d'inéligibilité et sa preuve ;
- `offres.jsonl` : le **texte complet** de 3 172 offres, tel qu'il a été noté ;
- les consignes données aux agents de notation (`prompt_agent.md`, `prompts/`) et les scripts
  d'harmonisation.

Couverture : **2 460 / 2 460** offres écartées ont leur note brute **et** leur texte.

## 1. Profil et stages recherchés (source : `notation/GRILLE.md`)

- 4e année à l'ECE Paris (majeure Data & IA), diplôme en juin 2028. Citoyen européen, J-1
  possible via Intrax.
- Stage de 12 à 18 semaines entre avril/mai et août 2027.
- Métiers visés : Applied AI / ML Engineer, Applied Scientist, FDE, SWE (en priorité dans une
  équipe IA), Data Scientist orienté modélisation.
- Objectif de la grille : un stage **qui mène à San Francisco** (master US puis OPT). Ce n'est
  pas « beaucoup de candidatures ». La grille est sélective par conception : 362 offres retenues
  sur environ 3 000.
- Décision du 11 octobre 2026 : aucun poste de recherche.
- France : Île-de-France uniquement (filtre de lieu).

## 2. Bot Telegram et collecte

- 216 entreprises dans `config.yaml` : 190 automatiques et 26 `manual` (Google, Meta, LinkedIn,
  Tesla, SAP, ByteDance…, sans collecte possible proprement).
- Plateformes : Greenhouse 69, Workday 44, Ashby 23, Eightfold 10, Lever 9, SmartRecruiters 7,
  sitemaps 7, Oracle HCM 5, JSON maison 7, Avature 3, RSS 2, Apple, Workable, Gestmax, Exalead.
- GitHub Actions toutes les heures (cron `17 * * * *`). Un passage dure environ 35 min, avec un
  timeout de 50 min.
- Données conservées dans `state.json` (branche `state`) : entreprise, id, titre, lieu, URL,
  date. **Pas le texte des annonces** : il est relu à la demande (`descriptions.py`) au moment
  de la notation.
- Filtre v3 sur le titre et le lieu (mots-clés, `filters_v3.py`), puis verdicts de
  `notes.json`.
- Limites connues : un stage dont le titre ne contient aucun mot de stage est manqué ; une offre
  publiée et retirée en moins d'une heure peut être manquée ; les endpoints Workday et JSON maison
  ne sont pas officiels.

## 3. Système de notation actuel

**Les « quatre notes de Claude » ne sont pas quatre notes par offre** :

| Critère | Poids | Qui le note |
|---|---|---|
| Fit rôle | 45 | Claude, **par offre**, citation obligatoire |
| Apprentissage | 15 | Claude, **par offre**, citation ou « non précisé » (3 au maximum dans ce cas) |
| Écosystème SF | 20 | **une fois par entreprise** (`entreprises.yaml`) |
| Pont vers SF | 20 | par entreprise ; 5 automatiquement si le lieu est aux US |

Avant ces notes, il y a un **filtre d'éligibilité binaire** (motif + citation).

Score = (Fit×45 + Éco×20 + Pont×20 + App×15) / 5, seuil 65. Une offre est « limite » si elle
passe avec l'un des deux autres jeux de poids.

Comment la notation a été faite : en sessions Claude Code, avec **environ 63 lots notés par des
agents indépendants** (un lot ≈ 45 offres). Aucun modèle n'est appelé par le bot. L'import vérifie
que chaque citation existe mot pour mot dans le texte. Il ne vérifie pas que l'interprétation est
juste.

### Les 519 offres gardées

362 retenues, 21 limites, 10 à trancher (pas un stage), **126 illisibles** (texte inaccessible,
jamais notées). Fit des offres notées : 5 → 92, 4 → 199, 3 → 87, 2 → 15.

### Les 2 460 offres écartées (recalculées depuis les notes brutes)

**1 255 (51 %) sont écartées pour inéligibilité**, pas pour leur qualité :

| Motif | Offres |
|---|---|
| fin d'études (dernière année / M2 exigés) | 414 |
| nationalité / habilitation / J-1 exclu | 316 |
| niveau / université imposée (ex. « US based University ») | 265 |
| dates incompatibles | 174 |
| recherche (décision de Matisse) | 43 |
| PhD uniquement | 29 |
| fermée | 14 |

**1 205 sont notées sous le seuil** :

- Fit : 1 → 872, 2 → 193, 3 → 121, **4 → 19** ;
- 119 ne sont pas des stages (alternance, CDI…) ;
- **143 sont à moins de 10 points du seuil** (score de 55 à 64).

Répartition des scores :

| Score | 20 | 25 | 30 | 35 | 40 | 45 | 50 | 55 | 60 |
|---|---|---|---|---|---|---|---|---|---|
| Offres | 28 | 288 | 105 | 163 | 308 | 91 | 79 | 67 | 76 |

## 4. Fichiers et historique

| Donnée | Où | État |
|---|---|---|
| Verdicts et notes des 2 979 offres (gardées et écartées) | `notation/notes.json` (dépôt, version 2) | versionné |
| Éco / Pont par entreprise, avec preuves | `notation/entreprises.yaml` | versionné |
| Notes brutes des ≈ 2 900 offres | archive ci-dessus | **retrouvé**, hors dépôt |
| Texte complet de 3 172 offres | archive ci-dessus | **retrouvé**, hors dépôt |
| Offres vues, lieux, URL | branche `state` | versionné |

Mis à jour le 15 octobre 2026 : `notation.py` gardait seulement l'identifiant des offres
écartées. Il garde désormais leur note (motif et preuve, ou notes, preuves et score). Les notes
des 2 460 offres écartées ont été réintégrées depuis l'archive ; toutes ont passé la vérification
des citations et restent écartées avec les règles actuelles.

## 5 à 8. Ce que le dépôt ne contient pas

- **IA** : aucun appel à un modèle (GPT, Claude API, Mistral, local) ni aucun embedding.
  Coût actuel de la notation : celui des sessions Claude Code. Précision : **inconnue**, aucune
  note de référence humaine.
- **Envoi de candidatures** : aucun code. Rien sur Simplify, les formulaires Workday / Greenhouse /
  Lever, les CV adaptés ou le suivi des candidatures.
- **Infrastructure** : GitHub Actions (dépôt public, minutes illimitées), relais Cloudflare
  Workers (offre gratuite) pour `/offres` et `/refresh`. Coût mesuré : 0 €.
- **Performances** : aucune mesure de taux de réponse, de faux rejets ou de candidatures envoyées.

## Sur le point crucial : peut-on calibrer un filtre sur les 2 460 rejets ?

Pas tel quel. Ce qu'on constate :

1. **La moitié des rejets portent sur l'accès, pas sur la qualité** (1 255 inéligibles). Comme
   « mauvais exemples » d'un filtre de pertinence, ils apprendraient « habilitation US »
   ou « dernière année exigée », pas « mauvais poste ». Il faut les traiter à part, comme des
   règles avec une citation, vérifiables une par une.
2. **40 % du score dépend de l'entreprise, pas de l'offre.** Un bon poste (Fit 4) chez Thales,
   Orange ou Engie (Éco 2, Pont 2) obtient 61 avec Apprentissage 3. Il ne peut passer qu'avec
   Apprentissage 5. Les 19 rejets à Fit 4 sont tous de ce type. Un filtre entraîné sur ces
   étiquettes apprendrait le nom de l'entreprise.
3. **Fit et Apprentissage sont très corrélés** : 821 des 872 offres à Fit 1 ont aussi
   Apprentissage 1, ce que la grille impose (section 3.5). Les rejets reflètent donc presque
   uniquement le Fit.
4. **L'accord entre notateurs n'a jamais été mesuré.** Environ 63 agents ont noté des lots
   différents, et aucune offre n'a été notée deux fois.
5. **La relecture d'harmonisation était asymétrique.** `harmonie.py` n'a relu que les offres
   **gardées**, pour en écarter davantage (dates, M2). Les offres écartées n'ont jamais été
   relues pour détecter de faux rejets.
6. **Sondage de 41 rejets tirés au hasard** (non représentatif statistiquement) :
   - les motifs d'inéligibilité sont tous appuyés par une phrase explicite de l'offre
     (« U.S. citizenship is required », « dernière année d'un cycle Ingénieur », « January-June
     2027 »…) ;
   - les Fit 1 et 2 sondés correspondent à des postes hors cible (RH, qualité usine, AutoCAD,
     dashboards Tableau) ;
   - quelques Fit 3 sont discutables à la frontière 3/4, par exemple Thales « L'IA dans les
     pratiques d'ingénierie » ou Infineon « AI/ML implementation on Chip Verification flow ».

**Ce qu'il faudrait avant toute calibration** : un jeu de référence noté par Matisse lui-même,
environ 150 offres tirées des textes conservés et stratifiées. Il devrait sur-représenter les 143
offres proches du seuil, les Fit 2 à 4 et chaque motif d'inéligibilité. On mesure alors l'accord
avec les notes de Claude. Si c'est utile, on fait noter le même échantillon par un second modèle.
On sépare enfin les deux tâches : **éligibilité** (règles avec citation) et **pertinence**
(Fit / Apprentissage).
