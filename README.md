# Combinés Foot

Appli (PWA) qui propose 2 à 3 combinés football par jour de match, avec la chance estimée de chaque combiné, son coût (marge des bookmakers), une note en étoiles, une mise conseillée de 1 à 5 € et le suivi juste/faux.

- **Championnats** : Ligue 1, Premier League, Liga, Serie A, Bundesliga
- **Cotes** : 1N2 Unibet France, nombre de buts PMU (à vérifier sur Unibet), handicap estimé (à saisir dans l'appli)
- **Robot** : GitHub Actions vers 8h et 17h, ou à la demande avec le bouton ↻ de l'appli
- **Crédits The Odds API** : environ 10 par passage les jours de match, 0 les jours sans match. Le robot passe automatiquement en mode économe sous 40 crédits restants, et ne fait plus d'appel payant sous 12.

## Installation (une seule fois)

1. **Créer le dépôt** sur GitHub : nom `paris-foot`, **public** (GitHub Pages gratuit).
2. **Envoyer les fichiers** : sur la page du dépôt, *Add file > Upload files*, glisser tout le contenu du dossier (y compris le dossier `.github`), puis *Commit changes*.
3. **Ajouter la clé API** : *Settings > Secrets and variables > Actions > New repository secret*, nom `ODDS_API_KEY`, valeur = ta clé The Odds API.
4. **Activer les pages** : *Settings > Pages*, Source *Deploy from a branch*, branche `main`, dossier `/docs`.
5. **Premier passage du robot** : onglet *Actions > Robot > Run workflow*. Au bout de 2 à 3 minutes, l'appli est à l'adresse `https://<ton-compte>.github.io/paris-foot/`.

## Bouton ↻ (actualiser depuis l'appli)

1. Sur GitHub : *Settings (de ton compte) > Developer settings > Personal access tokens > Fine-grained tokens > Generate new token*.
2. *Repository access* : seulement `paris-foot`. *Permissions > Actions* : **Read and write**. Rien d'autre.
3. Copier le jeton dans l'onglet **Réglages** de l'appli. Il reste stocké sur ton téléphone uniquement.

Chaque actualisation manuelle coûte environ 10 crédits les jours de match.

## APK Android

Comme pour l'appli hand : coller l'adresse de l'appli sur pwabuilder.com, puis *Package for stores > Android*.

## Fonctionnement

- Le modèle (Poisson pondéré, buts et tirs cadrés, données football-data.co.uk) est mélangé à 20 % avec les probabilités des bookmakers, réglage validé par le backtest sur 2 400 matchs.
- Les combinés du jour J restent provisoires la veille, puis sont **figés au premier passage du jour J** pour que le bilan soit honnête.
- Résultats : football-data.co.uk en priorité, sinon l'API (2 crédits) si assez de crédits restent.
- Tes paris joués, tes cotes corrigées et ton budget sont enregistrés sur ton téléphone.

Rappel du backtest : aucune stratégie testée ne bat durablement les bookmakers. Les combinés de 2 favoris sont simplement les moins coûteux. Joue pour le plaisir et dans ton budget.
