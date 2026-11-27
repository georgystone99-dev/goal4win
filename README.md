# Goal4win — version 1.0

Première interface PWA statique de Goal4win. Elle comprend l'identité visuelle, le calendrier J-10 à J+2, trois sélections indépendantes avec contenu de démonstration, les emplacements légaux/publicitaires et les fichiers PWA.

## Tester en local

Le service worker nécessite HTTP/HTTPS. Depuis ce dossier, lancez par exemple :

```bash
python -m http.server 8000
```

Puis ouvrez `http://localhost:8000`.

## Publier avec GitHub Pages

1. Connectez-vous à GitHub et créez un dépôt public nommé `goal4win`.
2. Envoyez tous les fichiers et dossiers de ce projet à la racine du dépôt (notamment `index.html`, `styles.css`, `app.js`, `manifest.webmanifest`, `sw.js` et `assets/`).
3. Dans le dépôt, ouvrez **Settings → Pages**.
4. Dans **Build and deployment**, choisissez **Deploy from a branch**.
5. Sélectionnez la branche `main` et le dossier `/ (root)`, puis cliquez sur **Save**.
6. Après le déploiement, GitHub affichera l'adresse publique du site, généralement `https://VOTRE-PSEUDO.github.io/goal4win/`.

## Personnalisation

- `app.js` : exemples de matchs, pronostics, dates et catégories.
- `styles.css` : couleurs, dimensions, typographie et mise en page.
- `assets/goal4win-background.png` : illustration BASIGEO 237 utilisée dans le hero.
- `manifest.webmanifest` : nom et paramètres d'installation PWA.

## Générer les pronostics

Le script `generate_pronos.py` analyse les matchs de J et J+1 avec les données gratuites de football-data.org : classement actuel et cinq derniers résultats de chaque équipe. Il attribue un score statistique au meilleur pari parmi Total +1,5, Total +2,5, Total -3,5, Vainqueur, Double Chance 1X/X2 et Double Chance 12, puis présélectionne au plus cinq matchs par jour.

The Odds API n'est appelée qu'après cette présélection. L'endpoint gratuit des événements associe les rencontres par équipes et heure de début ; un seul marché de cotes, celui du pari retenu, est ensuite demandé par match. Si Football-Data.org ne permet d'analyser aucun match pour J ou J+1, un mode de secours vérifie les compétitions complémentaires actives (Europa League, Conference League, Süper Lig, First Division A et NBA) via les endpoints gratuits `/sports` et `/events`, puis limite les vérifications payantes `/odds` à trois au total pour cette exécution de secours, sur le marché `h2h`. Les cotes admissibles, en mode principal comme en secours, vont de 1,15 à 1,65 inclus. Elles sont publiées dans les panneaux `PRONOS 1`, `PRONOS 2` et `PRONOS 3` (jusqu'à cinq sélections par jour). Les lignes de J−10 à J+2 sont conservées et seules celles antérieures à J−10 sont purgées.

1. Installez les dépendances : `python -m pip install -r requirements.txt`.
2. Définissez `FOOTBALL_DATA_API_KEY` avec une clé football-data.org et `ODDS_API_KEY` avec votre clé The Odds API. Dans GitHub Actions, configurez-les comme secrets `FOOTBALL_DATA_API_KEY` et `ODDS_API_KEY`. Si la clé football-data.org manque, le script affiche une information et termine sans appeler les API ni modifier Sheets.
3. Pour prévisualiser sans modifier la feuille : `python generate_pronos.py --dry-run`. Avec les deux clés configurées, le dry-run appelle les API et peut consommer des crédits de cotes pour les matchs présélectionnés.
4. Pour publier, configurez un compte de service Google Sheets avec accès éditeur à la feuille. Fournissez le JSON du compte dans `GOOGLE_CREDENTIALS_JSON` ou placez-le dans `credentials.json` à la racine, puis lancez `python generate_pronos.py`.
5. Pour actualiser les scores et résultats des rencontres en attente : `python generate_pronos.py --update-results`.

Le script utilise par défaut la feuille déjà lue par la PWA et son premier onglet. `GOOGLE_SHEET_ID` et `GOOGLE_SHEET_NAME` permettent de changer de feuille ou d’onglet. Les identifiants Google ne doivent jamais être publiés. Les matchs retenus sont datés selon le fuseau `Africa/Douala` et écrits avec les colonnes attendues par `app.js`. Les lignes des 10 derniers jours sont conservées ; les seules lignes purgées sont celles plus anciennes que J−10. Les rencontres futures déjà présentes ne sont pas dupliquées et les panneaux verrouillés/en cours ne sont pas modifiés.

Le workflow GitHub Actions met à jour les résultats chaque jour à 00h00 UTC, puis actualise les résultats et génère les nouveaux pronostics à 06h30 UTC. Les appels à l'API statistique sont espacés pour respecter sa limite de requêtes ; les événements The Odds API sont gratuits, tandis que chaque vérification de cote demande un seul marché dans la région `eu`.

## Important avant une mise en production

Les matchs et pronostics de démonstration restent fictifs ; le script de génération et l’écriture Google Sheets sont fournis séparément et nécessitent une configuration valide. Les pages légales sont des espaces réservés. Vérifiez les données, les accès et le fonctionnement complet avant toute publication.
