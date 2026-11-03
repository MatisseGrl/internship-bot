# Passation à Claude — tri ML des stages

Ce document est la version publiable de la passation. Le registre SQLite, l'inventaire des e-mails, les CV, le profil candidat, les identifiants des messages et les résultats détaillés par offre restent privés et ne sont pas dans ce dépôt. Demander à Matisse l'accès à ces fichiers dans son espace local si une analyse des lignes individuelles est nécessaire.

## Mission

Reprendre le tri sélectif des titres d'offres de stage, puis déterminer par des tests indépendants s'il améliore réellement la priorité de lecture. Le modèle ne décide pas d'une candidature, de l'éligibilité ou de l'envoi d'un formulaire. Aucune annonce n'est exclue automatiquement. Le premier objectif est de réduire le nombre de descriptions à récupérer tout en conservant les offres pertinentes dans une file vérifiable.

## Architecture et données

- Le bot personnel alimente le registre privé `offres`. L'import et le suivi sont décrits dans `agent_local/README.md` et `agent_local/agent.py`.
- Les alertes SWElist sont extraites par `agent_local/ingest_swelist.py`, puis `agent_local/import_swelist.py` les place dans `swelist_annonces`, **séparément** des offres du bot. Le schéma distant est dans `supabase/migrations/20261015214907_swelist_annonces.sql` et la copie privée dans `agent_local/sync_supabase.py`.
- Les recoupements entre sources sont attendus. Une égalité entreprise/titre n'est qu'un indice ; ne fusionner qu'avec une URL employeur ou un identifiant d'offre fiable, ou après vérification humaine. L'identifiant Simplify n'est pas l'identifiant du système de candidature de l'employeur.
- `agent_local/tri_ml.py` entraîne le premier modèle et écrit des scores de priorité sur la base passée par `--db`. **Toute reproduction doit utiliser une copie SQLite cohérente**, pas le registre actif.
- `agent_local/revue_swelist.py` exporte un échantillon à annoter et importe `label_humain` : `1` = métier pertinent, `0` = hors métier. Les labels humains ne sont pas déduits du score et ne sont pas injectés automatiquement dans l'entraînement.
- L'automatisation quotidienne importe les nouveaux messages dans l'inventaire et la table séparée ; elle ne réentraîne pas le modèle. Les nouvelles annonces peuvent avoir `score_fit = NULL`.

Au point de passation du 15 octobre 2026, la base privée contient **3 909 offres du bot** et **3 587 liens SWElist**, issus de 49 e-mails. Toutes les annonces SWElist alors présentes avaient un score `titre-logreg-v1`, mais **aucune étiquette humaine**. Un rapprochement strict entreprise/titre donnait 35 candidats uniques, 10 cas ambigus et aucune URL identique. Aucun rapprochement n'a fusionné les deux sources.

## Modèle et expérience déjà réalisée

La cible est la première note historique **Fit rôle** de la grille (`notation/GRILLE.md`), et non le verdict final gardée/écartée. La note `1` fournit 872 négatifs ; les notes `3–5` fournissent 518 positifs. Les notes `2` et les refus dus aux dates ou à l'éligibilité ne sont pas utilisés comme négatifs de titre. Après dédoublonnage des intitulés normalisés et retrait des labels contradictoires, il reste 1 205 exemples.

Le modèle actuel est une régression logistique locale avec TF-IDF de mots, de groupes de deux mots et de n-grammes de caractères. L'apprentissage, la validation et le test sont séparés par entreprise ; aucun titre normalisé exact ne traverse les jeux. Le seuil bas et le seuil haut viennent de la validation. Les scores ne sont pas des probabilités calibrées.

| Jeu | Titres | Positifs | AUC | Titres en basse priorité | Positifs en basse priorité | Priorisés | Précision des priorisés |
|---|---:|---:|---:|---:|---:|---:|---:|
| Apprentissage | 706 | 275 | 0,9805 | 296 | 2 | 145 | 98,62 % |
| Validation | 212 | 66 | 0,9344 | 43 | 0 | 44 | 90,91 % |
| Test | 287 | 94 | **0,8869** | 116 | **7** | 35 | **85,71 %** |

