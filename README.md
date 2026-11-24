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

Le script `generate_pronos.py` génère séparément les pronostics d'aujourd'hui (J), demain (J+1) et après-demain (J+2). Il vérifie d'abord l'onglet `Matchs` et ne demande pas de nouvelles cotes pour une date qui contient déjà 12 matchs uniques (4 par panneau). Pour chaque date manquante ou incomplète, il cherche 12 matchs uniques et fiables, répartis en 3 panneaux de 4. Les cotes sont comprises entre 1,20 et 1,50 inclus ; un panneau peut inclure 3 matchs de football et 1 de basketball uniquement si la probabilité corrigée du match de basketball dépasse 75 % et sa cote est au plus 1,32. Les compétitions actives sont découvertes par l'endpoint gratuit `/v4/sports`, puis interrogées par priorité ; les demandes payantes cessent dès que la journée a ses 12 pronostics. Les lignes de J−10 à J+2 sont conservées et seules celles antérieures à J−10 sont purgées.

1. Installez les dépendances : `python -m pip install -r requirements.txt`.
2. Définissez `ODDS_API_KEY` avec votre clé The Odds API.
3. Pour prévisualiser sans modifier la feuille : `python generate_pronos.py --dry-run`.
4. Pour publier, configurez un compte de service Google Sheets avec accès éditeur à la feuille. Fournissez le JSON du compte dans `GOOGLE_CREDENTIALS_JSON` ou placez-le dans `credentials.json` à la racine, puis lancez `python generate_pronos.py`.
5. Pour actualiser les scores et résultats des rencontres en attente : `python generate_pronos.py --update-results`.

Le script utilise par défaut la feuille déjà lue par la PWA et son premier onglet. `GOOGLE_SHEET_ID` et `GOOGLE_SHEET_NAME` permettent de changer de feuille ou d’onglet. Les identifiants Google ne doivent jamais être publiés. Les matchs retenus sont datés selon le fuseau `Africa/Douala` et écrits avec les colonnes attendues par `app.js`. Les lignes des 10 derniers jours sont conservées ; les seules lignes purgées sont celles plus anciennes que J−10. Les rencontres futures déjà présentes ne sont pas dupliquées et les panneaux verrouillés/en cours ne sont pas modifiés.

Le workflow GitHub Actions met à jour les résultats chaque jour à 00h00 UTC, puis actualise les résultats et génère les nouveaux pronostics à 06h30 UTC. Les appels au point de terminaison des événements servent d'abord à ignorer les championnats sans match dans la journée et ne consomment pas de crédits de cotes. La récupération des cotes ne demande qu'une région (`eu`) et deux marchés. Chaque appel HTTP à The Odds API est précédé d'une pause de 1,2 seconde ; une réponse 429 `EXCEEDED_FREQ_LIMIT` déclenche une nouvelle tentative après 3 secondes. Le quota restant renvoyé par l'API est affiché lorsqu'il est disponible ; surveillez-le avant d'automatiser des exécutions fréquentes.

## Important avant une mise en production

Les matchs et pronostics de démonstration restent fictifs ; le script de génération et l’écriture Google Sheets sont fournis séparément et nécessitent une configuration valide. Les pages légales sont des espaces réservés. Vérifiez les données, les accès et le fonctionnement complet avant toute publication.
