# Séance 12 — Envoi d'images

## Théorie — le fichier ne doit pas passer par ton serveur

Le reflexe : le navigateur envoie l'image a Flask, Flask l'envoie au stockage.
Deux problemes.

D'abord le trajet. L'image ferait navigateur -> Render -> stockage, soit deux
transferts complets la ou un seul suffit. Ensuite la memoire : l'instance
gratuite de Render a 512 Mo. Trois personnes qui envoient une photo de 4 Mo en
meme temps, et le processus meurt.

La bonne architecture inverse les roles. Le backend ne touche jamais au
fichier : il **signe une autorisation**, et le navigateur envoie l'image
directement au stockage.

```
navigateur --(1) demande une autorisation--> backend
navigateur <--(2) signature valable 5 min--- backend
navigateur --(3) le fichier, en direct-----> stockage
navigateur --(4) juste l'URL---------------> backend (dans le message)
```

Le backend voit passer quelques centaines d'octets au lieu de plusieurs Mo.

## La signature

```python
a_signer = f"folder={CLOUDINARY_DOSSIER}&timestamp={horodatage}{CLOUDINARY_API_SECRET}"
signature = sha1(a_signer.encode()).hexdigest()
```

Les parametres, tries par ordre alphabetique, suivis du secret, le tout passe
dans une fonction de hachage. Le stockage refait le meme calcul de son cote :
s'il trouve le meme resultat, c'est que la demande vient bien de quelqu'un qui
connait le secret.

Le point important : **le secret ne quitte jamais le serveur**. Le navigateur
recoit une signature — de quoi faire un envoi, avec ce dossier et cet
horodatage — mais pas de quoi en fabriquer une autre. C'est la difference
entre donner sa carte et donner un ticket de caisse.

Aucune bibliotheque a installer : `hashlib` fait partie de Python.

## Une variable d'environnement optionnelle

Toutes les autres variables sont lues avec des crochets :

```python
SECRET_KEY = os.environ["SECRET_KEY"]        # absente -> l'app refuse de demarrer
```

Celles du stockage, non :

```python
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")   # absente -> None
IMAGES_ACTIVES = all([...])
```

La nuance vaut la peine d'etre comprise. `SECRET_KEY` absente, l'application
n'a aucun sens : mieux vaut un crash immediat et lisible (Seance 8, le
`KeyError: 'FRONTEND_URL'`). Les identifiants du stockage absents, tout le
reste fonctionne encore : le chat, les DM, les reactions, les accuses de
lecture. Faire tomber le service entier pour une fonctionnalite secondaire
serait absurde.

L'endpoint repond alors `503` avec un message clair, et le bouton d'envoi
affiche l'erreur au lieu de tourner dans le vide.

C'est ce qui a permis de deployer ce code **avant** meme d'avoir cree le
compte de stockage.

## Redimensionner avant d'envoyer

Une photo de telephone fait 3 a 5 Mo pour 4000 pixels de large. Affichee dans
un chat sur 320 pixels, c'est vingt fois trop.

Le navigateur sait le faire seul, avec un `<canvas>` :

```js
const echelle = Math.min(1, maxCote / Math.max(image.width, image.height));
canvas.width = Math.round(image.width * echelle);
// ... drawImage, puis canvas.toBlob(..., 'image/jpeg', 0.82)
```

`Math.min(1, ...)` empeche d'agrandir une petite image : on reduit, jamais
l'inverse.

Resultat typique : 4 Mo devient 180 Ko. Le transfert est instantane, et le
quota du stockage gratuit dure vingt fois plus longtemps.

**Exception** : un GIF anime perdrait son animation en passant par un canvas,
qui ne connait qu'une image fixe. On le laisse donc tel quel s'il est
raisonnable :

```js
if (fichier.type === 'image/gif' && fichier.size < 3 * 1024 * 1024) return fichier;
```

## Securite — ne jamais stocker une URL venue du client

Le navigateur envoie `image_url` avec le message. Sans controle, on pourrait y
mettre n'importe quelle adresse du web.

Deux consequences, la seconde moins evidente. La premiere : afficher n'importe
quoi dans le chat. La seconde : **chaque personne qui affiche le message
telecharge l'image depuis le serveur choisi par l'attaquant**, qui recupere
ainsi l'adresse IP de tout le salon.

```python
return url if url.startswith(PREFIXE_IMAGE) else None
```

Une seule ligne, mais c'est la meme logique que pour `repond_a` et pour les
reactions : **tout ce qui vient du client est une proposition, pas un fait**.

