# Plan d'automatisation des candidatures

État au 15 octobre 2026 : **plan documenté, aucun envoi automatisé en production**. Le bot actuel découvre, filtre et note des offres ; il n'envoie pas de candidatures. Voir [AUDIT.md](AUDIT.md) pour son architecture et les limites de la notation existante.

## Décisions prises

- **Aucune API payante requise pour le pilote.** Les abonnements ChatGPT/Codex et Claude existants seront utilisés dans la limite de leurs quotas. Les **10 USD par mois** sont un plafond éventuel si une API est décidée plus tard, pas une dépense prévue. Avant toute activation d'API, le programme devra suivre les coûts et s'arrêter avant ce plafond.
- Les **15 premières candidatures** seront vérifiées avant leur envoi. Ensuite, l'envoi automatique ne concernera que les parcours de formulaire déjà validés. Une plateforme nouvelle, une question ambiguë ou une confirmation d'envoi incertaine remettra l'offre en attente.
- Les CV utilisés seront des versions finales approuvées, choisies selon la zone, les dates et les exigences du poste. Le nom d'un fichier ne suffit pas à prouver qu'un CV convient.
- Le registre des candidatures, les CV, les réponses personnelles, les sessions de navigateur et les identifiants de messagerie resteront **hors du dépôt public**. Le dépôt ne contiendra ni clé API ni jeton de connexion.

## Répartition des tâches

| Élément | Rôle prévu |
| --- | --- |
| Bot existant | Collecter les annonces, appliquer les filtres et conserver les notes dans `notation/notes.json`. |
| Python local | Importer les offres, appliquer les règles certaines, dédupliquer, gérer la file d'attente et le journal des candidatures. Si une API est activée plus tard, contrôler aussi son budget. |
| Codex et Claude Code via les abonnements existants | Aider sur les cas ambigus : adéquation du poste, choix entre CV approuvés et réponses courtes fondées sur des faits fournis. Mesurer les limites d'usage et conserver des décisions relisibles. |
| Navigateur | Remplir les formulaires des employeurs et constater le résultat. Les champs connus sont traités de façon déterministe ; le modèle intervient seulement quand il apporte une valeur. |
| Messagerie | Retrouver les confirmations d'envoi et éviter les doublons, y compris lorsque plusieurs boîtes sont utilisées. La consultation doit rester limitée aux messages utiles aux candidatures. |

Les embeddings ne sont pas nécessaires pour le premier pilote : les offres déjà filtrées, la grille et une recherche de texte suffisent pour construire une file de travail. Leur intérêt sera évalué seulement si la recherche ou le volume le justifie.

## Historique et comptes de messagerie

Une offre encore ouverte peut avoir déjà reçu une candidature. Le registre privé doit être initialisé à partir des candidatures antérieures avant le premier envoi et indexé au minimum par entreprise, identifiant d'offre et URL canonique. L'absence d'e-mail n'est pas une preuve d'absence de candidature.

La vérification doit accepter plusieurs boîtes, chacune ajoutée explicitement au périmètre. Un accès interactif dans Chrome **n'est pas** une autorisation API durable : une exécution autonome devra disposer d'un accès explicite et limité pour chaque boîte utilisée. Le registre conservera localement la source et la date de chaque confirmation, sans copier les courriels dans Git.

## Parcours d'une offre

1. Lire les offres ouvertes dans `current.json` et les notes dans `notation/notes.json`.
2. Écarter les inéligibilités explicites, les postes hors cible et les candidatures déjà envoyées. Conserver la preuve de chaque décision ; ne pas entraîner un filtre de pertinence directement sur tous les rejets historiques, car beaucoup correspondent à une inéligibilité.
3. Classer les offres restantes. Réserver le modèle aux décisions que les règles ne tranchent pas et mesurer le temps et l'usage. N'ajouter un compteur de coût par appel que si une API est ensuite activée.
4. Préparer le dossier candidat et choisir un CV approuvé. Ne jamais inventer un diplôme, une autorisation de travail ou une expérience pour répondre au formulaire.
5. Remplir le formulaire dans Chrome, contrôler les champs obligatoires, les pièces jointes et les réponses avant l'envoi.
6. Pour les 15 premiers cas, attendre la vérification humaine. Pour les parcours validés ensuite, envoyer puis enregistrer une preuve de succès. En cas de résultat ambigu, marquer `à vérifier` et **ne pas retenter automatiquement**.

Le suivi privé doit distinguer au minimum `à examiner`, `prête`, `envoyée`, `à vérifier` et `bloquée`. Un identifiant unique et une seule tentative active par offre empêchent les doublons, y compris après interruption du programme. Un clic sur « Envoyer » ne suffit pas à prouver la réception de la candidature.

## Simplify et autres plateformes

L'extension Simplify peut aider au remplissage dans les fonctions qu'elle propose. Le pilotage automatisé du site ou du compte Simplify par un agent externe dépend d'une autorisation qui couvre **explicitement** cette activité. Le premier pilote peut travailler directement avec les formulaires des employeurs (Workday, Greenhouse, Lever et autres) sans dépendre de Simplify. CAPTCHA, contrôle anti-bot ou question légale inconnue entraînent un arrêt et une revue humaine.

## Étapes et critères de passage

1. **Dossier candidat privé** : faits vérifiés, CV approuvés, réponses standard et règles de choix.
2. **Historique et file locale** : importer les offres, rapprocher les confirmations des boîtes autorisées, vérifier que les offres déjà traitées ne reviennent pas.
3. **Évaluation du modèle** : tester les décisions avec les abonnements existants sur un échantillon relu par une personne, en sur-représentant les cas proches du seuil ; mesurer désaccords, temps et consommation des quotas avant de lui confier davantage de décisions. Une API payante ne sera évaluée que si ces limites gênent réellement le projet. Le prix et la vitesse d'un modèle local restent des hypothèses tant qu'ils ne sont pas mesurés sur la machine cible.
4. **Formulaires pilotes** : préparer des candidatures sur plusieurs plateformes, mesurer erreurs de remplissage et preuve de réception.
5. **Quinze envois contrôlés**, puis activation progressive de l'envoi automatique uniquement sur les parcours qui ont réussi sans ambiguïté.

Ce plan n'active aucun agent autonome et ne modifie ni la collecte ni les verdicts du bot existant.
