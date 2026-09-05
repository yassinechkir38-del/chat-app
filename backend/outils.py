"""Fonctions pures du backend : ni base de donnees, ni reseau, ni etat global.

Elles sont regroupees ici pour une raison precise : `app.py` ne peut pas
s'importer sans une base PostgreSQL joignable et six variables d'environnement
definies -- il ouvre une connexion et cree les tables des l'import. Impossible,
donc, de tester quoi que ce soit sans monter toute l'infrastructure.

Une fonction pure, elle, se teste en une ligne : on lui donne une entree, on
verifie sa sortie. C'est le decoupage qui rend les tests possibles, pas
l'inverse.
"""

from urllib.parse import urlparse


def config_cloudinary_depuis_url(brut):
    """Extrait (cloud_name, api_key, api_secret) de la ligne fournie par Cloudinary.

    Format officiel : cloudinary://<api_key>:<api_secret>@<cloud_name>
    On tolere le prefixe "CLOUDINARY_URL=" que le tableau de bord affiche devant.
    """
    if not brut:
        return None, None, None
    brut = brut.strip()
    if brut.startswith("CLOUDINARY_URL="):
        brut = brut[len("CLOUDINARY_URL="):].strip()
    adresse = urlparse(brut)
    if adresse.scheme != "cloudinary":
        return None, None, None
    return adresse.hostname, adresse.username, adresse.password


def nom_conversation(a, b):
    """Nom de room d'une conversation privee, identique quel que soit l'ordre.

    `sorted` est tout le secret : nom_conversation("alice", "bob") et
    nom_conversation("bob", "alice") donnent la meme chaine, donc les deux
    utilisateurs rejoignent la meme room sans s'etre mis d'accord.
    """
    return "dm_" + "_".join(sorted([a, b]))


def image_valide(url, prefixe):
    """N'accepte qu'une URL provenant de NOTRE compte de stockage.

    Sans ce controle, le champ image_url accepterait n'importe quelle adresse :
    on pourrait faire afficher une image hebergee ailleurs dans le chat, et
    l'auteur de cette image verrait l'adresse IP de tous ceux qui la chargent.
    """
    if not url or not prefixe or not isinstance(url, str):
        return None
    return url if url.startswith(prefixe) else None


def salle_de_frappe(infos, prive):
    """Ou envoyer l'indicateur de frappe : la conversation privee ou le salon.

    Un utilisateur qui ouvre un DM reste membre de la room de son salon (il
    continue d'en recevoir les messages). Le serveur ne peut donc pas deviner
    ou il ecrit : c'est le client qui le dit, via `prive`.
    """
    return infos.get("conversation") if prive else infos.get("salon")
