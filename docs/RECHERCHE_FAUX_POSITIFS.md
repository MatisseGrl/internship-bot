# Faux positifs dans /offres : ce que font les agrégateurs, ce qu'on a déjà, quoi faire

Recherche du 2 novembre 2026, puis test des pistes sur des offres déjà notées (section « Test des pistes »). Rien n'est branché au bot : les essais ont tourné à part, hors du dépôt (scripts et résultats gardés en local, dans le dossier d'archives de notation de Matisse).

## En bref

- `/offres` affiche **2 274 offres** (current.json du 2 nov., 07:39 UTC) : **720 `notify` + 1 554 `review`**. Les `review` (« à vérifier ») sont la grosse source de bruit, pas les `notify`.
- **1 952 des 2 274 offres n'ont jamais été notées** avec la grille : elles sont arrivées après l'export de la session 6. La notation ne protège que les offres qu'elle a vues.
- Le paquet vient surtout des sites français lus par sitemap : **Thales 711** (toutes en `review`, lieu vide), Dassault Systèmes 229, Orange 115, Engie 63. Deux causes :
  1. le provider `sitemap` ne donne **aucun lieu** (992 offres « lieu vide ») : elles finissent en `review` d'office, et la règle « France = Île-de-France » ne peut pas les écarter ;
  2. les listes de mots de `filters_v3.py` sont **en anglais** : « Stage Ingénieur Développement Logiciel » ou « Stage Chargé de Communication » tombent tous les deux en « titre ambigu » (~1 240 offres).
- Les agrégateurs sérieux (Simplify, donc aussi SWElist qui renvoie vers Simplify) ne filtrent pas mieux sur le titre : ils **lisent le texte complet** et en tirent des champs (catégorie, diplôme, saison, visa, ouvert/fermé), puis un humain corrige à la marge.
- Les embeddings ont déjà été testés ici (« Tri ML v3 », octobre). Ils trient bien mais **n'ont jamais été branchés au bot**, et sur le titre seul ils ratent trop d'offres pour servir de filtre. Pas la peine de les refaire.
- **Test du 2 nov.** : le plus performant est de loin le **juge LLM avec la grille** (rappel 97 %, précision ~80 %, MCC 0,86). C'est aussi la mesure la plus flatteuse, car les étiquettes viennent du même type de juge. Sans LLM, le meilleur est un **petit modèle TF-IDF sur le texte de l'offre** (rappel 97 %, 40 % des offres affichées, MCC 0,48). Les règles seules (pistes 1 et 2) ratent **1 bonne offre sur 6**.

## Test des pistes (2 novembre 2026)

### Protocole

- **Étiquettes** : les 2 842 offres notées avec la grille en octobre dont on a gardé le texte (archives de la session 6). Pertinente = retenue, limite ou à trancher (393). Non pertinente = écartée, quel que soit le motif (2 449). Les illisibles sont retirées.
- **Découpage par entreprise**, tiré au sort avant tout essai : développement 1 650 offres (79 entreprises), test 1 192 offres (44 entreprises, 171 pertinentes). Aucune entreprise commune. Les listes de mots, les règles et les seuils ont été écrits en ne regardant que le développement. Le test n'a été évalué qu'une fois.
- **Méthodes**, toutes appliquées après le filtre de titre actuel (une offre `drop` reste écartée) :
  - **M0** : la prod d'aujourd'hui sans la notation (`notify` + `review` affichées) ;
  - **M1a / M1b / M1c** (piste 1) : seulement les `notify`, puis + mots français, puis + lieu lu sur la page de l'offre ;
  - **M1'** : mots FR + lieu, mais `review` encore affichées ;
  - **M2 / M2'** (piste 2) : M1c ou M1', + règles sur le texte (`eligibilite.py` de la branche Tri ML, plus une règle de dates : janvier-juin imposé, 6 mois dès janvier, automne 2026, été 2026…) ;
  - **ML** : régressions logistiques sur titre + texte, apprises sur le développement. TF-IDF mots et caractères, embeddings multilingues `paraphrase-multilingual-MiniLM-L12-v2`, ou les deux. Seuil réglé hors pli pour garder 95 % des bonnes offres ;
  - **M3** (piste 3) : juge LLM à l'aveugle, en appliquant `notation/CONSIGNES.md` sans voir les étiquettes. Faute de clé API, c'est Claude qui a jugé dans la session, sur 80 offres du test tirées au hasard (30 pertinentes, 50 écartées), texte réduit à 2 200 caractères + phrases clés (dates, niveau, nationalité).
