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

## Important avant une mise en production

Les matchs et pronostics actuels sont fictifs. Les pages légales sont des espaces réservés. La connexion Google Sheets, l'authentification administrateur, les vraies données, les règles de publication et la publicité ne sont pas encore intégrées. Ne publiez pas de pronostics réels avant d'avoir ajouté ces éléments et vérifié le fonctionnement complet.
