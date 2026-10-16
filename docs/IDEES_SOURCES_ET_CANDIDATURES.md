<!-- Copie publiable des notes de Codex du 15/10/2026 : adresse e-mail, chemins locaux et noms de fichiers privés retirés. -->

# Idées à conserver — sources, filtres et parcours de candidature

15 octobre 2026. Notes issues de la demande de Matisse ; ce document consigne des hypothèses à vérifier, pas des candidatures lancées.

## Sources d'offres

1. Le bot personnel et son registre existant (`suivi.sqlite`, synchronisé vers Supabase).
2. Les e-mails quotidiens d'alertes de stages, notamment SWE List / SWElist (`noreply@swelist.com`, exemple « 66 New Internships Posted Today », reçu le 15 octobre). Ne pas confondre l'expéditeur SWElist avec Simplify : le message mentionne et lie Simplify, mais la source de ce courriel est SWElist. Vérifier aussi les autres alertes reçues dans les deux boîtes autorisées.

Recenser toutes les annonces et leurs liens depuis ces alertes, avec la provenance, la date du mail et l'identifiant du message. Rapprocher les doublons avec le bot et l'historique des candidatures. Ne pas traiter 1 000 annonces comme 1 000 candidatures à envoyer.

## Filtrage en plusieurs étapes

1. Premier passage peu coûteux sur **entreprise + intitulé uniquement**, pour écarter les métiers clairement hors cible (audit, hardware pur, poste doctorant si non éligible, etc.). Conserver les cas ambigus ; un titre seul ne prouve pas l'éligibilité.
2. Lire les métadonnées déjà disponibles (pays, dates, niveau, famille de métier) et appliquer les exclusions certaines, notamment la période de stage et les conditions de travail/visa.
3. Pour les offres restantes, réutiliser d'abord le texte déjà présent dans le bot ou dans le mail. Enrichir seulement les manquantes par la page d'annonce. Le « Ctrl+A » sur une page Simplify est une piste pour obtenir le texte visible ; vérifier si le texte complet est réellement accessible et si cette méthode respecte les conditions du site. Le coût en tokens d'une reclassification intégrale de milliers de textes serait à mesurer avant toute généralisation.
4. Envisager des **embeddings** pour préclasser ou rechercher les offres proches du profil après les filtres simples. Tester sur un échantillon étiqueté ; les embeddings ne doivent pas décider seuls de l'éligibilité ni remplacer la lecture des questions du formulaire. Comparer coût, rappel et faux rejets avec des règles simples et une classification courte.
5. Dédupliquer, classer et plafonner le nombre de dossiers à préparer par jour. Garder une file priorisée, avec états `à examiner`, `hors cible`, `à vérifier`, `prête`, `envoyée`, `bloquée`.

## Parcours proposé pour une offre retenue

Le mail d'alerte peut mener en premier clic à une page d'annonce Simplify. Le bouton « Apply » peut mener en second clic au formulaire de l'entreprise. Exemple fourni : `https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2506918?utm_source=Simplify` (Oracle Candidate Experience, offre 2506918 ; vérifier l'entreprise et l'annonce sur la page avant usage). Les captures montrent une annonce onsemi « Semiconductor AI Specialist Intern » à Gresham, Oregon, été 2027, et une fenêtre Simplify proposant de compléter le profil ou « Apply Anyway ». Ce parcours observé sur une annonce ne garantit pas que tous les liens suivent deux clics ni que l'extension Simplify fonctionne sur Oracle.

Sur le site employeur : lire l'annonce officielle et les conditions, vérifier l'historique anti-doublon, préparer réponses et CV approprié, présenter la candidature à Matisse pour relecture (règle des 15 premiers envois), puis enregistrer la preuve de confirmation. Si site, connexion, CAPTCHA, droit au travail ou question inconnue bloque, classer le cas sans inventer de réponse ni réessayer un envoi ambigu.

## Vérifications demandées