- **Métriques** :
  - rappel = part des bonnes offres gardées, avec IC de Wilson à 95 % ;
  - faux rejets ;
  - précision = part des offres affichées qui sont bonnes ;
  - faux positifs et leur taux ;
  - F1 ;
  - F2, qui compte le rappel double : rater une offre coûte plus cher qu'en voir une de trop ;
  - MCC (corrélation de Matthews, de -1 à 1, insensible au déséquilibre des classes) ;
  - part des offres affichées ;
  - IC du F2 et du MCC par bootstrap des entreprises (2 000 tirages).

### Résultats sur le test complet (1 192 offres, 171 pertinentes)

| Méthode | Affichées | Rappel [IC 95 %] | Faux rejets | Précision | Faux positifs | F2 [IC] | MCC [IC] |
|---|---:|---:|---:|---:|---:|---:|---:|
| M0 actuel | 97 % | 100 % [98-100] | 0 | 14,8 % | 988 | 0,46 [0,30-0,64] | 0,07 [0,03-0,11] |
| M1a sans `review` | 32 % | 82,5 % [76-87] | 30 | 36,7 % | 243 | 0,66 [0,52-0,76] | 0,44 [0,30-0,56] |
| M1b + mots FR | 32 % | 82,5 % [76-87] | 30 | 36,9 % | 241 | 0,66 [0,52-0,77] | 0,44 [0,30-0,56] |
| M1c + lieu de la page | 45 % | 83,0 % [77-88] | 29 | 26,6 % | 392 | 0,58 [0,41-0,74] | 0,32 [0,18-0,49] |
| M1' FR + lieu, `review` gardées | 88 % | 96,5 % [93-98] | 6 | 15,7 % | 888 | 0,48 [0,31-0,65] | 0,10 [0,04-0,17] |
| M2 piste 1 + règles texte | 31 % | 80,7 % [74-86] | 33 | 37,5 % | 230 | 0,66 [0,50-0,77] | 0,44 [0,31-0,57] |
| M2' `review` gardées + règles texte | 65 % | 93,0 % [88-96] | 12 | 20,4 % | 621 | 0,54 [0,37-0,70] | 0,24 [0,13-0,34] |
| **ML TF-IDF (texte)** | **40 %** | **97,1 % [93-99]** | **5** | **35,2 %** | **305** | **0,72 [0,60-0,81]** | **0,48 [0,39-0,56]** |
| ML embeddings | 71 % | 87,1 % [81-91] | 22 | 17,6 % | 696 | 0,49 [0,36-0,60] | 0,15 [0,00-0,23] |
| ML ensemble | 49 % | 97,1 % [93-99] | 5 | 28,6 % | 415 | 0,66 [0,51-0,77] | 0,40 [0,31-0,49] |

AUC du test : TF-IDF 0,955, embeddings 0,726, ensemble 0,880.

### Résultats sur l'échantillon du juge (80 offres, repondérées aux proportions du test)

| Méthode | Affichées | Rappel [IC 95 %] | Précision | F2 | MCC |
|---|---:|---:|---:|---:|---:|
| M0 actuel | 95 % | 100 % [89-100] | 15 % | 0,47 | 0,10 |
| M1a / M2 (règles) | 31 % | 83 % [66-93] | 39 % | 0,68 | 0,47 |
| ML TF-IDF | 33 % | 100 % [89-100] | 43 % | 0,79 | 0,58 |
| **M3 juge LLM** | **17 %** | **97 % [83-99]** | **80 %** | **0,93** | **0,86** |
| ML TF-IDF puis juge | 17 % | 97 % [83-99] | 80 % | 0,93 | 0,86 |

Le juge s'est trompé 3 fois sur 80. Il a écarté un Micron « janvier-mai 2027 » qui recouvre en fait avril-mai, donc gardé par la grille. Il a gardé à tort Jump « Systems Engineer » et NVIDIA « Computer Architecture » (score de grille sous 65).

