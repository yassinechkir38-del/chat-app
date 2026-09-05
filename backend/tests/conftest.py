"""Preparation des tests d'integration.

Ceux-ci ont besoin d'une vraie base PostgreSQL : `app.py` ouvre une connexion
et cree ses tables des l'import, et le SQL utilise des types propres a
PostgreSQL (SERIAL, RETURNING, ON CONFLICT). Un SQLite en memoire ne suffirait
pas.

La base est donnee par TEST_DATABASE_URL. Si la variable est absente, les tests
d'integration sont ignores plutot que d'echouer : on ne veut pas qu'un
developpeur sans base sous la main voie une suite rouge. En integration
continue, elle pointe vers le PostgreSQL demarre par GitHub Actions.

Jamais, au grand jamais, vers la base de production : les tests creent et
suppriment des comptes.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

URL_TEST = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def application():
    if not URL_TEST:
        pytest.skip("TEST_DATABASE_URL absente : tests d'integration ignores")

    # app.py lit ces variables avec os.environ[...] : sans elles, l'import
    # echoue immediatement (c'est voulu, cf. Seance 8).
    os.environ["DATABASE_URL"] = URL_TEST
    os.environ.setdefault("SECRET_KEY", "cle-de-test-sans-valeur")
    os.environ.setdefault("MAILJET_API_KEY", "test")
    os.environ.setdefault("MAILJET_SECRET_KEY", "test")
    os.environ.setdefault("MAIL_FROM", "test@exemple.test")
    os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")

    import app as module_app
    module_app.app.config["TESTING"] = True
    return module_app


@pytest.fixture
def client(application):
    with application.app.test_client() as c:
        yield c


@pytest.fixture
def compte(client):
    """Cree un compte au nom unique et renvoie ses informations.

    Le nom est tire au hasard : deux executions successives ne doivent pas se
    marcher dessus, et la contrainte UNIQUE sur `username` refuserait le
    deuxieme passage.
    """
    identifiant = uuid.uuid4().hex[:12]
    donnees = {
        "username": f"test_{identifiant}",
        "email": f"test_{identifiant}@exemple.test",
        "password": "motdepasse-de-test",
    }
    reponse = client.post("/register", json=donnees)
    assert reponse.status_code == 201, reponse.get_json()
    return {**donnees, "token": reponse.get_json()["token"]}
