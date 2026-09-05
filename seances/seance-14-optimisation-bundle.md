# Séance 14 — Optimisation : mesurer avant de toucher

## Théorie — l'avertissement qu'on voyait a chaque build

Depuis la Seance 8, chaque `npm run build` affichait :

```
(!) Some chunks are larger than 500 kB after minification.
```

Un seul fichier JavaScript de 509 kB. La tentation est d'appliquer les
conseils qu'on lit partout — "importe les composants un par un", "remplace MUI
par plus leger". **Aucune de ces deux idees n'a servi ici**, et c'est tout
l'objet de cette seance : on ne peut pas optimiser ce qu'on n'a pas mesure.

## Pratique — mesurer d'abord

Avec une configuration Vite temporaire, un morceau par paquet :

| Morceau | Taille | Gzip |
|---------|--------|------|
| `@mui/material` | 262,6 kB | 84,2 kB |
| `react` + `react-dom` | 189,6 kB | 59,6 kB |
| `socket.io-client` | 41,2 kB | 12,9 kB |
| **notre code** | **20,2 kB** | 6,8 kB |
| `@mui/icons-material` | 2,3 kB | 0,9 kB |

Deux enseignements immediats.

Les **onze icones ne pesent que 2,3 kB**. Elles sont importees une par une
(`import SendIcon from '@mui/icons-material/Send'`), et ca fonctionne
parfaitement. Un import groupe depuis `@mui/icons-material` aurait pu en
ramener des milliers.

Et **notre code represente 4 % du total**. L'app entiere — quatorze seances de
travail — pese 20 kB. Le reste, ce sont les bibliotheques. Optimiser notre
propre code n'aurait donc, au mieux, aucun effet mesurable.

## L'experience qui n'a rien donne

Hypothese classique : l'import groupe `import { Box, Typography } from
'@mui/material'` ramenerait toute la bibliotheque, et les imports profonds
(`@mui/material/Box`) regleraient le probleme. Les deux versions ont ete
construites et comparees :

| | `@mui/material` |
|--|--|
| import groupe | 262,61 kB |
| imports profonds | 262,63 kB |

**Zero difference.** Rolldown ne garde deja que ce qui est utilise. Le conseil
etait vrai il y a quelques annees, avec des bundlers plus anciens ; il ne l'est
plus. La modification a donc ete **annulee** : un code moins lisible pour un
gain nul est une mauvaise affaire.

Garder ce resultat negatif dans la fiche est volontaire. Une optimisation qui
ne donne rien est une information, pas un echec.

## Ce qui marche vraiment : decouper pour le cache

Le decoupage **ne reduit pas** le poids total. Il change ce que le navigateur
doit **retelecharger**.

En un seul fichier, la moindre virgule modifiee dans `App.jsx` change
l'empreinte du fichier, donc son nom : le visiteur retelecharge 516 kB, dont
450 de bibliotheques qui n'ont pas bouge d'un octet.

```js
// vite.config.js
advancedChunks: {
  groups: [
    { name: 'react', test: /node_modules[\/](react|react-dom|scheduler)[\/]/ },
    { name: 'mui', test: /node_modules[\/](@mui|@emotion)[\/]/ },
    { name: 'socketio', test: /node_modules[\/](socket\.io|engine\.io)/ },
  ],
}
```

| Fichier | Taille | Change a chaque deploiement ? |
|---------|--------|-------------------------------|
| `mui-*.js` | 264,8 kB | non |
| `react-*.js` | 189,6 kB | non |
| `socketio-*.js` | 41,2 kB | non |
| `index-*.js` | 20,1 kB | **oui** |

Le nom de chaque fichier contient une empreinte de son contenu. Tant que React
ne change pas, son fichier garde le meme nom et le navigateur le ressort de son
cache sans rien demander.

**Le bilan honnete** : le total passe de 509 a 516 kB — le premier chargement
est donc tres legerement plus lourd, a cause des frontieres entre morceaux. En
revanche, apres chaque deploiement, un visiteur deja venu telecharge **20 kB au
lieu de 516**. Vingt-cinq fois moins, pour tous les deploiements a venir.

## Note sur rolldown

Vite 8 n'utilise plus rollup mais **rolldown**, sa reecriture en Rust. La
premiere tentative de configuration, ecrite avec `build.rollupOptions.output
.manualChunks`, a ete **silencieusement ignoree** — le build reussissait, sans
aucun effet. L'avertissement affiche a chaque build donnait pourtant le bon
nom : `build.rolldownOptions.output.codeSplitting`.

Encore un message d'erreur qui disait quoi faire et qu'on avait cesse de lire.

## Exercice

1. Ouvre le site, puis l'onglet **Réseau** des outils de developpement, et
   recharge : tu verras les quatre fichiers arriver en parallele.
2. Coche **Disable cache**, recharge : tout est retelecharge. Decoche, recharge :
   les fichiers repassent en "(disk cache)". C'est ca qu'on a optimise.
3. Modifie une couleur dans `theme.js`, `npm run build`, et compare les noms de
   fichiers avec les precedents. Lequel a change de nom ? Lesquels non ?
4. Question ouverte : `socket.io-client` (41 kB) n'est utile qu'une fois
   connecte, jamais sur la page de login. Cherche `React.lazy` et demande-toi ce
   qu'il faudrait decouper pour ne le charger qu'apres la connexion — et si le
   gain vaut la complexite ajoutee.