Le test montre que traiter la basse priorité comme un rejet ferait perdre **7 offres pertinentes sur 94**, soit 7,45 % de faux rejets parmi les offres pertinentes. La sortie reste donc `prioriser`, `a_lire` ou `basse_priorite_a_relire` ; **toutes les offres restent visibles**. Sur les 3 587 SWElist, les effectifs étaient respectivement 1 162, 1 679 et 746. La règle simple de titres mettait seulement 12 titres du test en basse priorité, sans positif parmi eux ; elle couvre beaucoup moins d'annonces.

Le jeu de test et ses sept erreurs sont désormais **consultés**. Ne pas optimiser un nouveau modèle ou seuil sur ce jeu, puis présenter sa performance sur ce même jeu comme indépendante. Une nouvelle évaluation doit employer un contrôle humain SWElist ou un autre test mis à part avant les réglages.

## Travail demandé à Claude

1. Lire `agent_local/README.md`, `docs/SOURCES_ET_TRI.md`, `notation/GRILLE.md` et les scripts cités. Vérifier l'état du dépôt et travailler sur une branche ou un checkout isolé. Demander l'accès aux rapports et à l'échantillon privés si ceux-ci ne sont pas disponibles dans l'espace local autorisé.
2. Reproduire les comptes et les résultats **sur une copie** du registre privé. Les tests du dépôt étaient au nombre de 19 et passaient au point d'arrêt : `python -m unittest discover -s agent_local -p 'test_*.py' -q`. Sous Windows, le Python système `WindowsApps` peut échouer ; employer le Python disponible dans l'environnement de travail et placer `TEMP`/`TMP` dans un dossier accessible du workspace.
3. Examiner les sept offres pertinentes tombées en basse priorité, les titres avec labels contradictoires, les titres quasi identiques entre jeux et la qualité des notes historiques. Construire une taxonomie d'erreurs concrète. Ne pas inventer d'étiquettes humaines.
4. Fixer par écrit la cible, la séparation des groupes, les règles de dédoublonnage, les métriques et les critères de décision **avant** d'ajuster le modèle. Comparer sur les données de développement : règles simples, modèle actuel, puis une variante légère motivée par les erreurs. Utiliser une validation par groupes d'entreprises. Mesurer surtout le rappel des offres pertinentes, les faux rejets, la couverture, la précision des priorités et l'incertitude statistique.
5. Faire annoter par Matisse un échantillon SWElist indépendant si nécessaire. Le script de revue fournit un CSV de 70 lignes avec 30 basses priorités, 20 intermédiaires et 20 priorités. Tant qu'il n'a pas de réponses humaines, avancer sur les analyses indépendantes et garder le verdict « priorité seule ».
6. Prévoir un artefact de modèle figé et versionné pour scorer les nouvelles annonces sans réentraîner silencieusement à chaque import. Conserver séparément le filtre par règles, le score ML, la version du modèle et les éventuels labels humains. Aucun coût d'API payante n'est requis pour le premier comparatif ; justifier et mesurer tout recours futur à des embeddings.
7. Tester les modifications utiles : absence de fuite entre jeux, scores reproductibles, import idempotent, conservation des labels, absence de modification des candidatures et rapprochements prudents entre sources. Vérifier toute évolution Supabase sans exposer la table aux rôles publics.
8. Livrer un rapport avec protocole, métriques par jeu, faux rejets, comparaison à la règle simple, limites, coût, et recommandation explicite. Ne proposer de rejet automatique qu'après un nouveau test indépendant et assez de labels humains pour estimer son risque ; sinon garder les annonces accessibles et ne prioriser que la lecture.

Les premiers dossiers de candidature peuvent partir des offres déjà qualifiées par le bot ; la recherche d'un meilleur classifieur n'a pas à retarder cette activité séparée. Aucun script de ce chantier ne doit remplir ni envoyer de candidature.
