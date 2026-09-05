# Séance 9 — Réactions emoji + frappe en message privé

## Théorie — le serveur ne sait pas ou tu ecris

L'indicateur "en train d'ecrire" ne marchait que dans les salons. Le code
frontend contenait meme un aveu :

```js
if (dmActif) return;   // App.jsx, avant cette seance
```

Pourquoi cette limite ? Quand tu ouvres un DM, le serveur ne te fait **pas**
quitter la room de ton salon — tu continues d'y recevoir les messages. A cet
instant tu es donc dans deux rooms a la fois, et l'evenement `en_train_ecrire`
n'apportait aucune information sur laquelle des deux te concerne :

```python
emit("quelquun_ecrit", ..., to=infos["salon"])   # toujours le salon
```

Deux corrections possibles : deviner cote serveur (impossible, l'information
n'existe pas), ou **la faire dire par le client**. C'est la deuxieme :

```js
socketRef.current.emit('en_train_ecrire', { prive: !!dmActif });
```

```python
salle = infos.get("conversation") if prive else infos.get("salon")
```

L'evenement `quelquun_ecrit` renvoie a son tour ce `prive`, et le client
n'affiche l'indicateur que si le contexte correspond a ce qu'on regarde :

```js
.filter(([p, infos]) => p !== pseudo && infos.prive === !!dmActif)
```

Sans ce filtre, quelqu'un qui tape dans `#general` ferait apparaitre "X est en
train d'ecrire" au milieu d'une conversation privee.

**A retenir** : `data=None` par defaut dans le handler Python. Un navigateur
qui a encore l'ancienne version du site en cache emet `en_train_ecrire` sans
argument — il ne doit pas provoquer une erreur serveur. C'est le probleme de
toute mise a jour d'app en ligne : pendant quelques minutes, deux versions du
frontend parlent au meme backend.

## Théorie — une seule table pour deux sortes de messages

Les reactions doivent marcher sur les messages de salon (`messages`) **et** sur
les messages prives (`messages_prives`). Deux tables auraient voulu dire deux
fois le meme code. Une seule table, avec une colonne qui dit de quel monde
vient l'identifiant :

```sql
CREATE TABLE IF NOT EXISTS reactions (
    id SERIAL PRIMARY KEY,
    message_id INTEGER NOT NULL,
    prive BOOLEAN NOT NULL DEFAULT FALSE,
    pseudo TEXT NOT NULL,
    emoji TEXT NOT NULL,
    UNIQUE (message_id, prive, pseudo, emoji)
)
```

La contrainte `UNIQUE` est le coeur du systeme : elle rend impossible qu'une
personne mette deux fois le meme emoji sur le meme message. Ce n'est pas une
verification du code, c'est une regle de la base — meme un bug dans l'app ne
peut pas la contourner. (Verifie pendant la seance : la deuxieme insertion
identique leve bien une `IntegrityError`.)

`prive` fait partie de la cle : le message de salon n°12 et le message prive
n°12 sont deux messages differents.

## L'id doit remonter au client

Avant, le serveur envoyait un message ainsi :

```python
{"pseudo": ..., "texte": ..., "envoye_le": ...}
```

Pas d'`id`. Le client n'avait donc aucun moyen de designer un message. Il a
fallu ajouter `RETURNING id` aux `INSERT` et `SELECT id, ...` aux historiques.

C'est une lecon de conception : **exposer l'identifiant d'une ligne des le
depart** coute une colonne dans un JSON, et evite de devoir tout retoucher le
jour ou on veut agir sur un message precis.

## Securite — ne jamais faire confiance a un id venu du client

Un id arrive du navigateur. Rien n'empeche quelqu'un d'ouvrir la console et
d'emettre :

```js
socket.emit('reagir', { message_id: 999, emoji: '👍', prive: true })
```

Sans controle, il reagirait a un message prive entre deux autres personnes —
et recevrait la mise a jour. D'ou `_message_visible()`, qui verifie en base
que le message appartient bien au salon courant, ou a la conversation dont
l'utilisateur est l'un des deux membres.

Deuxieme garde-fou, la liste blanche :

```python
if emoji not in EMOJIS or not isinstance(message_id, int):
    return
```

Sans elle, `emoji` est un champ texte libre : on pourrait y stocker un roman,
ou du HTML. Cinq valeurs autorisees, rien d'autre.

## Le detail qui evite 30 requetes

En rejoignant un salon, on charge 30 messages. Chercher les reactions message
par message ferait 30 allers-retours vers une base hebergee a l'autre bout du
monde. Une seule requete suffit :

```python
text("... WHERE prive = :prive AND message_id IN :ids")
    .bindparams(bindparam("ids", expanding=True))
```

`expanding=True` demande a SQLAlchemy de developper la liste en
`IN (:id_1, :id_2, ...)` au moment de l'execution. Sans lui, passer une liste
Python a une requete SQL ne marche tout simplement pas.

Ce probleme a un nom : **N+1 requetes**. Une requete pour la liste, puis une
par element. C'est la premiere cause de lenteur des applications qui parlent
a une base.

## Cote interface

La barre d'emojis apparait au survol du message. Elle est piloee en CSS, pas
en React :

```jsx
sx={{ '&:hover .barre-emoji': { opacity: 1, pointerEvents: 'auto' } }}
```

Faire ca avec un `useState` par message voudrait dire un re-rendu React a
chaque mouvement de souris sur la liste. Le CSS le fait sans que React ne
soit meme au courant.

`pointerEvents: 'none'` quand la barre est invisible : sinon elle resterait
cliquable alors qu'on ne la voit pas.

## Résultat

- Barre 👍 ❤️ 😂 😮 😢 au survol de n'importe quel message
- Un clic ajoute, un deuxieme clic retire (bascule)
- Compteur sous le message, entoure quand on en fait partie, avec la liste
  des pseudos au survol
- Fonctionne dans les salons **et** dans les DM
- "X est en train d'ecrire..." marche desormais aussi en message prive

## Exercice

1. Deux comptes, deux fenetres. Reagis a un message et verifie que le
   compteur bouge **chez l'autre sans rechargement** — c'est le WebSocket qui
   travaille.
2. Ouvre un DM et tape : l'indicateur doit apparaitre chez l'autre. Puis, en
   restant dans le DM, demande a quelqu'un d'ecrire dans `#general` : rien ne
   doit s'afficher.
3. Ouvre la console du navigateur et essaie de tricher :
   `socket.emit('reagir', { message_id: 1, emoji: 'pirate', prive: false })`.
   Rien ne se passe — trouve les deux lignes de `app.py` qui t'ont arrete.
4. Bonus : une reaction ne fait pas de son ni de notification. Fais-en une
   quand quelqu'un reagit a **ton** message (indice : le pseudo de l'auteur
   du message n'est pas envoye avec `reactions_maj`, il faudra l'ajouter).
