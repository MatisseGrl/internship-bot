# Noter les offres du bot avec la grille

La grille de référence est `notation/GRILLE.md`, recopiée sans modification du kit de notation
de Matisse. Ce fichier-ci explique seulement comment l'appliquer **en série** aux offres du bot,
au lieu de l'Excel (40 lignes au maximum, inadapté à des milliers d'offres).

Ce qui change par rapport à `GRILLE.md` :
- pas d'Excel ni de `ajouter_offre.py` (sections 5 et 6 de la grille) : les notes vont dans un
  fichier JSONL, puis `python -m internbot --importer-notes` calcule les scores et met à jour
  `notation/notes.json`, que le bot lit à chaque passage ;
- **Écosystème SF** et **Pont vers SF hors US** sont notés une fois par entreprise, dans
  `notation/entreprises.yaml` (même barème, sections 3.3 et 3.4 de la grille) ;
- pour chaque offre, on note seulement ce qui dépend de son texte : éligibilité, Fit,
  Apprentissage, lieu aux États-Unis, éventuel pont propre à l'équipe, conditions ;
- aucune recherche web par offre : tout se juge sur le texte de l'annonce.

Tout le reste de la grille s'applique tel quel : missions et pas le titre, aucun mot-clé
décisif, pas de comparaison avec le CV, une note = une preuve, règle de départage (en cas
d'hésitation, la note la plus basse), pas de double compte, pas d'ajustement pour passer le seuil.

## Déroulé

```bash
# 1. Texte des offres ouvertes pas encore notées (reprend là où il s'est arrêté)
python -m internbot --a-noter travail/ --state .state/state.json
# 2. Noter : une ligne JSON par offre dans travail/notes*.jsonl (format ci-dessous)
# 3. Appliquer (refuse toute note dont une citation est absente du texte de l'offre)
python -m internbot --importer-notes travail/
```

Une entreprise absente de `notation/entreprises.yaml` bloque l'import de ses offres : l'ajouter
d'abord (eco, pont hors US, une preuve pour chacun, sources citées).

## Format d'une note (une ligne JSON par offre)

```json
{"company": "Waymo", "job_id": "8234553",
 "eligible": true, "stage": true,
 "lieu_us": true, "preuve_lieu": "Mountain View, CA",
 "fit": 5, "preuve_fit": "train and evaluate perception models",
 "app": 4, "preuve_app": "you will be paired with a mentor",
 "conditions": "Été 2027, 12 semaines, non précisé"}
```

| Champ | Règle |
|---|---|
| `company`, `job_id` | Recopiés de l'offre, à l'identique. |
| `eligible` | `false` seulement si l'offre est **clairement fermée** (grille, étape 3). Ajouter alors `motif` et `preuve_motif` ; les autres champs sont inutiles. |
| `motif` | `fin_etudes` (stage de fin d'études uniquement, y compris quand l'offre **exige** d'être en M2, en 5e année ou en dernière année d'études : Matisse sera en M1 / 4e année en 2027. « Préparer un diplôme Bac+5 » ou « école d'ingénieur » ne ferme rien : Matisse prépare un diplôme d'ingénieur Bac+5 ; « avant-dernière année » lui correspond) ; `niveau` (niveau, école ou date de diplôme **imposés** que Matisse n'a pas : MBA uniquement, diplôme exigé en 2027 ou en 2029, inscription obligatoire dans une université d'un pays précis…) ; `phd` (PhD uniquement) ; `fermee` (expirée, ou saison passée : 2026) ; `nationalite` (citoyenneté US / « U.S. person » / habilitation de sécurité exigées, ou visa J-1 explicitement exclu) ; `dates` (période **imposée et écrite** sans aucun recouvrement possible avec avril-août 2027 : automne 2026, « Winter 2027 (January - April) », 6 mois imposés dès janvier 2027, début imposé en juillet pour 6 mois…). |
| éligibilité floue | N'exclut **pas** : noter normalement et l'écrire dans `conditions`. Exemples : « Master's preferred », « undergraduate students », droit de travailler dans le pays, durée de 6 mois sans date imposée, saison ambiguë (« Winter/Spring 2027 » sans dates, « dès que possible »). Matisse est en 4e année d'école d'ingénieur (niveau master 1), diplôme en juin 2028. **Pour les offres américaines, il est à la fois inscrit en Bachelor of Science et en Master of Science** (précisé par Matisse) : une offre réservée aux étudiants en Bachelor / undergraduate, ou en Master, lui est ouverte. Restent fermées : MBA uniquement, PhD uniquement, date de diplôme imposée hors de juin 2028, inscription dans une université précise. |
| `stage` | `false` si ce n'est pas un stage : alternance / apprentissage, CDI / CDD, VIE, Werkstudent / job étudiant à temps partiel, poste confirmé. L'offre est alors gardée « à trancher » par Matisse (grille, section 7) si elle passe la grille, écartée sinon. |
| `lieu_us` | `true` si le stage peut se faire aux États-Unis (au moins un lieu US proposé, ou remote US). `preuve_lieu` : le lieu US recopié du texte. → Pont = 5. `false` sinon → Pont = note de l'entreprise. |
| `pont_offre`, `preuve_pont` | Facultatifs, seulement si le texte prouve un lien plus fort que la note de l'entreprise : 4 = « équipe qui travaille avec le bureau de SF / Bay Area » ou « mobilité vers les US » écrite dans l'offre ; 5 = « mobilité interne vers SF explicitement prévue ». Jamais sur une supposition. |
| `fit` | 1 à 5, section 3.2 de la grille, **sur les missions**. `preuve_fit` : la phrase des missions qui justifie la note. |
| `app` | 1 à 5, section 3.5. `preuve_app` : la phrase sur la mise en prod, le mentor ou le programme ; ou `"non précisé"` si l'offre n'en dit rien (alors 3 au maximum). |
| `conditions` | Une ligne courte, hors score : dates, durée, rémunération, points de friction (« 6 mois », « droit de travailler au UK exigé »), ou « non précisé ». |

**Citations** : copiées **mot pour mot** du texte de l'offre (au moins 3 mots, langue d'origine).
L'import vérifie chaque citation dans le texte exporté ; une citation absente fait refuser la
note. On ne reformule pas et on n'invente rien.

## Verdicts calculés à l'import

Score = (Fit×45 + Éco×20 + Pont×20 + App×15) / 5, seuil 65 (onglet Barème du kit).

| Verdict | Condition | Dans /offres |
|---|---|---|
| retenue | score ≥ 65 | gardée |
| limite | score < 65, mais ≥ 65 avec un autre jeu de poids (SF-first ou Apprentissage) | gardée, à trancher par Matisse |
| à trancher | pas un stage (`stage: false`) mais passe la grille | gardée |
| illisible | texte inaccessible (page protégée, anti-bot) | gardée, à trier à la main |
| écartée | non éligible, ou sous le seuil avec les trois jeux de poids | supprimée (seul l'identifiant est gardé, pour la cacher) |

Une offre qui n'a pas encore été notée reste visible. Avec Fit = 1, aucune offre ne passe :
le maximum est 64 (grille, section 3.1).
