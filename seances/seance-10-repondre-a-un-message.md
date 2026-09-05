# Séance 10 — Répondre à un message (citation)

## Théorie — une table qui se regarde elle-meme

Un message qui repond a un autre message pointe vers une ligne de **sa propre
table**. C'est une auto-reference, et elle se declare comme n'importe quelle
colonne :

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS repond_a INTEGER
```

`IF NOT EXISTS` est important : cette ligne s'execute a **chaque** demarrage
du serveur. Sans elle, le deuxieme demarrage planterait sur "la colonne existe
deja". C'est la meme technique que le `CREATE TABLE IF NOT EXISTS` du reste du
fichier : le schema se met a jour tout seul au deploiement, sans commande
manuelle a lancer sur la base de production.

Les messages deja en base prennent `NULL` : ils ne citent rien, et c'est
exactement ce qu'on veut.

## La jointure sur soi-meme

Pour afficher "Yassine : bonjour" au-dessus d'une reponse, il faut aller
chercher le message cite. Naivement : une requete par message affiche. Le
probleme N+1 de la seance precedente, en pire. La bonne facon, c'est de
joindre la table a elle-meme :

```sql
SELECT m.id, m.pseudo, m.texte, m.envoye_le,
       cite.pseudo AS cite_pseudo, cite.texte AS cite_texte
FROM messages m
LEFT JOIN messages cite ON cite.id = m.repond_a
WHERE m.salon = :s
ORDER BY m.id DESC LIMIT 30
```

La meme table apparait deux fois, sous deux noms differents (`m` et `cite`).
Sans ces alias, la base ne saurait pas de quel `pseudo` on parle.

**`LEFT` JOIN, pas `INNER`.** Un `INNER JOIN` ne garde que les lignes qui ont
une correspondance : les messages qui ne citent rien — c'est-a-dire presque
tous — disparaitraient de l'historique. `LEFT` garde tout et remplit de `NULL`
ce qui n'a pas de correspondance. C'est l'erreur classique de la jointure, et
elle est silencieuse : pas de message d'erreur, juste des messages qui
manquent.

## Stocker l'id, envoyer un apercu

En base, on ne garde que `repond_a = 12`. On ne copie pas le texte cite. Sinon
deux verites coexisteraient : si le message d'origine est un jour modifie ou
supprime, la copie resterait fausse pour toujours.

En revanche, ce qui part sur le socket est bien une **copie tronquee** :

```python
APERCU_MAX = 120
{"pseudo": ..., "texte": ligne.texte[:APERCU_MAX]}
```

Le client n'a pas a aller rechercher le message cite — il peut ne meme plus
l'avoir en memoire (l'historique s'arrete a 30 messages). Et 120 caracteres
suffisent pour une citation : au-dela, elle prendrait plus de place que la
reponse.

Le champ `repond_a` envoye au client vaut donc soit `null`, soit
`{pseudo, texte}` — jamais un simple nombre. Le composant React n'a aucune
recherche a faire :

```jsx
{item.repond_a && ( ... {item.repond_a.pseudo} ... )}
```

## Securite — le meme controle que pour les reactions

`repond_a` arrive du client. Comme pour les reactions, rien n'empeche
d'envoyer l'id d'un message prive entre deux autres personnes : sans controle,
son texte reviendrait dans l'apercu. La fuite serait discrete et complete.

La fonction ecrite pour les reactions sert donc deux fois, renommee pour ce
qu'elle fait vraiment :

```python
apercu = _apercu_si_visible(infos, data.get("repond_a"), prive=False)
```

Elle renvoie le contenu du message **si** l'utilisateur a le droit de le voir,
et `None` sinon. Un seul endroit a auditer pour deux fonctionnalites.

## Degradation : ignorer plutot que refuser

Que faire si l'id cite est invalide ? Refuser le message serait le reflexe.
Mais l'utilisateur perdrait ce qu'il vient d'ecrire, a cause d'un probleme qui
ne le concerne pas (message efface entre-temps, onglet reste ouvert trop
longtemps).

```python
repond_a = data.get("repond_a") if apercu else None
```

Le message part, sans la citation. Regle generale : quand une partie
**accessoire** d'une requete est invalide, on la laisse tomber ; on ne refuse
que si c'est l'essentiel qui est en cause.

## Cote interface

Trois morceaux :

1. **Un bouton dans la barre de survol**, apres les emojis, separe par un
   trait. Il remplit l'etat `reponseA` et redonne le focus au champ de saisie.
2. **Une banniere au-dessus du champ**, avec le pseudo, le debut du message
   et une croix pour annuler.
3. **Le bloc cite au-dessus du message**, avec une barre verticale a gauche
   et le pseudo colore de la meme facon que partout ailleurs
   (`couleurPour()`).

Detail qui compte : `setReponseA(null)` est appele au changement de salon, a
l'ouverture d'un DM et au retour au salon. Sans ca, on repondrait dans
`#general` a un message vu dans une conversation privee — le serveur
refuserait la citation (bien), mais l'interface aurait menti a l'utilisateur.

## Exercice

1. Reponds a un message, verifie que la citation apparait **chez l'autre**
2. Reponds a ta propre reponse : la citation doit citer la reponse, pas
   l'original. Comprends pourquoi en relisant le `LEFT JOIN`.
3. Ecris un message de plus de 120 caracteres, puis reponds-y : l'apercu est
   coupe. Retrouve la constante qui decide de cet endroit.
4. Bonus : cliquer sur une citation devrait faire defiler jusqu'au message
   d'origine et le surligner brievement. Indice : `document.getElementById`
   et un `id` pose sur chaque message — mais que faire quand le message cite
   n'est plus dans les 30 charges ?
