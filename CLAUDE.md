# Combinés Foot

Appli PWA (GitHub Pages) qui propose chaque jour les meilleurs combinés (foot des 5 grands championnats et coupes d'Europe, NBA, tennis ATP/WTA) avec chance estimée, note d'intérêt, mise conseillée et suivi juste/faux. Robot Python sur GitHub Actions (passage complet à 7h30, actualisation à 16h30, résultats toutes les 15 min via cron-job.org). Détails dans le README.

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
- Je parie sur Unibet. Sources de cotes, toutes gratuites :
  - The Odds API (secret `ODDS_API_KEY`, 500 crédits/mois) : relevé complet du matin (1N2 Unibet, buts PMU, NBA, tennis). Chaque appel coûte des crédits : ne jamais en ajouter sans vérifier le budget (économe sous 40, arrêt sous 12).
  - OddsPapi (secret `ODDSPAPI_KEY`, 250 requêtes/mois, arrêt à 230) : seulement le 1N2 Unibet, pour les actualisations (16h30, ballon) et en secours.
  - ESPN (gratuit, non officiel) : scores, direct, cotes NBA de référence, logos.
- Pas de scraping d'Unibet, ni de son offre internationale (conditions d'utilisation). Historique : football-data.co.uk (gratuit).
- Objectif : un outil d'aide qui évite les pièges, pas une promesse de gain. Le bookmaker gagne sur le long terme ; j'accepte un ROI légèrement négatif si le combiné reste assez probable.
- Note d'intérêt = prix (marge du bookmaker) + ressemblance avec mon style de jeu (cote visée, réglable dans l'appli). Le robot propose les meilleurs combinés de 2 ou 3 sélections, un sport par ticket ; les tickets multisport seulement si je les demande (interrupteur).
- Cotes non Unibet (PMU, estimées) : l'appli me demande la vraie cote quand je joue ; le robot apprend de ces corrections.
- Budget mensuel indicatif, non bloquant. Garder l'onglet de métriques pour améliorer le modèle en continu.
