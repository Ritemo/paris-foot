# Combinés Foot

Appli PWA (GitHub Pages) qui propose 2 à 3 combinés football par jour avec chance estimée, note, mise conseillée de 1 à 5 € et suivi juste/faux. Robot Python sur GitHub Actions. Détails dans le README.

## Qui je suis et comment je travaille

- Mathieu Cognard. Je ne suis pas développeur : je décris ce que je veux, Claude code, teste et pousse.
- Je travaille surtout depuis mon téléphone (sessions cloud Claude Code), avec un abonnement Claude Pro : économise le quota (pas de relectures inutiles de gros fichiers, pas d'outils qui consomment des tokens en arrière-plan).
- Réponds en français, simplement, sans jargon. Jamais de tiret cadratin (caractère U+2014), ni dans les réponses ni dans les fichiers.
- Uniquement des outils et services gratuits (GitHub Actions, GitHub Pages, Google Sheets, ntfy...). Si quelque chose de payant semble nécessaire, demande d'abord.
- Pousse directement sur `main` une fois les tests passés. Pas de branche ni de pull request sauf si je le demande.
- Tu peux prendre les décisions de design et proposer des améliorations : je valide ou corrige ensuite.
- Le README est écrit pour quelqu'un qui reprendrait le projet sans savoir coder : mets-le à jour quand le fonctionnement change.

## Vérifier avant de pousser

- Lance les tests du dépôt (voir ci-dessous).
- Pour toute modification d'interface, ouvre l'appli avec Playwright (MCP déclaré dans `.mcp.json`) au format téléphone (390 x 844) et vérifie l'affichage, puis au format ordinateur si l'appli s'utilise aussi sur PC.
- Pense au cache du service worker (`sw.js`) : change sa version quand les fichiers de l'appli changent, sinon les téléphones gardent l'ancienne.

## Règles propres à ce projet

- Tests : `python tests/test_robot.py` puis `python tests/test_app.py` (appli testée avec Playwright), et `node --check` sur les fichiers JS de `docs/`. L'appli est dans `docs/`.
- Je parie sur Unibet. The Odds API en offre **gratuite** (secret `ODDS_API_KEY`) : chaque appel coûte des crédits, ne jamais ajouter d'appels payants sans vérifier le budget de crédits (modes économe sous 40, arrêt sous 12).
- Pas de scraping d'Unibet (conditions d'utilisation). Historique : football-data.co.uk (gratuit).
- Objectif : un outil d'aide qui évite les pièges, pas une promesse de gain. Le bookmaker gagne sur le long terme ; j'accepte un ROI légèrement négatif si le combiné reste assez probable.
- Combinés de préférence à 3 sélections, mêlant 1N2, nombre de buts et handicap. Cotes approximatives acceptables : je peux les corriger dans l'appli.
- Budget mensuel indicatif, non bloquant. Garder l'onglet de métriques pour améliorer le modèle en continu.
