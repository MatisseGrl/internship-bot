# Idées à réaliser — suivi des candidatures lié au bot

État au 15 octobre 2026 : **spécification pour une prochaine étape**. Le bot collecte et note les offres ; l'envoi et le suivi complet décrits ici ne sont pas encore automatisés. Le registre privé existant reste local. Une copie vers Supabase est synchronisée sur le PC ; l'interface de consultation reste à construire.

## Lien entre le bot et les candidatures

- Importer chaque offre du bot avec sa clé stable (entreprise + identifiant), son URL, son texte, les quatre notes, le score, le verdict et la date de dernière observation.
- Garder séparés le **verdict sur l'offre**, l'**état de la tentative de candidature** et le **résultat du recrutement**. Une offre bien notée n'est pas une candidature envoyée.
- Dédupliquer les offres venant du bot et d'autres sources avant toute tentative. Conserver l'historique même si l'offre disparaît du dernier instantané du bot.
- Conserver les événements horodatés (ouverture du formulaire, choix du CV, problème de connexion, clic d'envoi, mail de confirmation, réponse du recruteur) et la preuve associée. Les CV, courriels, jetons et données personnelles restent hors du dépôt public.

## États à afficher dans le tableau de suivi

| État | Signification |
| --- | --- |
| `a_examiner` | Offre importée, candidature non commencée. |
| `prete` | Candidature préparée ; attendre la revue humaine pendant les 15 premiers essais ou si le parcours n'est pas validé. |
| `en_cours` | Formulaire en train d'être rempli. |
| `echec_technique` | Impossible de poursuivre : connexion Google, session expirée, formulaire cassé, pièce jointe refusée, etc. Enregistrer la cause et passer à l'offre suivante. |
| `temps_depasse` | Limite de temps atteinte ; tentative interrompue et reprise éventuelle différée. |
| `envoi_non_confirme` | Le formulaire semble soumis, mais aucun mail de confirmation fiable n'a été rapproché. Ne pas retenter automatiquement. |
| `envoyee` | Un mail de confirmation de candidature a été vérifié et rattaché sans ambiguïté à l'offre. |
| `en_attente` | Candidature confirmée, réponse du recruteur encore attendue. |
| `reponse_positive` | Entretien, test ou autre suite favorable demandée ; action et échéance à afficher. |
| `refusee` | Refus explicite reçu. |
| `a_verifier` | Mail ou résultat de formulaire ambigu ; examen humain nécessaire. |

Ces états sont un vocabulaire de travail. Le schéma final devra distinguer une tentative d'envoi du résultat ultérieur pour conserver toute la chronologie : `envoyee` puis `en_attente` puis `reponse_positive` ou `refusee`.

## Temps maximal par offre — à déterminer par les tests

- Les **5 minutes en moyenne** et le **seuil de 8 minutes** cités en discussion étaient des exemples, pas des valeurs validées.
- Mesurer la durée réelle des premiers parcours sur chaque plateforme, y compris connexion et blocages. Définir ensuite un plafond configurable, éventuellement différent selon le site et le type de formulaire.
- Quand le plafond choisi est atteint, interrompre la tentative, enregistrer `temps_depasse`, l'étape atteinte, le temps passé et la cause observée, puis passer à l'offre suivante. Ne pas rester bloqué sur la même offre toute la nuit. L'attente du mail de confirmation se fait séparément et ne bloque pas la file.
- Si le clic final a peut-être eu lieu, utiliser `envoi_non_confirme` ou `a_verifier` plutôt que `temps_depasse` seul ; ne jamais renvoyer automatiquement une candidature possiblement soumise.
- Réévaluer le seuil à partir des résultats des tests et des cas réellement rencontrés.

## Rapprochement avec les mails

- Vérifier périodiquement les boîtes explicitement autorisées et classer les messages utiles : confirmation, demande d'action, entretien/test, refus, message ambigu.
- Rattacher un mail à une offre avec les indices disponibles (entreprise, identifiant, intitulé, URL, date, compte destinataire). Un simple nom d'entreprise ne suffit pas si plusieurs offres y sont en cours.
- Selon la règle décidée pour ce projet, **ne passer à `envoyee` qu'après vérification d'un mail de confirmation correspondant**. Le clic sur « Postuler », une page de remerciement ou l'absence d'erreur ne suffisent pas.
- Si aucun mail ne vient, garder `envoi_non_confirme` et signaler le cas pour vérification ; ne pas déduire un échec ni refaire l'envoi automatiquement.
- Mettre à jour le résultat quand un mail ultérieur annonce une suite positive, un refus ou une action requise. Garder l'identifiant du message et la justification pour éviter les doublons et permettre une revue.
- Si l'accès à une boîte échoue, enregistrer un incident de connexion et signaler que cette boîte n'a pas été vérifiée. Ne pas présenter le suivi comme complet pendant cet incident.

## Vérifications avant automatisation large

1. Relire les 15 premières candidatures avant envoi et mesurer la durée, les erreurs et le taux de confirmations par mail.
2. Tester les échecs Google, les formulaires longs, les interruptions et les mails ambigus. Vérifier qu'un incident laisse une trace et libère la file.
3. Vérifier que l'import du bot et le scan des mails sont idempotents : une même offre ou un même mail ne crée ni doublon ni deuxième envoi.
4. Activer l'envoi automatique uniquement pour les parcours déjà validés ; garder les nouveaux formulaires et réponses inconnues en attente de revue.

Ce document décrit les fonctions à construire et leurs critères de contrôle. Il n'active aucun envoi automatique.