### Ce qu'il faut en retenir

1. **Le juge LLM avec la grille est de loin le plus performant** : il n'affiche que 17 % des offres, et 4 sur 5 sont bonnes. Avec le modèle TF-IDF devant lui, il fait aussi bien en ne lisant que ~35-40 % des offres, ce qui réduit le coût (ou le temps de notation en session).
2. **Sans LLM, le modèle TF-IDF sur le texte est le meilleur compromis** : il rate 5 bonnes offres sur 171 (3 %) et divise l'affichage par 2,4. Mais il lui faut le texte de chaque offre (`descriptions.py`, une requête de plus par nouvelle offre), et il faut le réentraîner quand la grille change.
3. **Les règles seules ne suffisent pas** : masquer les `review` coupe 2/3 de l'affichage mais perd **1 bonne offre sur 6**. C'est contraire à la règle « mieux vaut une alerte de trop qu'une offre manquée ». Les mots français et les règles texte n'ajoutent presque rien sur ce test. Récupérer le lieu fait même **monter** l'affichage : des offres « lieu vide » passent en `notify` sans être meilleures.
4. **Les embeddings restent faibles** (AUC 0,73 sur le test), comme en octobre. On peut arrêter de les essayer.

### Limites (à lire avant de décider)

- **Le juge est avantagé.** Les étiquettes viennent de la notation d'octobre, faite elle aussi par des agents Claude avec la même grille. Ce test mesure la fidélité à la grille de Matisse, pas la vérité. Un juge LLM qui « pense comme » les étiquettes est forcément flatté. Seul un échantillon relu par Matisse trancherait.
- **Le ML apprend ces mêmes étiquettes**, donc il hérite de leurs erreurs. Les règles, elles, n'en dépendent pas.
- **Thales et Dassault sont tombés dans le développement, pas dans le test**, donc l'effet des mots français est mal mesuré ici. Engie, Orange et Siemens sont bien dans le test.
- **80 offres pour le juge** : les intervalles sont larges (rappel entre 83 et 99 %).
- Le juge a lu un texte réduit. Un vrai passage automatique lirait l'offre entière.
- Les offres d'octobre sont celles qui passaient le filtre à l'époque ; les nouvelles (sitemaps français) peuvent se comporter autrement.

## Ce que font vraiment ces sites

### Simplify / SimplifyJobs Summer2027-Internships (et SWElist)

Source la plus documentée. J'ai lu leur guide de contribution et analysé leur fichier public `listings.json` (17 373 annonces au 2 nov.).

- **Presque tout est automatique.** 17 181 annonces sur 17 373 (99 %) viennent d'un « microservice externe » privé qui tire chaque jour les offres de la base Simplify ; 192 seulement viennent d'humains via une issue GitHub, relue par l'équipe (étiquette `approved`) avant d'entrer.
- **Chaque annonce porte des champs structurés**, remplis à partir de la description (méthode privée, non publiée) :
  - `category` : Software, AI/ML/Data, Hardware, Product, Quant. Pas de catégorie tech = pas dans la liste ;
  - `degrees` : Bachelor's, Master's, PhD, MBA. Le 🎓 « diplôme avancé exigé » vient de là, pas du titre (803 annonces « PhD seul ») ;
  - `terms` : Summer 2027, Fall 2026, Winter 2027… Le README « Summer 2027 » ne prend que la bonne saison : c'est leur filtre « mauvaise saison » ;
  - `sponsorship` : « Does Not Offer Sponsorship », « U.S. Citizenship is Required » (🛂, 🇺🇸) ;
  - `active` : 12 288 annonces sur 17 373 sont marquées fermées (🔒) et partent dans une liste « Inactive ». Les humains peuvent aussi signaler une fermeture (issue « Edit » ou « Bulk Mark Inactive »).
- **Périmètre volontairement étroit** : US, Canada ou remote ; une entreprise doit passer par un vrai ATS (Workday, Greenhouse, Ashby…). Ça élimine d'avance les Werkstudent, les alternances et les sites maison.
- **Doublons** : une annonce = une URL employeur, avec un identifiant unique. Pas de rapprochement « même titre, même entreprise ».
- Ce qui passe quand même : dans les annonces visibles, 168 titres contiennent « marketing », 98 « sales », 41 « part-time ». Même Simplify laisse passer du bruit.

