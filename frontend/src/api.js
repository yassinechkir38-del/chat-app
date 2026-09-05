// En developpement : le backend local. En production (npm run build) : la valeur
// de VITE_API_URL, definie dans .env.production.
const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5050';

export function inscrire(username, email, password) {
  return fetch(`${BASE_URL}/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  });
}

export function connecter(username, password) {
  return fetch(`${BASE_URL}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function motDePasseOublie(email) {
  return fetch(`${BASE_URL}/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
}

export function reinitialiserMotDePasse(token, password) {
  return fetch(`${BASE_URL}/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
  });
}

export const SOCKET_URL = BASE_URL;

// ---------- images ----------

// Une photo de telephone fait 3 a 5 Mo. La reduire AVANT l'envoi divise le
// poids par 20 et se fait entierement dans le navigateur : ni le serveur ni le
// stockage n'ont a manipuler le fichier d'origine.
export function redimensionner(fichier, maxCote = 1280, qualite = 0.82) {
  // Un GIF anime perdrait son animation en passant par un canvas : on le laisse
  // tel quel s'il est raisonnable.
  if (fichier.type === 'image/gif' && fichier.size < 3 * 1024 * 1024) {
    return Promise.resolve(fichier);
  }
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(fichier);
    image.onload = () => {
      URL.revokeObjectURL(url);
      const echelle = Math.min(1, maxCote / Math.max(image.width, image.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(image.width * echelle);
      canvas.height = Math.round(image.height * echelle);
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error('Conversion impossible'))),
        'image/jpeg',
        qualite,
      );
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Fichier illisible'));
    };
    image.src = url;
  });
}

// Deux etapes : le backend signe une autorisation, puis le navigateur envoie le
// fichier directement au stockage. Le fichier ne passe jamais par notre serveur.
export async function televerserImage(token, fichier) {
  const reponse = await fetch(`${BASE_URL}/signature-upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!reponse.ok) {
    const { erreur } = await reponse.json().catch(() => ({}));
    throw new Error(erreur || "Envoi d'images indisponible");
  }
  const { cloud_name, api_key, folder, timestamp, signature } = await reponse.json();

  const formulaire = new FormData();
  formulaire.append('file', fichier);
  formulaire.append('api_key', api_key);
  formulaire.append('folder', folder);
  formulaire.append('timestamp', timestamp);
  formulaire.append('signature', signature);

  const envoi = await fetch(`https://api.cloudinary.com/v1_1/${cloud_name}/image/upload`, {
    method: 'POST',
    body: formulaire,
  });
  if (!envoi.ok) throw new Error('Le stockage a refuse le fichier');
  const { secure_url } = await envoi.json();
  return secure_url;
}
