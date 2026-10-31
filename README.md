# Combinés Foot

Appli (PWA) qui propose 2 à 3 combinés football par jour de match, avec la chance estimée de chaque combiné, son coût (marge des bookmakers), une note en étoiles, une mise conseillée de 1 à 5 € et le suivi juste/faux.

- **Championnats** : Ligue 1, Premier League, Liga, Serie A, Bundesliga, et Ligue des champions (probabilités des bookmakers seules, pas d'historique football-data)
- **Cotes** : 1N2 Unibet France, nombre de buts PMU (à vérifier sur Unibet), handicap estimé (à saisir dans l'appli)
- **Robot** : GitHub Actions toutes les heures, de 6 h à minuit environ (résultats, gratuit) ; les cotes (payantes en crédits) seulement au premier passage après 7 h 30 et après 16 h 30, heure de Paris ; ou à la demande avec le bouton ↻ de l'appli
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

## Tests

Avant chaque publication : `./tools/check.sh` (numéro de version automatique, syntaxe, tests du robot et test de l'appli dans Chromium, sans réseau ni crédit).
Les mêmes tests tournent sur GitHub à chaque modification de l'appli ou du robot, avec une notification ntfy en cas d'échec.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `robot/run.py` | Le robot : cotes, combinés du jour, résultats, historique et bilan. |
| `robot/model.py` | Modèle de Poisson pondéré (scores probables). |
| `robot/teams.py` | Correspondance des noms d'équipes entre The Odds API et football-data. |
| `docs/` | L'appli (servie par GitHub Pages) : `index.html`, `app.js`, `compose.js`, `live.js`, `style.css`, `sw.js`. |
| `docs/data/` | Données écrites par le robot : `today.json` (combinés du jour), `history.json` (bilan), `meta.json` (crédits restants, derniers passages), `odds_cache.json`. |
| `tools/check.sh` | Vérification complète avant publication. |
| `tools/bump_version.py` | Change le numéro de version pour que les téléphones prennent la nouvelle appli. |
| `.github/workflows/robot.yml` | Horaires du robot. |
| `.github/workflows/tests.yml` | Tests à chaque modification de l'appli ou du robot. |

## Réglages GitHub

| Nom | Où | Valeur |
|---|---|---|
| `ODDS_API_KEY` | *Settings > Secrets and variables > Actions* | Clé The Odds API. |
| Pages | *Settings > Pages* | Branche `main`, dossier `/docs`. |
| Jeton du bouton ↻ | Dans l'appli, onglet Réglages | Jeton GitHub « fine-grained », accès `paris-foot` seulement, *Actions : Read and write*. |

Notifications d'échec des tests : sujet ntfy `combines-foot-ritemo-7k3q9x`.

## Modifier l'appli

1. Modifier les fichiers de `docs/` (ou `robot/`).
2. Lancer `./tools/check.sh` (numéro de version, syntaxe, tests sans réseau ni crédit).
3. Déposer les fichiers. Les tests repassent sur GitHub ; en cas d'échec, une notification part sur ntfy.

## Dépannage

| Symptôme | Où regarder |
|---|---|
| Pas de combinés du jour | *Actions > Robot > dernier passage*. Vérifier aussi `docs/data/meta.json` : `credits_remaining` sous 12 = plus d'appel payant jusqu'au renouvellement mensuel des crédits. |
| Le bouton ↻ ne fait plus rien | Le jeton GitHub a expiré (les jetons « fine-grained » ont une date de fin) : en générer un nouveau et le recoller dans Réglages. |
| Erreur 401 dans les logs du robot | Clé The Odds API invalide ou changée : mettre à jour le secret `ODDS_API_KEY`. |
| Une équipe n'est pas reconnue | Ajouter la correspondance de nom dans `robot/teams.py`. |
| Résultats manquants | football-data.co.uk publie parfois avec un jour de retard ; le robot réessaie à chaque passage. |
| Le téléphone garde une ancienne version | Fermer et rouvrir l'appli ; si besoin, vérifier que `tools/bump_version.py` a bien été lancé avant la publication. |

## Limites gratuites

- **The Odds API** : quota mensuel de l'offre gratuite. Le robot passe en mode économe sous 40 crédits et s'arrête sous 12.
- **GitHub Actions** : illimité pour un dépôt public.
- **GitHub** désactive les tâches programmées d'un dépôt sans activité pendant 60 jours ; les commits du robot gardent le dépôt actif tant qu'il y a des matchs. Après une longue pause, réactiver le robot dans *Actions*.
