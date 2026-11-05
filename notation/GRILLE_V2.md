# Notation v2 des offres de stage

Remplace la notation `GRILLE.md` (jugée insuffisante par Matisse). **Rien n'est branché sur le bot** tant que Matisse n'a pas donné son avis : les notes vivent dans `notation/v2/`, la prod (`/offres`, `notes.json`) ne change pas.

Population : les offres de `current.json` (elles ont passé le premier filtre, celui de `config.yaml`).

Le profil de Matisse est dans `notation/profil.local.md` (local, hors git). La notation v2 **compare l'offre à ce profil**, contrairement à l'ancienne grille.

## Principes

1. On juge les **missions et les exigences écrites**, jamais le titre ni un mot-clé seul.
2. Chaque note de 1 à 5 a **une preuve** : une phrase copiée mot pour mot de l'offre (3 mots ou plus), ou « non précisé ».
3. En cas d'hésitation, la note la plus basse.
4. **Rien n'est jamais caché.** La notation classe et étiquette, elle ne supprime aucune offre. Seule l'inéligibilité claire (étape 0) met une offre de côté, avec sa raison.
5. Les trois notes sont **séparées, jamais moyennées**. Une offre parfaite côté intérêt mais irréaliste reste visible, avec son étiquette.

## Étape 0 : éligibilité

Offre clairement fermée à Matisse : motif `fin_etudes` (stage de fin d'études / M2 / dernière année exigés), `niveau` (MBA seul, diplôme imposé hors juin 2028), `phd`, `fermee` (expirée, saison 2026), `nationalite` (citoyenneté US, habilitation, J-1 exclu), `dates` (période imposée sans aucun recouvrement avec avril-août 2027), `recherche` (poste de recherche : Research Intern, Researcher, Research Scientist, thèse. Les Research **Engineer** restent notés). Une éligibilité simplement floue n'exclut pas : on note et on l'écrit dans `conditions`.

Pas un stage (alternance, CDI, VIE, Werkstudent) : `stage: false`, noté quand même.

## Les trois notes

### Intérêt (1-5) : est-ce que cette offre vaut le coup pour son objectif ?
Objectif : meilleurs postes d'ingénierie IA appliquée / logicielle, chemin vers SF. On regarde ensemble le **métier**, ce qu'il y **apprend** et la **valeur de la boîte** pour la suite.
- **5** : cœur de cible (Applied AI / ML Engineer, FDE IA, SWE dans une équipe IA/ML) dans une boîte très reconnue, avec projet en prod, mentor ou programme.
- **4** : bon métier (SWE solide, data science de modélisation, FDE hors IA) dans une boîte reconnue, ou cœur de cible dans une boîte moyenne.
- **3** : métier proche (data engineering, full-stack, DevOps) ou bon métier dans une boîte peu lisible ; encadrement non précisé.
- **2** : lien faible (analyste, BI, front/mobile pur, avant-vente).
- **1** : hors métier (hardware, embedded, QA manuel, support, business, ESN générique).

### Compétences (1-5) : est-ce que je sais faire ce qui est demandé ?
Comparaison des exigences **requises** avec le profil (niveau >= 3 prouvé = acquis ; niveau 1-2 = à moitié ; inconnu = non). Le « nice to have » ne pèse presque pas.
- **5** : tout le requis est acquis.
- **4** : l'essentiel est acquis, 1 manque mineur.
- **3** : la moitié environ est acquise, le reste apprenable en quelques semaines.
- **2** : manque important sur le cœur du poste (ex. React avancé, C++ système, cloud en prod).
- **1** : le cœur du poste est hors de portée aujourd'hui.

### Réalisme (1-5) : chances raisonnables d'être pris ?
Regarde : expérience exigée (stage précédent, années), sélectivité de la boîte (Big Tech/labs/Palantir = bas), niveau d'études, lieu et autorisation de travail (US sans visa possible = bas, UE = neutre), exigences dures non remplies.
- **5** : profil de départ attendu, boîte accessible, aucune exigence dure manquante.
- **4** : bonnes chances, boîte moyennement sélective.
- **3** : possible mais compétitif (scale-up connue, ou un manque notable).
- **2** : ambitieux (boîte très sélective, ou expérience en entreprise tech attendue).
- **1** : quasi impossible (exigence dure non remplie : expérience, diplôme, autorisation, très haute sélectivité).

## Sorties par offre

`manque` : 1 à 4 compétences ou exigences requises que Matisse n'a pas. `conditions` : dates, durée, salaire, friction (hors notes).

## Priorité (calculée, jamais cachée)

| Priorité | Règle |
|---|---|
| **A : à tenter** | Intérêt >= 4 et Compétences >= 3 et Réalisme >= 3 |
| **B : ambitieux** | Intérêt >= 4 et (Compétences <= 2 ou Réalisme <= 2) : à tenter si l'envie est là, en sachant ce qui manque |
| **C : réaliste, moins fort** | Intérêt = 3 |
| **D : peu utile** | Intérêt <= 2 |
| **X : inéligible** | Étape 0 |

Tri : priorité, puis Intérêt, puis Compétences, puis Réalisme.