### Handshake

Les offres sont **déposées par les employeurs** (pas collectées). Le tri se fait en amont : vérification de l'entreprise par l'équipe Trust & Safety de Handshake, puis validation de chaque offre par le service carrières de chaque école, avec ses propres règles (définition du stage de la NACE, refus des tâches « routinières »…). L'employeur coche lui-même « Internship » et temps plein ou partiel. Rien de transposable à un bot qui lit les sites carrières.

### intern-list.com, Jobright, LinkedIn, levels.fyi

- **intern-list.com** : mises à jour toutes les heures depuis « 200 000+ » sites, publiées dans un Airtable. Aucune vérification par offre n'est décrite.
- **Jobright** : promet des « offres authentiques » et une couche anti-spam, sans rien publier sur la méthode ; des utilisateurs se plaignent d'offres vieilles d'un ou deux mois.
- **LinkedIn** : des modèles ML ramènent les titres libres vers ~25 000 titres standard, puis vers une fonction (ingénierie, ventes…). C'est de la normalisation de titre, à une échelle qui n'a rien à voir avec la nôtre.
- **levels.fyi, SWElist** : rien de public sur leur tri. SWElist envoie des liens Simplify : même pipeline.

### Ce que dit la recherche

- **Clavié et al. 2023** (Bright Network, classement « poste pour jeune diplômé ou non », 10 000 offres) : à 95 % de rappel exigé, les mots-clés n'atteignent jamais ce rappel, un SVM fait 63 % de précision, DeBERTa fine-tuné 80 %, et **gpt-3.5 en zéro exemple, avec un prompt bien travaillé, 87 %**. Les auteurs jugent l'offre ratée plus grave que l'offre en trop, comme nous. Ce qui a aidé : le rôle et la tâche dans le message système, préciser que les stages comptent, demander de raisonner étape par étape. Ce qui a nui : les exemples few-shot et les formats de sortie trop rigides.
- **Kavas et al. 2024** (offres en italien et en espagnol) : le LLM fait mieux que les embeddings multilingues et le zéro-shot classique.
- **Thakrar & Young 2025** : un LLM fine-tuné sur leurs étiquettes a surappris (beaucoup de faux positifs et de faux négatifs), d'où un retour à une approche plus souple.
- **SetFit** (Hugging Face) : quelques dizaines d'exemples suffisent pour fine-tuner un petit modèle d'embeddings ; c'est l'option « petit modèle local » la plus légère, mais elle reste un tri sur le texte qu'on lui donne.
- **Offres expirées** : Greenhouse garde souvent la page en ligne avec un bandeau « no longer available », donc un 404 ne suffit pas. Il faut le code HTTP **et** chercher des phrases de fermeture (méthode de Lightcast, qui coupe aussi après 60 jours).
- **LLM comme juge** : la doc NeMo Curator de NVIDIA rappelle qu'un juge LLM n'est pas une vérité. On le valide d'abord sur un échantillon relu à la main, et la grille reste dans un fichier texte relisible.

## Ce qui a déjà été essayé ici

| Étage | Où | Ce qu'il fait | Limite constatée |
|---|---|---|---|
| Filtre par règles v3 | `src/internbot/filters_v3.py` (prod) | titre -> `notify` / `review` / `drop`, puis lieu | Listes en anglais ; lieu vide -> `review` d'office ; tout `review` est affiché dans `/offres` |
| Grille de notation | `notation/GRILLE.md`, `notes.json` (prod) | sous-agents qui lisent le texte complet, notes + citations obligatoires, motifs d'exclusion (niveau, dates, fin d'études, recherche…) | Très efficace (2 892 -> ~490 en octobre), mais **manuelle, en session** (pas de clé API, décision de Matisse) : 1 952 offres arrivées depuis ne sont pas notées |
| Tri ML titre `titre-ensemble-v3` | branche `claude/reprise-tri-ml`, `agent_local/tri_ml.py`, `docs/TRI_ML_RAPPORT.md` | embeddings `bge-base-en` + n-grammes de caractères, appris sur les notes « Fit rôle » | Test mis de côté : AUC 0,90, **6 offres pertinentes sur 94** en basse priorité. Verdict du rapport : « priorité de lecture seulement » |
| Tri ML texte `texte-ensemble-v1` | même branche, `agent_local/tri_texte.py` | titre + TF-IDF + embeddings sur la description | Bien meilleur : AUC 0,976, 2/94 ratées avec 59 % en basse priorité. **Jamais branché au bot** ; test déjà consulté ; aucune étiquette humaine indépendante (les 70 titres SWElist à annoter attendent toujours) |
| Règles d'éligibilité | même branche, `agent_local/eligibilite.py` | phrases du texte : PhD, nationalité US, fin d'études, recherche, annonce fermée | Retrouve 365 refus « fin d'études » sur 414, 193 « nationalité » sur 316. Pas de règle sur les dates ni sur le pays de l'université. Signale l'offre sans la supprimer |