- Confirmer l'accès en lecture aux e-mails d'alerte et extraire les vrais liens des annonces, sans cliquer sur « Unsubscribe » ni transférer le message.
- Déterminer ce que donne exactement le lien Oracle fourni et si la description complète est accessible sur la page officielle.
- Vérifier si l'extension Simplify est installée et utilisable par l'outil de navigateur. Un compte Simplify ouvert, une capture de son site et la mention d'une extension dans un mail ne prouvent pas l'accès à l'extension. Distinguer Simplify Copilot (aide au remplissage) de Simplify Autopilot (envoi sur certains sites).
- Vérifier les conditions d'accès automatisé de Simplify avant toute interaction automatisée avec son site ; documenter une autre voie via les liens des employeurs si nécessaire.

## État au moment de la note

Vérifié en lecture le 15 octobre : le mail « 66 New Internships Posted Today » est présent dans la boîte Gmail personnelle avec **66 liens d'annonces Simplify distincts**. Des mails analogues des jours précédents sont aussi présents. Les liens sont encodés directement dans le HTML du mail : l'ingestion des intitulés et URL ne nécessite aucun clic ni « Ctrl+A » sur Simplify.

Inventaire ponctuel réalisé : **49 mails SWElist** du 26 août au 15 octobre, **3 587 liens distincts** ; les nombres annoncés dans les objets des 49 mails correspondent aux liens trouvés. L'inventaire CSV privé conserve date, identifiant de mail, entreprise, titre, URL et premier tri. Le filtre provisoire par titre donne **468 à écarter probablement**, **1 020 à revoir** et **2 099 à retenir pour une étape suivante**. Ces catégories ne constituent pas encore des décisions de candidature. Sur les 29 mails du 16 septembre au 15 octobre, on compte 1 602 couples entreprise/titre uniques parmi 1 834 annonces : plusieurs intitulés reviennent sur des annonces distinctes. Un rapprochement strict entreprise/titre des **49 mails** avec la base du bot trouve seulement 45 lignes ; il ne suffit pas pour la déduplication, qui devra utiliser l'URL ou l'identifiant de l'offre employeur. Aucune des 45 correspondances strictes n'est l'une des trois candidatures déjà enregistrées.

La page Oracle fournie est bien l'annonce officielle onsemi `2506918`, intitulée « Spring 2027 - Semiconductor AI Specialist Intern », à Gresham (Oregon). Elle affiche la description complète, les responsabilités AI/VLSI et l'exigence de Master ou doctorat en génie électrique ou domaine technique pertinent. Le bouton « Apply Now » ouvre la candidature ; il n'a pas été cliqué ici. Le nom seul semblait compatible avec l'IA, mais le texte montre un fort accent sur la physique des semi-conducteurs et le VLSI : exemple utile d'offre à conserver au premier filtre puis à réévaluer au second.

**Extension Simplify vérifiée sur la page Oracle dans Chrome** : un panneau « Simplify » est présent avec `Autofill`, `Resume Score`, `Profile`, `Job details` et un CV enregistré. Cela prouve l'accès visuel au panneau sur cette page, pas que l'Autofill réussira ni que l'agent peut envoyer une candidature sans relecture. Le score affiché pour cette offre est faible (1 mot-clé sur 5) ; il ne suffit pas à lui seul pour décider.

Aucune de ces nouvelles annonces n'a été ajoutée au registre ou postulée dans cette étape. Aucun clic d'envoi n'est autorisé par cette note.

La vérification quotidienne existante de 8 h (Paris) a été mise à jour pour rechercher les nouveaux mails SWElist et ajouter leurs annonces au CSV sans doublon, tout en conservant le suivi des candidatures. Elle utilise `agent_local/ingest_swelist.py`, qui extrait les annonces du HTML, vérifie le compte annoncé dans l'objet, applique le premier tri, écrit le CSV de façon atomique et évite les doublons par identifiant de lien. Un essai local a confirmé l'idempotence et le refus d'un mail dont le nombre d'annonces ne correspond pas ; les 3 587 lignes actuelles donnent toutes le même résultat de filtre avec ce script. La première exécution programmée avec cette nouvelle consigne reste à observer ; la collecte ponctuelle des 49 mails disponibles dans cette boîte est déjà terminée.

