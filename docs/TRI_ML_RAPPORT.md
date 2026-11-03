# Tri ML des titres — rapport du 16 octobre 2026

Reprise du travail de Codex (`docs/REPRISE_TRI_ML_CLAUDE.md`). Les chiffres ci-dessous sont agrégés ; les résultats par offre, la base et les échantillons restent privés.

## Verdict

**Priorité de lecture seulement.** Le modèle livré, `titre-ensemble-v3`, trie mieux que `titre-logreg-v1`. Il ne doit toujours pas exclure d'offre : sur le test mis de côté, 6 offres pertinentes sur 94 tombent en basse priorité. Les erreurs restantes viennent surtout de titres qui ne décrivent pas le poste ; seul le texte de l'annonce peut les corriger.

## Données

- Cible : première note historique **Fit rôle**, 3-5 = pertinent (1), 1 = hors métier (0). Les notes 2 et les refus d'éligibilité ne servent pas d'étiquettes.
- 1 209 titres après dédoublonnage. Changement par rapport à v1 : un titre noté de façon contradictoire prend son **étiquette majoritaire** au lieu d'être retiré (égalités retirées). v1 jetait ainsi « software engineer intern », le titre pertinent le plus fréquent, à cause d'une seule annonce hors métier.
- Découpage inchangé par entreprise : développement 922 titres (343 pertinents), test 287 titres (94 pertinents), aucune entreprise commune.
- Le registre actif n'a pas été modifié : toutes les expériences tournent sur une copie `sqlite3.backup`.

## Protocole

Fixé avant les essais. Sélection par **validation croisée imbriquée groupée par entreprise** sur le développement seulement : 5 plis externes × 2 répétitions, recherche des hyperparamètres en 4 plis internes. Le critère interne est la moyenne des faux rejets lorsque 15, 25 et 35 % des titres sont en basse priorité. Le seuil bas est réglé hors pli pour viser 2 % de faux rejets. Le test (déjà consulté en v1 pour ses 7 erreurs, jamais utilisé ici pour un réglage) n'est évalué qu'une fois, sur le modèle final choisi.

## Résultats de la validation imbriquée (développement)

| Famille | AUC | Faux rejets, 15 % en basse priorité | à 25 % | à 35 % | Réglage opérationnel : faux rejets / part en basse priorité |
|---|---:|---:|---:|---:|---|
| Modèle v1 (Python pur), nouveau seuil | 0,887 | 0,7 % | 2,8 % | 5,5 % | 2,9 % / 26,5 % |
| TF-IDF optimisé (scikit-learn, 30 réglages) | 0,885 | 2,6 % | 4,1 % | 6,9 % | 3,9 % / 25,9 % |
| TF-IDF + règles de titres en caractéristiques | 0,871 | 3,6 % | 5,4 % | 8,2 % | 3,1 % / 21,4 % |
| Embeddings `bge-base-en-v1.5` + logistique | 0,908 | 1,2 % | 2,8 % | 5,4 % | 3,6 % / 26,4 % |
| Plus gros embeddings (arctic-m, nomic, gte) | 0,910 | 1,6 % | 3,2 % | 5,5 % | 3,6 % / 28,9 % |
| **Ensemble embeddings + TF-IDF caractères 3-5** | **0,924** | **0,6 %** | **1,5 %** | **4,1 %** | **2,6 % / 28,7 %** |

Avant cette reprise, v1 affichait 7,4 % de faux rejets pour 27 % des titres en basse priorité. L'essentiel de l'écart venait du **seuil** : v1 prenait le plus petit score pertinent d'une validation de 66 exemples, une valeur très instable. Le seuil réglé hors pli ramène le même modèle à environ 3 %.

## Test mis de côté (une seule évaluation)

| Modèle | AUC | Faux rejets, 25 % en basse priorité | Réglage opérationnel | Offres retenues (score ≥ 65) en basse priorité | Précision des `prioriser` |
|---|---:|---:|---|---:|---:|
| v1, nouveau seuil | 0,895 | 3/94 | 5/94, 37 % en basse priorité | 1/45 | 81 % |
| **Ensemble v3** | **0,900** | 5/94 | 6/94, 38 % en basse priorité | 1/45 | **89 %** |

Avec 94 positifs, un écart d'une ou deux erreurs n'est pas significatif. L'ensemble est retenu pour sa meilleure qualité de tri (AUC en développement et précision des `prioriser`, qui décident quelles descriptions récupérer d'abord), pas pour une baisse prouvée des faux rejets.

## Erreurs restantes

Analyse des titres pertinents classés dans les 25 % les plus bas, prédictions hors pli du développement :

