"""Tests des fonctions pures : aucune base, aucun reseau, aucune variable
d'environnement. Ils tournent en une fraction de seconde, partout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outils import (  # noqa: E402
    config_cloudinary_depuis_url,
    image_valide,
    nom_conversation,
    salle_de_frappe,
)

PREFIXE = "https://res.cloudinary.com/svg1sjgd/"


# ---------- nom_conversation ----------

def test_meme_nom_quel_que_soit_l_ordre():
    """La regle qui fait tenir les messages prives : deux utilisateurs doivent
    calculer le meme nom de room sans s'etre concertes."""
    assert nom_conversation("alice", "bob") == nom_conversation("bob", "alice")

def test_deux_paires_differentes_ne_se_croisent_pas():
    assert nom_conversation("alice", "bob") != nom_conversation("alice", "carol")

def test_prefixe_dm():
    assert nom_conversation("bob", "alice") == "dm_alice_bob"


# ---------- image_valide ----------

def test_accepte_une_url_de_notre_compte():
    url = PREFIXE + "image/upload/v1/chat-app/photo.jpg"
    assert image_valide(url, PREFIXE) == url

def test_refuse_une_url_hebergee_ailleurs():
    """Le coeur du controle : une image externe permettrait a son auteur de
    relever l'adresse IP de tous ceux qui l'affichent."""
    assert image_valide("https://exemple.test/pixel.gif", PREFIXE) is None

def test_refuse_un_autre_compte_cloudinary():
    autre = "https://res.cloudinary.com/quelqu-un-dautre/image/upload/x.jpg"
    assert image_valide(autre, PREFIXE) is None

def test_refuse_ce_qui_n_est_pas_une_chaine():
    assert image_valide({"url": "..."}, PREFIXE) is None
    assert image_valide(None, PREFIXE) is None

def test_refuse_tout_si_le_stockage_n_est_pas_configure():
    """Sans prefixe connu, on ne peut rien valider : on refuse plutot que
    d'accepter n'importe quoi."""
    assert image_valide(PREFIXE + "photo.jpg", None) is None


# ---------- config_cloudinary_depuis_url ----------

def test_lit_la_ligne_du_tableau_de_bord():
    cloud, cle, secret = config_cloudinary_depuis_url(
        "CLOUDINARY_URL=cloudinary://123456:UNSECRET@moncloud"
    )
    assert (cloud, cle, secret) == ("moncloud", "123456", "UNSECRET")

def test_lit_aussi_l_url_sans_le_prefixe():
    assert config_cloudinary_depuis_url("cloudinary://123456:UNSECRET@moncloud")[2] == "UNSECRET"

def test_tolere_espaces_et_retour_a_la_ligne():
    """Le cas reel qui a coute une soiree : un copier-coller dans un formulaire
    web ramene souvent un caractere invisible."""
    assert config_cloudinary_depuis_url("  cloudinary://1:S@c \n")[2] == "S"

def test_refuse_une_valeur_qui_n_est_pas_une_url_cloudinary():
    assert config_cloudinary_depuis_url("juste-un-secret") == (None, None, None)
    assert config_cloudinary_depuis_url("") == (None, None, None)
    assert config_cloudinary_depuis_url(None) == (None, None, None)


# ---------- salle_de_frappe ----------

def test_frappe_dans_le_salon():
    infos = {"salon": "general", "conversation": "dm_alice_bob"}
    assert salle_de_frappe(infos, prive=False) == "general"

def test_frappe_dans_la_conversation_privee():
    """Un utilisateur qui ouvre un DM reste membre de son salon : sans le
    drapeau `prive`, l'indicateur partirait au mauvais endroit."""
    infos = {"salon": "general", "conversation": "dm_alice_bob"}
    assert salle_de_frappe(infos, prive=True) == "dm_alice_bob"

def test_aucune_salle_si_l_utilisateur_n_a_rien_rejoint():
    assert salle_de_frappe({}, prive=False) is None
    assert salle_de_frappe({}, prive=True) is None