## Étape suivante : modèle de tri sélectif (discussion du 15 octobre)

L'instantané actuel du bot contient **449 offres déjà gardées** et **748 offres non notées**. Parmi ces 748, **11 seulement ont un texte d'annonce de plus de 100 caractères** ; l'acquisition de descriptions fiables est donc le principal manque pour une notation complète. Les notes historiques comprennent **2 460 offres écartées** et **519 gardées**, mais 1 255 rejets reposent sur un motif d'éligibilité ou de période, et 126 offres gardées ont un texte inaccessible : un entraînement binaire naïf « écartée contre gardée » serait trompeur. On dispose en revanche de **872 exemples Fit rôle = 1** et d'environ **518 exemples Fit rôle ≥ 3**, plus adaptés à un modèle de présélection par titre.

Proposition : utiliser d'abord des règles certaines (recherche exclue selon la préférence du 11 octobre, PhD exclusivement, métier clairement hors cible), puis comparer sur le même jeu de test un modèle léger de titres (TF-IDF caractères/mots + régression logistique) et une variante avec embeddings. Séparer les entreprises et les titres quasi identiques entre entraînement et test. Choisir un seuil qui minimise les bonnes offres rejetées ; la sortie doit être **écarter avec forte confiance / prioriser / à lire**, pas un verdict de candidature. Faire relire un échantillon de rejets et de cas incertains par Matisse avant d'automatiser l'exclusion. Les embeddings peuvent améliorer les formulations nouvelles ou bilingues, mais ne décident pas des dates, visas ou questions du formulaire. Récupérer le texte officiel seulement pour les offres qui survivent et appliquer alors la grille existante, avec preuves.

Pour postuler rapidement, partir d'abord des 449 offres déjà gardées, éliminer les doublons et les annonces closes, vérifier dates/droit au travail, puis préparer une courte file à relire. La construction du classifieur ne doit pas retarder ces premiers dossiers.

## Réalisation : source SWElist séparée et premier test ML

Le 15 octobre, les **3 587** annonces SWElist ont été chargées dans une table `swelist_annonces` distincte de `offres`, d'abord dans SQLite puis dans Supabase. Les 3 909 lignes du bot sont inchangées. Il y a 35 correspondances uniques et 10 ambiguës par entreprise/titre ; ce sont des indices de doublon, pas des fusions confirmées. La colonne `label_humain` permet une correction future sans écraser la note historique, et `score_fit`/`verdict_ml` gardent la sortie du modèle. L'import est idempotent, et la synchronisation programmée copie désormais aussi cette table. Une sauvegarde SQLite antérieure à l'import a été conservée dans le dossier privé de l'agent.

Un modèle local et gratuit TF-IDF + régression logistique a été entraîné sur **Fit rôle = 1** contre **Fit rôle ≥ 3**, avec apprentissage/validation/test séparés par entreprise. Les intitulés normalisés identiques sont dédoublonnés et les étiquettes contradictoires retirées. Sur le test : 287 titres, dont 94 positifs ; AUC 0,887 ; 30 des 35 titres priorisés sont pertinents. Mais la zone de basse priorité contient 7 titres pertinents sur 94 : ce seuil créerait **7,4 % de faux rejets** si on l'utilisait pour exclure. Il n'y a donc **aucun rejet automatique**. Répartition actuelle des alertes : 1 162 à prioriser, 1 679 à lire, 746 en basse priorité **à relire**. Le premier filtre par règles du CSV est conservé séparément.

Les résultats détaillés, les erreurs du test et un échantillon de revue privé contiennent 70 annonces à annoter avec `label_humain = 1` (métier pertinent) ou `0` (hors métier). Cet audit SWElist n'entre pas automatiquement dans l'entraînement ; il servira à mesurer le décalage entre sources et à décider si un modèle plus élaboré ou des embeddings sont justifiés. Ces fichiers restent privés et hors de GitHub.