1. **Titres opaques** : codes internes d'un fabricant de mémoire, intitulés de programmes ou de viviers sans métier. Le titre ne contient pas l'information.
2. **Titres non anglais** : un stage de développement logiciel en français. Les n-grammes de caractères de l'ensemble compensent en partie la faiblesse du modèle d'embedding anglais.
3. **Mot de domaine trompeur** : « Electronics » ou « Analyst » dans un poste dont les missions sont logicielles ou ML.
4. **Inverse** : « Software Engineer » chez un industriel de défense dont les missions sont de l'embarqué (noté Fit 1).

Presque tous ces cas avaient un score de grille inférieur à 65 ; en réglage opérationnel, 1 offre retenue sur 45 (test) et 6 sur 488 (développement, deux répétitions) se retrouvent en basse priorité.

## Pistes écartées

- **Règles de titres comme caractéristiques** : dégradent le modèle (tableau ci-dessus).
- **Abstention sur les titres jugés insuffisants par la règle** : 2,1 % de faux rejets, mais seulement 3 % des titres en basse priorité, moins utile que la règle seule.
- **Historique par entreprise** : seules 519 des 3 587 annonces SWElist viennent d'une entreprise déjà notée par le bot.

## Utilisation

```powershell
pip install -e ".[ml]"
# Entraîner, évaluer, figer le modèle et noter toutes les annonces SWElist (sur une copie d'abord)
python agent_local/tri_ml.py --db C:\chemin\prive\copie.sqlite --model C:\chemin\prive\modele_v3.json --report C:\chemin\prive\rapport.json --errors C:\chemin\prive\erreurs.csv
# Noter les nouvelles annonces sans réentraîner (annonces sans score ou d'une autre version)
python agent_local/tri_ml.py --db C:\chemin\prive\suivi.sqlite --model C:\chemin\prive\modele_v3.json --noter
```

L'artefact JSON (environ 430 Ko) contient le vocabulaire, les idf, les poids des deux régressions, les seuils et l'empreinte des données d'apprentissage. Le score d'une annonce ne change donc pas quand l'inventaire grossit. Le modèle d'embedding (~440 Mo) est téléchargé une fois par fastembed. Entraînement complet : environ 80 s sur CPU ; aucune API payante.

## Modèle sur le texte complet (`texte-ensemble-v1`)

Les descriptions sont maintenant récupérées : pages publiques Simplify pour SWElist, export du bot pour ses offres. Le modèle `agent_local/tri_texte.py` additionne les log-odds de trois régressions logistiques : modèle titre v3, TF-IDF mots et paires de mots du texte, embeddings locaux du texte (moyenne de morceaux de 1 200 caractères). Même protocole : validation imbriquée par entreprise sur le développement.

| Modèle | AUC | Faux rejets, 15 % en basse priorité | à 25 % | à 35 % |
|---|---:|---:|---:|---:|
| Titre v3 | 0,925 | 0,6 % | 1,6 % | 4,2 % |
| TF-IDF texte | 0,963 | 0,15 % | 0,44 % | 1,6 % |
| Embeddings texte | 0,945 | 0,3 % | 0,44 % | 1,0 % |
| **Titre + TF-IDF + embeddings** | **0,975** | **0 %** | **0,29 %** | **1,0 %** |

Sur le test mis de côté, le modèle texte atteint une AUC de 0,976. 2 offres pertinentes sur 94 tombent en basse priorité, qui regroupe 59 % des titres, et 41 `prioriser` sur 41 sont pertinents. Une seconde cible, « retenue » (score de grille ≥ 65), atteint une AUC de 0,974 hors pli et sert à trier la file finale.

## Éligibilité par règles (`agent_local/eligibilite.py`)

Les règles repèrent les exclusions explicites, avec la phrase qui les justifie : doctorat, nationalité ou habilitation américaine, stage de fin d'études ou dernière année, diplôme exigé avant 2028, poste de recherche, annonce fermée. Elles ont été mesurées sur les décisions historiques du bot :

- **Fausses alertes** : 18 sur 1 598 offres jugées éligibles, et plusieurs sont en fait de vraies exclusions.
- **Refus historiques retrouvés** : fin d'études 365 sur 414, nationalité 193 sur 316, recherche 27 sur 32.
- **Non couverts** : les critères de pays d'université et de dates de stage.

Les règles signalent l'offre ; elles ne la suppriment pas.

## Suite

1. **Récupérer les textes SWElist** par le lien Simplify puis « Apply » vers le site de l'employeur, en lecture seule, en commençant par les `prioriser`. Noter ces textes avec la grille donne de nouvelles étiquettes **indépendantes** : c'est le test qui manque pour décider d'un éventuel filtre.
2. Faire annoter l'échantillon SWElist de 70 titres (`label_humain`). Le rapport l'utilise automatiquement comme audit.
3. Un rejet automatique ne se discute qu'après un test indépendant d'au moins quelques centaines d'offres pertinentes, avec un taux de faux rejets et son intervalle de confiance acceptés par Matisse.