## Ce qui n'est PAS protege

Honnetement : la taille du fichier n'est verifiee **que dans le navigateur**.
Quelqu'un qui appelle l'API directement, sans passer par la page, peut envoyer
un fichier de la taille qu'il veut.

La vraie protection serait une "policy" signee cote serveur, imposant une
taille maximale que le stockage fait respecter lui-meme. C'est le prolongement
naturel de cette seance.

Retenir la formule : **une validation cote client est un confort pour
l'utilisateur, jamais une securite**.

## Le detail qui fuit : URL.revokeObjectURL

`URL.createObjectURL(blob)` cree une reference que le navigateur garde en
memoire **jusqu'a ce qu'on la libere explicitement**. Sans
`URL.revokeObjectURL`, chaque image choisie puis annulee resterait en memoire
pour toute la duree de la session.

## Configuration (a faire dans le dashboard Render)

Une seule variable suffit :

| Variable | Ou la trouver |
|----------|---------------|
| `CLOUDINARY_URL` | tableau de bord Cloudinary, ligne "API environment variable", **bouton de copie** |

Elle a la forme `cloudinary://<api_key>:<api_secret>@<cloud_name>` et le backend
en extrait les trois valeurs lui-meme. C'est la convention officielle des
bibliotheques Cloudinary. Les trois variables separees
(`CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`)
restent acceptees, mais voir ci-dessous pourquoi on ne les recommande plus.

L'API Secret est un vrai secret : il ne va **que** dans les variables
d'environnement de Render. Jamais dans le depot, jamais dans une variable
`VITE_*` — qui finirait en clair dans le JavaScript telecharge par tout le
monde (cf. Seance 8).

## Le piege : "Invalid Signature", trois fois de suite

La mise en service a echoue trois fois d'affilee, toujours avec le meme
message renvoye par Cloudinary :

```
Invalid Signature 72bf09ff... String to sign - 'folder=chat-app&timestamp=1788612300'
```

Ce message est plus utile qu'il n'en a l'air. Cloudinary y **reconstruit la
chaine qu'il a signee de son cote** : `folder=chat-app&timestamp=...`. Elle est
identique a la notre. Le format, l'ordre des parametres, l'horodatage : tout
est bon. Une seule chose peut alors differer — le secret utilise pour hacher.

Le diagnostic s'est fait sans jamais regarder la valeur enregistree, en
comparant la signature produite par le backend a celle qu'on obtiendrait avec
diverses hypotheses :

```python
sha1((chaine + hypothese).encode()).hexdigest() == signature_du_backend
```

Reponse : la variable `CLOUDINARY_API_SECRET` contenait **la ligne entiere**
`CLOUDINARY_URL=cloudinary://172...:psd...@svg1sjgd` au lieu du seul fragment
situe entre `:` et `@`.

Trois lecons, dans l'ordre d'importance :

1. **Ne jamais faire recopier un fragment de secret a la main.** Extraire "ce
   qui est entre les deux-points et l'arobase" est une operation qu'un humain
   rate, et l'erreur est invisible : un caractere faux ressemble exactement a
   un caractere juste. La solution n'a pas ete de mieux expliquer l'extraction,
   mais de **supprimer l'extraction** — le backend lit desormais la ligne
   complete, celle que le tableau de bord copie en un clic.
2. **Un message d'erreur en dit souvent plus que ce qu'on y lit d'abord.** La
   chaine a signer etait affichee des le premier echec ; elle prouvait que le
   format etait correct et que seul le secret pouvait etre en cause. Le temps
   perdu l'a ete a soupconner tout le reste.
3. **Un secret peut se verifier sans jamais s'afficher.** Comparer des
   empreintes suffit a savoir si la bonne valeur est en place. C'est aussi
   pourquoi le mot de passe de la base a ete transmis via le presse-papiers
   plutot qu'affiche a l'ecran.

## Exercice

1. Envoie une photo prise au telephone et regarde le poids affiche sous
   l'apercu. Compare-le au poids du fichier d'origine.
2. Envoie une image **sans texte** : le message doit partir quand meme.
   Retrouve la condition qui l'autorise, cote serveur et cote client.
3. Ouvre l'onglet Reseau des outils de developpement pendant un envoi : tu dois
   voir deux requetes, dont une seule vers ton backend. Laquelle transporte les
   megaoctets ?
4. Bonus : les images ne sont jamais supprimees, meme quand le message l'est.
   Reflechis a ce qu'il faudrait pour nettoyer — et pourquoi ce n'est pas aussi
   simple qu'un `DELETE`.