Pourquoi les embeddings « n'ont pas suffi » :
1. **Sur le titre, l'information n'y est pas** : codes internes, titres de programme, mots trompeurs (« Analyst », « Electronics »). La moitié des refus de la grille portent sur les dates, le niveau ou la nationalité, qu'aucun titre ne montre.
2. **Le modèle d'embedding est anglais**, alors que le gros du bruit actuel est en français (Thales, Orange, Engie, Dassault).
3. **Le modèle sur le texte marche, mais il vit à côté du bot** (`agent_local/`, sur une branche). La prod n'a que les règles et les notes.

Les refaire n'apporterait rien. Le manque n'est pas dans le modèle : c'est le branchement et la langue.

## Pistes, classées par effort et gain

> **Mis à jour après le test du 2 nov.** Classement révisé par les mesures :
> 1. **juge LLM avec la grille** (piste 3), si possible derrière le modèle TF-IDF pour lire moins d'offres ;
> 2. **modèle TF-IDF sur le texte**, si on reste sans LLM. Il n'était pas dans la liste de départ ;
> 3. **règles** (pistes 1 et 2) : utiles pour ranger, pas pour filtrer, car elles perdent 1 bonne offre sur 6.
>
> Les pistes de départ sont gardées telles quelles ci-dessous.

### 1. Faire le ménage dans les règles (effort faible, gain fort)

C'est ce que fait Simplify : pas de catégorie tech reconnue = pas dans la liste.

- **Ne plus afficher les `review` par défaut dans `/offres`** (par exemple derrière `/offres tout`, ou seulement dans le résumé du matin). `/offres` passerait de 2 274 à ~720 offres tout de suite. Aucun risque de spam : les `review` ne sont pas notifiées une par une.
- **Ajouter les mots français** dans `filters_v3.py` : tech (logiciel, développement, informatique, données, cybersécurité, réseau…) et non-tech (communication, juriste, achats, comptabilité, mécanique, génie civil, logistique…). Ordre de grandeur sur les « titres ambigus » : environ 380 ont un mot tech français, environ 130 un mot non-tech français, à affiner sur les vrais titres.
- **Récupérer le lieu des offres lues par sitemap** (Thales, Orange, Engie…) sur la page de l'offre, comme on le fait déjà pour les Workday « N Locations ». La règle Île-de-France pourra alors s'appliquer.
- **Werkstudent / working student / alternance / apprenti** : aujourd'hui comptés comme des stages dans `INTERN`. Matisse doit trancher (« à trancher » dans STATUS) ; si c'est non, il suffit de les sortir de la liste.

Risque : écarter de vrais stages à cause d'un mot. Comme pour chaque changement de filtre : `--dry-run` sur une copie de l'état, puis relecture des offres qui changent de seau.

### 2. Lire le texte pour les critères que le titre ne montre pas (effort moyen, gain fort sur le reste)

L'équivalent des champs `degrees`, `terms`, `sponsorship` et `active` de Simplify, avec des outils qu'on a déjà :

- brancher `agent_local/eligibilite.py` (PhD, nationalité, fin d'études, recherche, annonce fermée) dans le runner, sur les textes déjà exportés (`descriptions.py`). Au départ en simple **étiquette** dans `/offres`, pas en suppression, comme le recommande le rapport ML ;
- ajouter une règle **saison** : refuser l'offre si le texte ne parle que de 2026, Fall, Spring ou Winter sans Summer 2027 ;
- **offres fermées** : code HTTP + phrases « no longer accepting / n'est plus disponible », pour les vider de `/offres` ;
- `texte-ensemble-v1` peut ensuite **ordonner** l'affichage (les plus pertinentes d'abord), sans rien jeter.

