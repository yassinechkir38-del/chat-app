# Séance 11 — Accusés de lecture (« Vu »)

## Théorie — qu'est-ce qu'un message "lu" ?

C'est la vraie question de cette seance, et elle n'est pas technique. Trois
reponses possibles, de la plus fausse a la plus honnete :

1. **Le serveur l'a envoye.** Faux : le destinataire peut etre hors ligne.
2. **Le navigateur l'a recu.** Toujours faux : l'onglet peut etre en
   arriere-plan depuis trois heures.
3. **Il est affiche dans un onglet visible.** C'est celle qu'on retient.

D'ou les deux conditions dans le code :

```js
if (document.hidden || !socketRef.current?.connected) return;
```

`document.hidden` est vrai quand l'onglet est en arriere-plan ou la fenetre
reduite. Un "Vu" envoye dans ces conditions serait un mensonge affiche a
quelqu'un d'autre — et un accuse de lecture est une information **sur une
personne**, pas sur un message. C'est le genre de detail ou une approximation
technique devient un probleme de confiance.

L'ecouteur est pose sur `visibilitychange` : revenir sur l'onglet declenche
l'accuse, sans avoir a bouger la souris.

## Modelisation — une position, pas une liste de coches

Le reflexe serait une table "qui a lu quel message" : une ligne par message et
par lecteur. Avec 30 personnes et 10 000 messages, ca fait 300 000 lignes pour
une information qu'on peut resumer en 30.

Un fil de discussion se lit dans l'ordre. Si tu as lu le message 200, tu as lu
tous ceux d'avant. Une seule ligne par personne et par salle suffit donc :

```sql
CREATE TABLE IF NOT EXISTS lectures (
    pseudo TEXT NOT NULL,
    salle TEXT NOT NULL,
    dernier_message_id INTEGER NOT NULL,
    maj_le TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (pseudo, salle)
)
```

`salle` est le nom de la room socket.io : `"general"` pour un salon,
`"dm_alice_bob"` pour une conversation privee. Le meme mecanisme sert donc aux
deux, sans une ligne de code specifique.

La cle primaire composee `(pseudo, salle)` dit qu'une personne n'a **qu'une**
position par salle. Cette contrainte n'est pas decorative : c'est elle qui rend
possible l'UPSERT qui suit.

## L'UPSERT, et pourquoi GREATEST

"Insere, ou mets a jour si la ligne existe deja" — en une seule requete :

```sql
INSERT INTO lectures (pseudo, salle, dernier_message_id, maj_le)
VALUES (:pseudo, :salle, :message_id, NOW())
ON CONFLICT (pseudo, salle) DO UPDATE
SET dernier_message_id = GREATEST(lectures.dernier_message_id, EXCLUDED.dernier_message_id),
    maj_le = NOW()
RETURNING dernier_message_id
```

`EXCLUDED` est la ligne qu'on essayait d'inserer ; `lectures.` est celle deja
en base. `GREATEST` garde la plus grande des deux — autrement dit **un accuse
de lecture ne recule jamais**.

Sans ce `GREATEST` : deux onglets ouverts, l'un a jour et l'autre reste sur un
vieil etat. Le second envoie sa position, plus basse, et le "Vu" de l'autre
personne recule sous ses yeux. Verifie pendant la seance : on envoie 12, puis
20, puis 5 — la position reste a 20.

`RETURNING dernier_message_id` sert au coup d'apres : on diffuse la position
**reellement enregistree**, pas celle qu'on a recue. Si le client etait en
retard, les autres n'en savent rien.

## Cote client — deux seaux, pas un

```js
const [lectures, setLectures] = useState({ salon: {}, prive: {} });
```

Meme raison qu'a la Seance 9 pour l'indicateur de frappe : en ouvrant un DM on
reste membre de la room de son salon. Les deux flux d'accuses arrivent donc en
meme temps, et il faut les ranger separement — sinon la position de quelqu'un
dans `#general` viendrait s'afficher dans une conversation privee.

Le champ `prive` accompagne chaque evenement, exactement comme pour la frappe.
C'est devenu le motif recurrent du projet : **le serveur ne peut pas deviner
le contexte, le client le declare**.

## L'avatar au bon endroit

```js
.filter(([p, dernierLu]) => p !== pseudo && dernierLu === id)
```

Egalite stricte, pas `>=`. Avec `>=`, l'avatar apparaitrait sous *tous* les
messages deja lus — une colonne de pastilles le long de la conversation. Avec
`===`, il n'apparait que sous le dernier message lu, et **glisse** vers le bas
a mesure que la personne avance. C'est ce que fait Messenger, et c'est une
ligne de difference.

## Exercice

1. Deux comptes, deux fenetres cote a cote. Envoie un message : l'avatar doit
   apparaitre chez toi des que l'autre le voit.
2. Reduis la fenetre du deuxieme compte et envoie un nouveau message : aucun
   accuse. Reaffiche la fenetre : l'accuse part. Retrouve la ligne responsable.
3. Ouvre la meme conversation dans deux onglets du meme compte, laisse-en un
   en arriere sur un vieil etat, puis reviens dessus : la position ne doit pas
   reculer. C'est `GREATEST` qui te protege.
4. Bonus : Messenger affiche "Vu a 14:32". La colonne `maj_le` est deja
   remplie mais n'est jamais envoyee au client. Ajoute-la.
