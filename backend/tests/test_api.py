"""Tests d'integration des routes HTTP : une vraie base, un vrai client Flask.

Ils ne testent pas les WebSockets -- c'est un autre monde, avec son propre
client de test -- mais tout ce qui se passe avant : creation de compte,
connexion, et le controle du jeton sur les routes protegees.
"""


def test_salons_est_public(client):
    """La seule route qui ne demande pas de jeton."""
    reponse = client.get("/salons")
    assert reponse.status_code == 200
    assert "general" in reponse.get_json()


def test_inscription_renvoie_un_jeton(compte):
    assert compte["token"]


def test_inscription_refuse_un_nom_deja_pris(client, compte):
    reponse = client.post("/register", json={
        "username": compte["username"],
        "email": "autre@exemple.test",
        "password": "peu-importe",
    })
    assert reponse.status_code == 400


def test_inscription_refuse_un_champ_manquant(client):
    reponse = client.post("/register", json={"username": "sans-email"})
    assert reponse.status_code == 400


def test_connexion_avec_les_bons_identifiants(client, compte):
    reponse = client.post("/login", json={
        "username": compte["username"], "password": compte["password"],
    })
    assert reponse.status_code == 200
    assert reponse.get_json()["username"] == compte["username"]


def test_connexion_refuse_un_mauvais_mot_de_passe(client, compte):
    reponse = client.post("/login", json={
        "username": compte["username"], "password": "ce-n-est-pas-le-bon",
    })
    assert reponse.status_code == 401


def test_connexion_refuse_un_compte_inexistant(client):
    reponse = client.post("/login", json={
        "username": "personne-de-ce-nom", "password": "x",
    })
    assert reponse.status_code == 401


def test_le_mot_de_passe_n_est_jamais_stocke_en_clair(application, compte):
    """Verification directe en base : c'est une empreinte qui est enregistree,
    pas le mot de passe. Une fuite de la base ne doit pas livrer les comptes."""
    from sqlalchemy import text
    with application.engine.connect() as conn:
        empreinte = conn.execute(
            text("SELECT password_hash FROM users WHERE username = :u"),
            {"u": compte["username"]},
        ).scalar()
    assert compte["password"] not in empreinte
    assert empreinte.startswith(("pbkdf2:", "scrypt:", "argon2"))


def test_signature_upload_exige_un_jeton(client):
    """La route qui signe les envois d'images : sans jeton, n'importe qui
    pourrait obtenir un droit d'ecriture sur le compte de stockage."""
    assert client.post("/signature-upload").status_code == 401


def test_signature_upload_refuse_un_jeton_bidon(client):
    reponse = client.post("/signature-upload",
                          headers={"Authorization": "Bearer pas-un-vrai-jeton"})
    assert reponse.status_code == 401


def test_signature_upload_accepte_un_jeton_valide(client, compte):
    reponse = client.post("/signature-upload",
                          headers={"Authorization": f"Bearer {compte['token']}"})
    # 200 si le stockage est configure, 503 sinon : dans les deux cas le jeton
    # a ete accepte, ce qui est l'objet du test.
    assert reponse.status_code in (200, 503)
