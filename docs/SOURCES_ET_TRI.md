# Deux sources d'offres et tri sélectif

Le bot public et les alertes de stages reçues par e-mail sont deux sources distinctes. Les messages SWElist contiennent directement les entreprises, intitulés et liens Simplify. L'inventaire et les identifiants des e-mails sont privés ; seuls le code et cette méthode sont publiés ici.

## Parcours recommandé

1. Recenser chaque annonce avec sa source, sa date et son URL ; dédoublonner d'abord les liens exacts, puis rapprocher avec le bot par URL ou identifiant de l'offre employeur. Un même couple entreprise/titre peut correspondre à plusieurs offres.
2. Utiliser le titre pour **prioriser** la lecture et écarter les cas manifestement hors cible. Les intitulés ambigus restent à vérifier. Le premier tri ne décide pas d'une candidature.
3. Pour les offres prioritaires, récupérer la description officielle, le lieu, les dates, le niveau demandé et les conditions de droit au travail. Réutiliser les textes déjà présents dans le bot avant tout nouvel accès au site.
4. Appliquer la grille existante aux missions réelles, avec les citations exigées, puis vérifier l'éligibilité et l'historique des candidatures. Préparer une courte file pour la revue humaine prévue pendant les quinze premiers envois.

## Classifieur éventuel

Les refus historiques ne forment pas tous une même classe d'entraînement : certains résultent du métier, d'autres de dates, de nationalité ou de niveau, impossibles à inférer d'un titre. Les annonces gardées faute de texte ne sont pas non plus des exemples positifs fiables. Pour un modèle de titres, utiliser plutôt les notes **Fit rôle = 1** comme négatifs et **Fit rôle >= 3** comme positifs, avec audit des étiquettes.

Comparer sur le même jeu de test une base légère TF-IDF + régression logistique et des embeddings de titres. Séparer les entreprises et les intitulés quasi identiques entre entraînement et test pour éviter une mesure artificiellement favorable. Le modèle doit pouvoir s'abstenir : `écarter avec forte confiance`, `prioriser`, `à lire`. Mesurer en premier les offres pertinentes rejetées, puis faire relire un échantillon des rejets par l'utilisateur. Les embeddings peuvent améliorer les variantes de formulation ; ils ne répondent pas aux questions de dates, de visa ou de formulaire.

Ne pas attendre ce modèle pour les premiers dossiers : les offres déjà retenues par la grille sont le point de départ naturel. Vérifier qu'elles sont encore ouvertes et que leurs conditions sont compatibles avant toute tentative.
