# Séance 13 — Premiers tests et intégration continue

## Théorie — pourquoi ce code n'etait pas testable

Avant d'ecrire un seul test, il a fallu constater un probleme. Voici les
premieres lignes utiles de `app.py` :

```python
engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    conn.execute(text("CREATE TABLE IF NOT EXISTS users (...)"))
```

Ce code s'execute **a l'import**. Autrement dit, `import app` ouvre une
connexion PostgreSQL et cree des tables. Impossible d'importer la moindre
fonction du fichier sans une base joignable et six variables d'environnement
definies.

C'est le probleme le plus courant quand on veut tester un projet qui n'a pas
ete pense pour : le code marche tres bien, mais il ne se laisse pas prendre en
main morceau par morceau.

## Pratique — separer ce qui est pur

Une **fonction pure** ne lit rien, n'ecrit rien, ne depend d'aucun etat : meme
entree, meme sortie, toujours. Elle se teste en une ligne.

Quatre fonctions d'`app.py` etaient deja pures sans qu'on l'ait fait expres.
Elles sont parties dans `backend/outils.py` :

| Fonction | Ce qu'elle decide |
|----------|-------------------|
| `nom_conversation(a, b)` | le nom de room d'un DM, identique dans les deux sens |
| `image_valide(url, prefixe)` | si une URL d'image vient bien de notre compte |
| `salle_de_frappe(infos, prive)` | ou envoyer l'indicateur "en train d'ecrire" |
| `config_cloudinary_depuis_url(...)` | lire `cloudinary://cle:secret@cloud` |

Aucun changement de comportement : les memes lignes, dans un autre fichier.
`app.py` les importe et garde une petite adaptation la ou une constante locale
est necessaire :

```python
def _image_valide(url):
    return image_valide(url, PREFIXE_IMAGE)
```

Resultat : **15 tests qui tournent en 0,05 seconde**, sans base, sans reseau,
sans variable d'environnement. C'est ce genre de suite qu'on lance vingt fois
par jour.

## Pratique — les tests d'integration

Le reste demande une vraie base. Le SQL du projet utilise `SERIAL`,
`RETURNING`, `ON CONFLICT` : du PostgreSQL, pas du SQL generique. Un SQLite en
memoire ne remplacerait rien.

D'ou la regle posee dans `conftest.py` :

```python
if not URL_TEST:
    pytest.skip("TEST_DATABASE_URL absente : tests d'integration ignores")
```

**Ignorer plutot qu'echouer.** Une suite rouge parce qu'il manque une base sur
la machine du developpeur, c'est une suite qu'on arrete de lancer au bout de
trois jours. En local : 15 tests verts, 11 ignores. En integration continue,
ou la base existe : 26 verts.

Deux tests meritent d'etre lus, parce qu'ils verifient des affirmations
repetees depuis des seances sans avoir jamais ete prouvees :

```python
def test_le_mot_de_passe_n_est_jamais_stocke_en_clair(application, compte):
    ...
    assert compte["password"] not in empreinte

def test_signature_upload_refuse_un_jeton_bidon(client):
    assert client.post("/signature-upload",
        headers={"Authorization": "Bearer pas-un-vrai-jeton"}).status_code == 401
```

Le second protege le compte Cloudinary : sans ce controle, n'importe qui
obtiendrait un droit d'ecriture sur ton stockage.

Et un detail qui compte : chaque compte de test est cree avec un nom tire au
hasard (`uuid4`). Sans cela, la contrainte `UNIQUE` sur `username` ferait
echouer la deuxieme execution de la suite.

## Pratique — l'integration continue

`.github/workflows/ci.yml` tourne a chaque push sur `main` et sur chaque pull
request. Deux jobs en parallele.

Le plus interessant est le **service PostgreSQL** :

```yaml
services:
  postgres:
    image: postgres:16
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
```

GitHub demarre une vraie base a cote du job, le temps de l'execution. Le
`--health-cmd` n'est pas un detail : sans lui, les tests demarreraient avant que
la base accepte les connexions. L'echec serait **aleatoire** — le pire genre de
rouge, celui qui passe une fois sur deux et qu'on finit par ignorer.

Cote frontend, `npm run lint` puis `npm run build`. Un build casse chez toi
casse aussi chez Cloudflare : autant l'apprendre ici, avant que le deploiement
automatique ne parte.

## Resultat

Premiere execution verte : backend 40 s, frontend 17 s.

Ce que ca change concretement : jusqu'a aujourd'hui, un push sur `main`
partait directement en production sur Cloudflare et Render, sans que rien ne
soit verifie. Maintenant, une erreur de syntaxe, un import casse ou une route
qui ne repond plus se voient avant.

## Exercice

1. Casse volontairement une fonction d'`outils.py` (retire le `sorted` de
   `nom_conversation`), lance `pytest tests -q` : quel test tombe, et son
   message est-il assez clair pour comprendre sans lire le code ?
2. Commit et push cette version cassee sur une branche, ouvre une pull request,
   et regarde la CI passer au rouge. Puis corrige et regarde-la repasser au
   vert.
3. Ecris un test pour une fonction pure qui n'en a pas encore.
4. Question ouverte : les WebSockets ne sont pas testes du tout. Cherche
   `SocketIOTestClient` dans la documentation de Flask-SocketIO — et demande-toi
   quel evenement de la Seance 9 ou 11 tu voudrais couvrir en premier.