### 3. Automatiser la grille avec un petit LLM (effort moyen, coût récurrent faible ; contraire à une décision actuelle)

La notation de la session 6 est déjà un « LLM comme juge » : grille écrite, citations obligatoires, validateur. La recherche (Clavié et al.) montre que c'est l'approche la plus précise quand on veut rater peu d'offres. La faire tourner à chaque passage sur les **nouvelles** offres réglerait pour de bon le problème des 1 952 non notées.

- Ordre de grandeur : Claude Haiku 4.5 à 1 $ / 5 $ par million de tokens (moitié prix en lot). ~2 000 offres × ~2 500 tokens ≈ 5 M tokens, **environ 3 à 5 $ une fois**, puis quelques centimes par jour.
- Mais Matisse a décidé **pas de clé API** (session 6). À rediscuter seulement s'il le veut. Sinon, l'alternative est de garder la notation en session, plus souvent (après chaque grosse vague d'offres).
- Avant tout filtrage automatique : comparer ses verdicts aux 3 000 notes existantes, et faire relire par Matisse un échantillon de ses refus.

### Écarté

- **Refaire des embeddings ou fine-tuner un modèle de titres** : déjà fait (voir plus haut). Le plafond vient des titres, pas du modèle.
- **Embeddings multilingues pour le français** : possible, mais la piste 1 règle le même problème pour beaucoup moins cher.
- **Rapprocher les doublons par titre** : Simplify ne le fait pas non plus. Les doublons xAI / SpaceX restent mineurs.

## Sources

- SimplifyJobs, guide de contribution et schéma : https://github.com/SimplifyJobs/Summer2027-Internships/blob/dev/CONTRIBUTING.md
- SimplifyJobs, README Summer 2027 (catégories, symboles) : https://github.com/SimplifyJobs/Summer2027-Internships
- SimplifyJobs, données analysées : https://github.com/SimplifyJobs/Summer2027-Internships/blob/dev/.github/scripts/listings.json
- Clavié et al., *Large Language Models in the Workplace: A Case Study on Prompt Engineering for Job Type Classification* (2023) : https://arxiv.org/abs/2303.07142
- Kavas et al., *Enhancing Job Posting Classification with Multilingual Embeddings and Large Language Models* (CLiC-it 2024) : https://aclanthology.org/2024.clicit-1.53
- Thakrar & Young, extraction de critères d'offres par LLM (2025) : https://arxiv.org/html/2501.07663v1
- SetFit, Hugging Face : https://huggingface.co/blog/setfit
- NVIDIA NeMo Curator, LLM juge : https://docs.nvidia.com/nemo/curator/curate-text/process-data/quality-assessment/llm-judge
- Lightcast, expiration des offres : https://kb.lightcast.io/en/articles/7124903-job-postings-expiration
- Offres Greenhouse archivées (blog tiers) : https://jobspipe.dev/blog/find-expired-job-postings
- LinkedIn, standardisation des titres : https://business.linkedin.com/talent-solutions/cx/18/09/insights-resources/corp/our-data
- Handshake, vérification des employeurs (guide InternshipsVA) : https://www.vedp.org/sites/default/files/InternshipsVA/InternshipsVA%20on%20Handshake_Employer%20Guide.pdf
- intern-list.com (article NCDA) : https://www.ncda.org/aws/NCDA/pt/sd/news_article/605007/_PARENT/CC_layout_details/false
- Jobright (avis Adzuna) : https://www.adzuna.co.uk/blog/?p=24001
- Tarifs Claude : https://docs.claude.com/en/docs/about-claude/pricing
- Dans ce dépôt : `docs/TRI_ML_RAPPORT.md`, `docs/REPRISE_TRI_ML_CLAUDE.md`, `docs/SOURCES_ET_TRI.md` (branche `claude/reprise-tri-ml`), `src/internbot/filters_v3.py`, `notation/GRILLE.md`.
