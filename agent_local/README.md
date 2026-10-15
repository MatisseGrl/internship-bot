# Agent local de candidatures

Ce répertoire contient le **moteur local** qui relie les offres du bot, un export du suivi Simplify, les décisions propres à chaque offre et les réponses par mail. Les CV, le profil personnel, les exports, la base SQLite et les sessions de navigateur restent hors du dépôt public.

## Partage du travail avec Claude

- **Codex** : base privée, rapprochement des sources, dossier par offre, file de travail, contrôle du CV, suivi des états, anti-doublons, rapprochement des mails et protocole de candidature dans Chrome.
- **Claude (autre branche ou copie)** : collecte et filtrage du bot public, fiabilité des textes d'annonce, `current.json`, `notation/notes.json`, et tests correspondants. Garder le format `current.json` version 1 avec `companies[*].jobs[*]` (`job_id`, `title`, `url`, `location`), et `notes.json` avec `offres` et `ecartees`. Si ce format change, fournir un exemple avant fusion.
- **Point de raccord** : `python agent_local/agent.py sync-bot --snapshot ... --notes ... --archives export.jsonl` ; la base conserve les candidatures et les mails lors des réimports. L'archive JSONL contient les clés `company`, `job_id`, `title`, `location`, `url`, `texte` (ou `erreur`).

## Flux réel

1. **Collecte** : `sync-bot` importe l'instantané du bot. `import-simplify` accepte le CSV « Export CSV » du Job Tracker ou un JSON équivalent. La source est rapprochée par URL canonique ou identifiant. Une ligne Simplify sans URL est conservée pour l'historique, mais ne peut pas déclencher une candidature.
2. **Tri** : `classer` sépare les inéligibilités explicites des offres qui nécessitent une lecture. Un rejet historique pour score faible n'est pas réutilisé comme rejet automatique. Les textes manquants vont en vérification.
3. **Analyse de l'offre** : `dossier` remet le texte, la note historique, les faits du CV et l'état de candidature. L'agent doit consulter l'annonce actuelle et produire une décision avec citation exacte, choix du CV et au moins un argument lié à cette offre. `decider` refuse une citation inventée ou un CV absent du profil.
4. **Formulaire** : Codex pilote Chrome à partir du dossier. L'état suit `prete_a_remplir` → `formulaire_en_cours` → `prete_a_envoyer` → `envoi_en_cours` → `envoyee`. Les 15 premières tentatives exigent une revue enregistrée. Un envoi incertain devient `a_verifier`, sans seconde tentative automatique. `envoyee` exige une preuve de réception.
5. **Mails** : `suivi_candidatures.py mail` enregistre chaque message par boîte et identifiant Gmail. Un statut ne change que si l'entreprise et l'identifiant de l'offre sont établis. `reconcilier` reporte ces statuts dans la file. Un accusé de réception ne peut pas effacer un refus ou un entretien.

L'utilisation de Chrome et la lecture quotidienne des deux boîtes sont assurées par la tâche Codex locale, pas par un accès Gmail ou Simplify caché dans ce programme. Le programme n'inclut **aucun appel d'API de modèle** et ne dépense rien. Le plafond de 10 USD par mois est représenté par `budget_disponible` avec arrêt local à 9 USD ; brancher un fournisseur exigera une clé hors dépôt et une mesure du coût réel.

## Alertes SWElist

`ingest_swelist.py` ajoute les annonces d'e-mails SWElist à un inventaire CSV privé. Il reçoit un JSON local contenant une liste d'objets `id`, `date` (`YYYY-MM-DD`), `subject` et `html` ; la lecture de Gmail reste en dehors du programme. L'import vérifie le nombre d'annonces indiqué dans l'objet, retire les paramètres de suivi des liens, dédoublonne par identifiant Simplify et applique un premier tri **indicatif** sur le titre. Il ne visite ni Simplify ni les sites des employeurs.

```powershell
python agent_local/ingest_swelist.py --messages-json C:\chemin\prive\nouveaux_mails.json --inventory C:\chemin\prive\swelist_inventaire.csv
```

Garder le JSON source et le CSV hors du dépôt public. Le tri du titre ne remplace pas la lecture de l'annonce officielle ni les règles d'éligibilité. Voir [la stratégie de tri](../docs/SOURCES_ET_TRI.md).

## Copie privée vers Supabase

