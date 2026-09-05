# Séance 8 — Déploiement (Render + Netlify)

## Théorie — pourquoi le WebSocket change les regles du deploiement

Le todo-app (Seance 26) etait simple a deployer : chaque requete HTTP arrive,
est traitee, la connexion se ferme. Un serveur de production classique
(`gunicorn app:app`) suffit, avec ses workers qui se passent les requetes.

Un chat WebSocket, lui, garde **une connexion ouverte par utilisateur
connecte**, potentiellement pendant des heures. Avec le worker par defaut de
gunicorn (`sync`), un worker occupe par une connexion permanente ne peut plus
rien faire d'autre : deux utilisateurs connectes et le serveur est bloque.

Il faut donc un worker **asynchrone**, capable de tenir des milliers de
connexions ouvertes en parallele sur un seul processus. D'ou la commande de
demarrage :

```
gunicorn --worker-class gevent --workers 1 app:app
```

- `--worker-class gevent` : le worker asynchrone (voir plus bas)
- `--workers 1` : **un seul** worker, c'est important. Flask-SocketIO garde en
  memoire la liste des clients connectes et de leurs rooms. Avec plusieurs
  workers, chaque processus aurait sa propre liste et un message envoye a un
  worker ne serait jamais vu par les clients de l'autre. Pour depasser un seul
  worker il faudrait un "message queue" partage (Redis) — hors sujet ici.

## Le piege : eventlet, puis gevent

Premiere tentative avec `eventlet`, le worker async historique de
Flask-SocketIO : echec au demarrage sur Render. `eventlet` n'est plus vraiment
maintenu et casse avec les versions recentes de Python.

Bascule vers **gevent** (`gevent` + `gevent-websocket`), qui fait le meme
travail. Deux consequences dans le code :

```python
from gevent import monkey
monkey.patch_all()
```

Ces deux lignes doivent etre **tout en haut de `app.py`**, avant le moindre
autre import. Le "monkey patching" remplace les fonctions bloquantes de Python
(sockets, `time.sleep`, etc.) par des versions cooperatives ; si un module a
deja ete importe avant, il garde les anciennes versions et le serveur se fige.

Et cote SocketIO :

```python
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")
```

Troisieme erreur rencontree : `ModuleNotFoundError: packaging` — le worker
gevent de gunicorn en a besoin sans le declarer lui-meme. Ajoute a la main
dans `requirements.txt`.

## Étape 1 — le backend sur Render

Service Web Render, meme methode que le todo-app :

- **Root Directory** : `backend`
- **Build Command** : `pip install -r requirements.txt`
- **Start Command** : `gunicorn --worker-class gevent --workers 1 app:app`
- **Variables d'environnement** : `DATABASE_URL` (le projet Neon du chat, pas
  celui du todo-app), `SECRET_KEY`, `MAILJET_API_KEY`, `MAILJET_SECRET_KEY`,
  `MAIL_FROM`, `FRONTEND_URL`

Toutes ces variables sont lues avec `os.environ["..."]` (crochets, pas `.get()`) :
si l'une manque, l'app plante immediatement au demarrage avec un message clair,
plutot que de tomber en panne plus tard sur un `None` incomprehensible.

`FRONTEND_URL` sert a construire le lien du mail "mot de passe oublie"
(`{FRONTEND_URL}/reset-password?token=...`) : elle doit pointer vers l'URL
publique du frontend, pas vers `localhost`.

Resultat : **https://chat-app-gkbm.onrender.com** (verifiable avec
`/salons`, qui repond `["general","aleatoire","aide"]`).

Rappel du plan gratuit : le service s'endort apres 15 minutes sans trafic, la
requete suivante met ~30 s. Ce n'est pas un bug — c'est visible ici au premier
chargement de la page.

## Étape 2 — brancher le frontend

Le code ne doit pas contenir d'URL en dur : `src/api.js` lit une variable Vite.

```js
const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5050';
```

- en `npm run dev` : la variable n'existe pas, on retombe sur le backend local
- en `npm run build` : Vite lit `.env.production` et **inscrit la valeur en dur
  dans le bundle** (`VITE_API_URL=https://chat-app-gkbm.onrender.com`)

D'ou une regle : ne jamais mettre de secret dans une variable `VITE_*`. Tout
ce qui est prefixe `VITE_` finit en clair dans le JavaScript telecharge par le
navigateur. Une URL d'API publique, oui ; une cle d'API, jamais.

Meme URL pour le HTTP et le WebSocket (`export const SOCKET_URL = BASE_URL`) :
socket.io se connecte au meme hote, en basculant de `https://` a `wss://` tout
seul.

## Étape 3 — le frontend sur Netlify

Deux fichiers de configuration, tous les deux nes d'erreurs faites sur le
todo-app :

```toml
[build]
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

- `publish = "dist"` : Netlify sert le **resultat du build**, jamais les
  sources. L'`index.html` a la racine du projet reference `/src/main.jsx`, que
  le navigateur ne sait pas lire — c'est le piege "page blanche" du todo-app.
- La redirection `/*` -> `/index.html` : l'app React gere ses propres URL
  (`/reset-password`). Sans cette regle, Netlify cherche un fichier
  `/reset-password` sur le disque et renvoie une 404.

## Le blocage : "account credit usage exceeded"

Le deploiement Netlify a echoue, mais **pas a cause du code**. Reponse de
l'API Netlify :

```
"state": "error",
"error_message": "Skipped due to account credit usage exceeded",
"skipped": true
```

Le compte gratuit a epuise ses credits mensuels : Netlify refuse de lancer de
nouveaux deploiements. A noter — les sites deja publies continuent de
fonctionner (https://yassine-todo-app.netlify.app repond toujours), c'est
uniquement la **publication** de nouvelles versions qui est bloquee.

Lecon a retenir : un deploiement qui echoue n'est pas forcement une erreur de
code. Toujours lire le message renvoye par l'hebergeur avant de modifier quoi
que ce soit — ici, une heure passee a relire `netlify.toml` n'aurait rien
donne.

Trois sorties possibles :

1. **Attendre** le renouvellement des credits (debut du cycle mensuel), ou
   ajouter un moyen de paiement sur le compte Netlify
2. **Render Static Site** — un deuxieme service Render, gratuit, a cote du
   backend (build `npm run build`, publish `dist`). Meme hebergeur pour les
   deux moities du projet.
3. **GitHub Pages** — le depot est deja sur GitHub, l'hebergement statique y
   est gratuit. Demande un ajustement de `base` dans `vite.config.js` si le
   site est servi depuis un sous-chemin.

## Etat au 5 septembre 2026

- **Backend** : en ligne, https://chat-app-gkbm.onrender.com
- **Frontend** : buildé et pret (`dist/`), publication en attente
