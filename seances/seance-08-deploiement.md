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

Trois sorties possibles : attendre le renouvellement des credits, ajouter un
moyen de paiement, ou changer d'hebergeur. On a choisi la troisieme —
**Cloudflare**, compte gratuit sans plafond de builds. Le frontend etant du
statique, il n'est attache a aucun hebergeur : c'est justement l'interet de
la separation frontend/backend.

## Étape 4 — bascule sur Cloudflare

### Pages n'existe plus pour les nouveaux projets

Cloudflare Pages est en maintenance : un nouveau projet passe forcement par
**Workers**. La difference se voit tout de suite dans le formulaire — Workers
demande une **"Deploy command"**, Pages n'en avait pas. Pages deployait
lui-meme le dossier de sortie ; avec Workers, c'est `wrangler` (l'outil en
ligne de commande de Cloudflare) qui publie, et il lui faut un fichier de
configuration :

```jsonc
// frontend/wrangler.jsonc
{
  "name": "chat-app",
  "account_id": "...",
  "compatibility_date": "2026-09-05",
  "assets": {
    "directory": "./dist",
    "not_found_handling": "single-page-application"
  }
}
```

Un Worker "static assets" ne fait tourner aucun code : il sert le contenu de
`dist/` depuis le reseau Cloudflare. `not_found_handling` est l'equivalent
natif de la regle `/* -> /index.html` de `netlify.toml`.

### Reglages dans l'interface

| Champ | Valeur |
|---|---|
| Repertoire racine | `frontend` |
| Commande de build | `npm run build` |
| Commande de deploiement | `npx wrangler deploy` |

Le **repertoire racine** est le reglage qui decide de tout : le depot contient
`backend/` et `frontend/`, et il n'y a pas de `package.json` a la racine. Le
premier build a echoue en 3 secondes pour cette seule raison. Le champ
n'apparait pas dans le formulaire de creation — il faut creer le projet, puis
aller dans Parametres > Configuration de build.

`.node-version` (contenant `22`) a ete ajoute au depot : Vite 8 exige Node
>= 20.19, et un hebergeur qui tourne encore sur Node 18 par defaut ferait
echouer le build. Ce fichier est lu par Cloudflare, Render et Netlify — il
rend le projet portable.

### Le piege : deux fois la meme regle

Le deploiement a echoue une derniere fois, avec ce message :

```
Invalid _redirects configuration:
Line 5: Infinite loop detected in this rule.
```

Un fichier `public/_redirects` avait ete ajoute avec la regle
`/*  /index.html  200`. Or `wrangler.jsonc` fait deja le meme travail via
`not_found_handling`. Les Workers valident `_redirects` bien plus strictement
que Pages et voient dans cette regle une boucle : `/index.html` est lui-meme
capture par `/*`, donc redirige vers `/index.html`, indefiniment. Fichier
supprime, deploiement passe.

**Lecon, la meme que pour Netlify mais dans l'autre sens** : le journal de
build disait exactement quoi corriger des la premiere lecture. Le temps perdu
l'a ete a chercher ailleurs (une histoire de variables d'environnement) avant
d'avoir lu le message en entier. Lire le log jusqu'au bout **avant** de
toucher au code.

## Verification finale

Depuis l'exterieur, sans passer par le navigateur :

```
GET /                          -> 200, <title>Chat en temps reel</title>
GET /reset-password            -> 200   (le fallback SPA marche)
GET /assets/index-*.js         -> 200
GET /socket.io/?EIO=4&transport=polling
   -> {"sid":"...","upgrades":["websocket"]}
```

La derniere ligne est la plus importante du projet : `"upgrades":["websocket"]`
signifie que le serveur accepte de passer du HTTP au WebSocket. C'est ce que
le worker `gevent` rend possible et qu'un gunicorn par defaut n'aurait pas su
faire — toute la Seance 1 tient dans ce mot.

## Resultat final

- **Frontend** : https://chat-app.yassinechkir38.workers.dev (Cloudflare Workers)
- **Backend** : https://chat-app-gkbm.onrender.com (Render + Neon PostgreSQL)

Ne pas oublier : la variable `FRONTEND_URL` du service Render doit pointer vers
l'URL Cloudflare, sinon le lien du mail "mot de passe oublie" mene dans le vide.

## Exercice

1. Ouvre le chat depuis ton telephone, en 4G (pas en wifi) : c'est la preuve
   que ca passe vraiment par internet et pas par le reseau local
2. Deux comptes, deux appareils differents, et verifie que le message arrive
   en temps reel des deux cotes
3. Teste "mot de passe oublie" de bout en bout et verifie que le lien recu par
   mail ouvre bien la page de reinitialisation
4. Fais une petite modification visible (un titre, une couleur), commit, push —
   et regarde Cloudflare rebuilder tout seul. C'est ca, le deploiement continu.