`sync_supabase.py` copie les tables SQLite `offres`, `candidatures` et `mails` vers les tables correspondantes de Supabase. Il ne transmet pas le champ `cv`, le contenu des mails, le profil candidat ni les fichiers de CV. La clé secrète est lue dans `SUPABASE_SECRET_KEY`, l'URL du projet dans `SUPABASE_URL` ; aucune valeur réelle ne va dans Git. Garder le registre et le fichier d'état hors du dépôt.

```powershell
$env:SUPABASE_URL = 'https://VOTRE-PROJET.supabase.co'
$env:SUPABASE_SECRET_KEY = '<clé secrète saisie localement>'
python agent_local/sync_supabase.py --db C:\chemin\prive\suivi.sqlite
```

Le premier passage réécrit les lignes existantes par lots. Le fichier `sync_supabase.sqlite` créé à côté du registre mémorise chaque lot confirmé ; une relance ne renvoie que les lignes nouvelles ou modifiées. Les erreurs réseau temporaires sont réessayées, puis un échec arrête la commande avec un code non nul. Une réponse perdue peut entraîner le renvoi d'un lot, sans doublon grâce aux clés primaires. Après chaque passage, la commande contrôle les comptes des trois tables et des notes, textes et offres présentes dans l'instantané. Une perte de lignes distantes déclenche une réécriture complète. Les lignes distantes supplémentaires sont signalées et ne sont jamais supprimées automatiquement. `--full` force une vérification par réécriture intégrale quand le contenu distant a pu être changé directement sans modifier les comptes.

Pour une exécution régulière sur Windows, conserver la clé dans le magasin chiffré lié au compte Windows et utiliser le Planificateur de tâches. Les scripts de configuration propres au projet privé se trouvent hors de ce dépôt. Le compte Windows doit être connecté et le PC allumé pour que la tâche locale s'exécute.

## Configuration locale

Créer un profil JSON privé hors du dépôt, avec au minimum `faits`, `cv` et `connexion`, puis définir `INTERNBOT_PROFILE` vers ce fichier. Le profil de travail de Matisse est conservé dans le dossier Codex privé. La base est par défaut `agent_local/suivi.sqlite`, ignorée par Git ; `--db` permet de choisir un autre emplacement privé.

Exemples :

```powershell
python agent_local/agent.py --db C:\chemin\prive\suivi.sqlite sync-bot --snapshot C:\chemin\current.json --notes C:\chemin\notes.json
python agent_local/agent.py --db C:\chemin\prive\suivi.sqlite import-simplify C:\chemin\export.csv
python agent_local/agent.py --db C:\chemin\prive\suivi.sqlite classer
python agent_local/agent.py --db C:\chemin\prive\suivi.sqlite file
python agent_local/agent.py --db C:\chemin\prive\suivi.sqlite dossier Microsoft 200061386
```

`decider` lit une décision JSON :

```json
{
  "etat": "prete_a_remplir",
  "raison": "Correspondance entre les missions décrites et un projet vérifié",
  "citation_annonce": "citation exacte de l'annonce",
  "cv": "nom du CV défini dans le profil privé",
  "justification_cv": "pays, dates, langue et exigences de cette offre",
  "arguments": [
    {
      "citation_annonce": "autre citation exacte de l'annonce",
      "fait_cv": "identifiant d'un fait du profil privé",
      "usage": "comment ce fait répond à cette mission précise"
    }
  ]
}
```

## État et limites au 15 octobre 2026

- Les fonctions locales et les tests d'anti-doublon, de transitions et de suivi mail fonctionnent ; aucun formulaire n'est envoyé par ce code.
- Une répétition générale sur une **copie** de la base réelle a mis l'offre Microsoft Dublin `200061386` en tête comme `action_requise`.
- Le connecteur Simplify attend un export de Job Tracker ; il faut vérifier les intitulés réels de ses colonnes avec le premier export. La documentation officielle décrit la fonction [Export CSV](https://help.simplify.jobs/help/articles/2140179-using-the-job-tracker).
- Il reste à tester des parcours Chrome de bout en bout sur plusieurs plateformes, à vérifier les réponses rédigées sur les 15 premiers cas et à raccorder la tâche quotidienne à cette version du moteur. L'agent n'est pas encore prêt à envoyer des centaines de candidatures sans supervision.
