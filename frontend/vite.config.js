import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        // Decouper le bundle ne le rend pas plus petit -- le navigateur
        // telecharge le meme total au premier chargement. Ce que ca change,
        // c'est ce qu'il retelecharge aux visites suivantes.
        //
        // En un seul fichier, la moindre modification d'App.jsx change son
        // empreinte : le visiteur retelecharge les 516 kB, dont 450 de
        // bibliotheques qui n'ont pas bouge d'un octet.
        //
        // Separes, React et MUI gardent le meme nom de fichier d'un
        // deploiement a l'autre et restent en cache. Seul le morceau qui
        // contient notre code est retelecharge -- environ 20 kB.
        advancedChunks: {
          groups: [
            { name: 'react', test: /node_modules[\/](react|react-dom|scheduler)[\/]/ },
            { name: 'mui', test: /node_modules[\/](@mui|@emotion)[\/]/ },
            { name: 'socketio', test: /node_modules[\/](socket\.io|engine\.io)/ },
          ],
        },
      },
    },
  },
})
