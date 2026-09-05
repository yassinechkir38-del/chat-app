from gevent import monkey
monkey.patch_all()

import os
from datetime import datetime, timedelta, timezone
from functools import wraps
from hashlib import sha1
from time import time

import jwt
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from sqlalchemy import bindparam, create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

@app.after_request
def ajouter_cors(reponse):
    reponse.headers["Access-Control-Allow-Origin"] = "*"
    reponse.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    reponse.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return reponse

SECRET_KEY = os.environ["SECRET_KEY"]
MAILJET_API_KEY = os.environ["MAILJET_API_KEY"]
MAILJET_SECRET_KEY = os.environ["MAILJET_SECRET_KEY"]
MAIL_FROM = os.environ["MAIL_FROM"]
FRONTEND_URL = os.environ["FRONTEND_URL"]

# --- Stockage des images (Cloudinary) ------------------------------------
# Ces variables-la sont lues avec .get() et non avec des crochets, contrairement
# a toutes les autres. Raison : sans elles l'app doit continuer de tourner, avec
# l'envoi d'images simplement desactive. Une variable dont l'absence ne doit pas
# tuer le service est une option ; une variable sans laquelle l'app n'a aucun
# sens (SECRET_KEY, DATABASE_URL) doit au contraire la faire crasher au demarrage.
# .strip() : un copier-coller dans un formulaire web ramene souvent un espace
# ou un retour a la ligne invisible. Sur un secret, cela produit une signature
# fausse et un message d'erreur qui n'a aucun rapport avec la cause.
CLOUDINARY_CLOUD_NAME = (os.environ.get("CLOUDINARY_CLOUD_NAME") or "").strip() or None
CLOUDINARY_API_KEY = (os.environ.get("CLOUDINARY_API_KEY") or "").strip() or None
CLOUDINARY_API_SECRET = (os.environ.get("CLOUDINARY_API_SECRET") or "").strip() or None
CLOUDINARY_DOSSIER = "chat-app"

IMAGES_ACTIVES = all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET])
PREFIXE_IMAGE = f"https://res.cloudinary.com/{CLOUDINARY_CLOUD_NAME}/" if CLOUDINARY_CLOUD_NAME else None

app.config["SECRET_KEY"] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            pseudo TEXT NOT NULL,
            texte TEXT NOT NULL,
            envoye_le TIMESTAMP DEFAULT NOW()
        )
    """))
    conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS salon TEXT NOT NULL DEFAULT 'general'"))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS messages_prives (
            id SERIAL PRIMARY KEY,
            expediteur TEXT NOT NULL,
            destinataire TEXT NOT NULL,
            texte TEXT NOT NULL,
            envoye_le TIMESTAMP DEFAULT NOW()
        )
    """))
    # Une reponse pointe vers un message de la MEME table. Colonne ajoutee
    # apres coup : les messages deja en base gardent repond_a a NULL.
    conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS repond_a INTEGER"))
    conn.execute(text("ALTER TABLE messages_prives ADD COLUMN IF NOT EXISTS repond_a INTEGER"))
    # On ne stocke que l'URL de l'image, jamais le fichier : la base sert aux
    # donnees, le stockage objet aux fichiers.
    conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS image_url TEXT"))
    conn.execute(text("ALTER TABLE messages_prives ADD COLUMN IF NOT EXISTS image_url TEXT"))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS reactions (
            id SERIAL PRIMARY KEY,
            message_id INTEGER NOT NULL,
            prive BOOLEAN NOT NULL DEFAULT FALSE,
            pseudo TEXT NOT NULL,
            emoji TEXT NOT NULL,
            UNIQUE (message_id, prive, pseudo, emoji)
        )
    """))
    # Une ligne par personne et par salle : "jusqu'ou cette personne a lu".
    # `salle` est le nom de la room socket.io -- "general" ou "dm_alice_bob" --
    # ce qui fait marcher le meme mecanisme pour les salons et les DM.
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS lectures (
            pseudo TEXT NOT NULL,
            salle TEXT NOT NULL,
            dernier_message_id INTEGER NOT NULL,
            maj_le TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (pseudo, salle)
        )
    """))
    conn.commit()

def nom_conversation(a, b):
    return "dm_" + "_".join(sorted([a, b]))

SALONS = ["general", "aleatoire", "aide"]
# Liste blanche : on n'enregistre que ces cinq emojis. Sans elle, "emoji"
# serait un champ texte libre ou n'importe qui pourrait stocker n'importe quoi.
EMOJIS = ["👍", "❤️", "😂", "😮", "😢"]

def _reactions_pour(ids, prive):
    """Renvoie {message_id: [{"emoji": ..., "pseudos": [...]}, ...]}.

    Une seule requete pour tous les messages de l'historique : une requete par
    message ferait 30 allers-retours vers la base a chaque ouverture de salon.
    """
    if not ids:
        return {}
    requete = text(
        "SELECT message_id, emoji, pseudo FROM reactions "
        "WHERE prive = :prive AND message_id IN :ids ORDER BY id"
    ).bindparams(bindparam("ids", expanding=True))
    with engine.connect() as conn:
        lignes = conn.execute(requete, {"prive": prive, "ids": list(ids)}).fetchall()

    par_message = {}
    for ligne in lignes:
        par_emoji = par_message.setdefault(ligne.message_id, {})
        par_emoji.setdefault(ligne.emoji, []).append(ligne.pseudo)
    return {
        mid: [{"emoji": e, "pseudos": p} for e, p in par_emoji.items()]
        for mid, par_emoji in par_message.items()
    }

def _image_valide(url):
    """N'accepte qu'une URL provenant de NOTRE compte de stockage.

    Sans ce controle, le champ image_url accepterait n'importe quelle adresse :
    on pourrait faire afficher une image hebergee ailleurs dans le chat, et
    l'auteur de cette image verrait l'adresse IP de tous ceux qui la chargent.
    """
    if not url or not PREFIXE_IMAGE or not isinstance(url, str):
        return None
    return url if url.startswith(PREFIXE_IMAGE) else None

def _lectures_de(salle):
    """{pseudo: id du dernier message lu} pour une salle donnee."""
    with engine.connect() as conn:
        lignes = conn.execute(
            text("SELECT pseudo, dernier_message_id FROM lectures WHERE salle = :salle"),
            {"salle": salle},
        ).fetchall()
    return {ligne.pseudo: ligne.dernier_message_id for ligne in lignes}

def _formater_message(ligne):
    """Transforme une ligne SQL en dictionnaire pret a partir sur le socket.

    Les deux colonnes cite_pseudo / cite_texte viennent du LEFT JOIN sur la
    table elle-meme ; on les replie en un seul champ `repond_a`, qui vaut
    None quand le message ne cite rien.
    """
    m = dict(ligne._mapping)
    m["envoye_le"] = m["envoye_le"].isoformat()
    cite_pseudo = m.pop("cite_pseudo", None)
    cite_texte = m.pop("cite_texte", None)
    m["repond_a"] = {"pseudo": cite_pseudo, "texte": cite_texte[:APERCU_MAX]} if cite_pseudo else None
    return m

def _attacher_reactions(messages, prive):
    reactions = _reactions_pour([m["id"] for m in messages], prive)
    for m in messages:
        m["reactions"] = reactions.get(m["id"], [])
    return messages
utilisateurs_connectes = {}  # sid -> {"username": ..., "salon": ...}

# ---------- authentification (meme pattern que le todo-app) ----------

def generer_token(user_id):
    return jwt.encode(
        {"user_id": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=7)},
        SECRET_KEY,
        algorithm="HS256",
    )

def generer_token_reset(user_id):
    return jwt.encode(
        {"user_id": user_id, "type": "reset", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
        SECRET_KEY,
        algorithm="HS256",
    )

def envoyer_email(destinataire, sujet, html):
    reponse = requests.post(
        "https://api.mailjet.com/v3.1/send",
        auth=(MAILJET_API_KEY, MAILJET_SECRET_KEY),
        json={"Messages": [{
            "From": {"Email": MAIL_FROM, "Name": "Chat"},
            "To": [{"Email": destinataire}],
            "Subject": sujet,
            "HTMLPart": html,
        }]},
        timeout=10,
    )
    reponse.raise_for_status()

def token_requis(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"erreur": "Authentification requise"}), 401
        try:
            donnees = jwt.decode(auth[7:], SECRET_KEY, algorithms=["HS256"])
        except jwt.InvalidTokenError:
            return jsonify({"erreur": "Token invalide ou expire"}), 401
        return f(donnees["user_id"], *args, **kwargs)
    return wrapper

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("email") or not data.get("password"):
        return jsonify({"erreur": "username, email et password requis"}), 400

    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT id FROM users WHERE username = :u OR email = :e"),
            {"u": data["username"], "e": data["email"]},
        ).fetchone()
        if existe:
            return jsonify({"erreur": "Ce nom d'utilisateur ou cet email existe deja"}), 400

        resultat = conn.execute(
            text("INSERT INTO users (username, email, password_hash) VALUES (:u, :e, :p) RETURNING id"),
            {"u": data["username"], "e": data["email"], "p": generate_password_hash(data["password"])},
        )
        conn.commit()
        user_id = resultat.fetchone()[0]

    return jsonify({"token": generer_token(user_id), "username": data["username"]}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"erreur": "username et password requis"}), 400

    with engine.connect() as conn:
        ligne = conn.execute(
            text("SELECT id, username, password_hash FROM users WHERE username = :u"),
            {"u": data["username"]},
        ).fetchone()

    if not ligne or not check_password_hash(ligne.password_hash, data["password"]):
        return jsonify({"erreur": "Identifiants invalides"}), 401

    return jsonify({"token": generer_token(ligne.id), "username": ligne.username})

@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify({"erreur": "email requis"}), 400

    with engine.connect() as conn:
        ligne = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": data["email"]}).fetchone()

    if ligne:
        token = generer_token_reset(ligne.id)
        lien = f"{FRONTEND_URL}/reset-password?token={token}"
        envoyer_email(
            data["email"],
            "Reinitialisation de mot de passe - Chat",
            f'<p>Clique sur ce lien pour choisir un nouveau mot de passe (valable 30 minutes) :</p><p><a href="{lien}">{lien}</a></p>',
        )

    return jsonify({"message": "Si ce compte existe, un email a ete envoye."})

@app.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json()
    if not data or not data.get("token") or not data.get("password"):
        return jsonify({"erreur": "token et password requis"}), 400

    try:
        donnees = jwt.decode(data["token"], SECRET_KEY, algorithms=["HS256"])
        if donnees.get("type") != "reset":
            raise jwt.InvalidTokenError
    except jwt.InvalidTokenError:
        return jsonify({"erreur": "Lien invalide ou expire"}), 400

    with engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET password_hash = :p WHERE id = :id"),
            {"p": generate_password_hash(data["password"]), "id": donnees["user_id"]},
        )
        conn.commit()

    return jsonify({"message": "Mot de passe mis a jour"})

@app.route("/signature-upload", methods=["POST"])
@token_requis
def signature_upload(_user_id):
    """Signe une autorisation d'envoi valable quelques minutes.

    Le fichier ne transite jamais par ce serveur : il irait du navigateur vers
    Render, puis de Render vers le stockage, pour rien -- en saturant au passage
    la petite instance gratuite. Le backend ne fait que signer.

    La signature est un sha1 des parametres tries, suivis du secret. Le secret
    ne quitte donc jamais le serveur : le navigateur recoit une signature, pas
    de quoi en fabriquer d'autres.
    """
    if not IMAGES_ACTIVES:
        return jsonify({"erreur": "Envoi d'images non configure sur ce serveur"}), 503

    horodatage = int(time())
    a_signer = f"folder={CLOUDINARY_DOSSIER}&timestamp={horodatage}{CLOUDINARY_API_SECRET}"
    return jsonify({
        "cloud_name": CLOUDINARY_CLOUD_NAME,
        "api_key": CLOUDINARY_API_KEY,
        "folder": CLOUDINARY_DOSSIER,
        "timestamp": horodatage,
        "signature": sha1(a_signer.encode()).hexdigest(),
    })

@app.route("/salons", methods=["GET"])
def lister_salons():
    return jsonify(SALONS)

# ---------- websockets, maintenant securises par JWT ----------

def utilisateur_depuis_token(token):
    try:
        donnees = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    with engine.connect() as conn:
        ligne = conn.execute(text("SELECT username FROM users WHERE id = :id"), {"id": donnees["user_id"]}).fetchone()
    return ligne.username if ligne else None

@socketio.on("connect")
def gerer_connexion(auth):
    username = utilisateur_depuis_token((auth or {}).get("token", ""))
    if not username:
        return False  # refuse la connexion : pas de token valide
    utilisateurs_connectes[request.sid] = {"username": username, "salon": None}

@socketio.on("disconnect")
def gerer_deconnexion():
    infos = utilisateurs_connectes.pop(request.sid, None)
    if infos and infos["salon"]:
        emit("systeme", {"texte": f"{infos['username']} a quitte le salon"}, to=infos["salon"])
        emit("utilisateurs_en_ligne", _pseudos_du_salon(infos["salon"]), to=infos["salon"])

def _pseudos_du_salon(salon):
    return [v["username"] for v in utilisateurs_connectes.values() if v["salon"] == salon]

@socketio.on("rejoindre_salon")
def gerer_rejoindre(data):
    salon = data.get("salon")
    if salon not in SALONS:
        return
    infos = utilisateurs_connectes.get(request.sid)
    if not infos:
        return

    ancien_salon = infos["salon"]
    if ancien_salon and ancien_salon != salon:
        leave_room(ancien_salon)
        infos["salon"] = None
        emit("systeme", {"texte": f"{infos['username']} a quitte le salon"}, to=ancien_salon)
        emit("utilisateurs_en_ligne", _pseudos_du_salon(ancien_salon), to=ancien_salon)

    infos["salon"] = salon
    join_room(salon)

    with engine.connect() as conn:
        resultat = conn.execute(
            text("""
                SELECT m.id, m.pseudo, m.texte, m.envoye_le, m.image_url,
                       cite.pseudo AS cite_pseudo, cite.texte AS cite_texte
                FROM messages m
                LEFT JOIN messages cite ON cite.id = m.repond_a
                WHERE m.salon = :s
                ORDER BY m.id DESC LIMIT 30
            """),
            {"s": salon},
        )
        derniers_messages = [_formater_message(ligne) for ligne in resultat]
    derniers_messages.reverse()
    emit("historique", _attacher_reactions(derniers_messages, prive=False))
    emit("lectures", {"prive": False, "lectures": _lectures_de(salon)})

    emit("systeme", {"texte": f"{infos['username']} a rejoint le salon"}, to=salon, include_self=False)
    emit("utilisateurs_en_ligne", _pseudos_du_salon(salon), to=salon)

def _salle_de_frappe(infos, prive):
    """Ou envoyer l'indicateur de frappe : la conversation privee ou le salon.

    Un utilisateur qui ouvre un DM reste membre de la room de son salon (il
    continue d'en recevoir les messages). Le serveur ne peut donc pas deviner
    ou il est en train d'ecrire : c'est le client qui le dit, via `prive`.
    """
    return infos.get("conversation") if prive else infos.get("salon")

@socketio.on("en_train_ecrire")
def gerer_ecriture(data=None):
    infos = utilisateurs_connectes.get(request.sid)
    if not infos:
        return
    prive = bool((data or {}).get("prive"))
    salle = _salle_de_frappe(infos, prive)
    if salle:
        emit("quelquun_ecrit", {"pseudo": infos["username"], "prive": prive}, to=salle, include_self=False)

@socketio.on("arrete_ecrire")
def gerer_arret_ecriture(data=None):
    infos = utilisateurs_connectes.get(request.sid)
    if not infos:
        return
    prive = bool((data or {}).get("prive"))
    salle = _salle_de_frappe(infos, prive)
    if salle:
        emit("plus_personne_ecrit", {"pseudo": infos["username"], "prive": prive}, to=salle, include_self=False)

@socketio.on("message_envoye")
def gerer_message(data):
    infos = utilisateurs_connectes.get(request.sid)
    if not infos or not infos["salon"]:
        return
    # Citation : si l'id est invalide ou hors de portee, on ignore la citation
    # au lieu de refuser le message. L'utilisateur ne perd pas ce qu'il a ecrit.
    apercu = _apercu_si_visible(infos, data.get("repond_a"), prive=False)
    repond_a = data.get("repond_a") if apercu else None
    image_url = _image_valide(data.get("image_url"))
    texte = (data.get("texte") or "").strip()
    if not texte and not image_url:  # un message vide n'a rien a faire en base
        return

    with engine.connect() as conn:
        resultat = conn.execute(
            text("""
                INSERT INTO messages (pseudo, texte, salon, repond_a, image_url)
                VALUES (:pseudo, :texte, :salon, :repond_a, :image_url) RETURNING id, envoye_le
            """),
            {"pseudo": infos["username"], "texte": texte, "salon": infos["salon"],
             "repond_a": repond_a, "image_url": image_url},
        )
        message_id, envoye_le = resultat.fetchone()
        conn.commit()
    emit(
        "nouveau_message",
        {
            "id": message_id,
            "pseudo": infos["username"],
            "texte": texte,
            "envoye_le": envoye_le.isoformat(),
            "reactions": [],
            "repond_a": apercu,
            "image_url": image_url,
        },
        to=infos["salon"],
    )

# ---------- messages prives ----------

@socketio.on("rejoindre_conversation")
def gerer_rejoindre_conversation(data):
    autre = data.get("avec")
    infos = utilisateurs_connectes.get(request.sid)
    if not infos or not autre:
        return

    ancienne = infos.get("conversation")
    if ancienne:
        leave_room(ancienne)

    conversation = nom_conversation(infos["username"], autre)
    infos["conversation"] = conversation
    infos["conversation_avec"] = autre
    join_room(conversation)

    with engine.connect() as conn:
        resultat = conn.execute(
            text("""
                SELECT m.id, m.expediteur, m.destinataire, m.texte, m.envoye_le, m.image_url,
                       cite.expediteur AS cite_pseudo, cite.texte AS cite_texte
                FROM messages_prives m
                LEFT JOIN messages_prives cite ON cite.id = m.repond_a
                WHERE (m.expediteur = :moi AND m.destinataire = :autre)
                   OR (m.expediteur = :autre AND m.destinataire = :moi)
                ORDER BY m.id DESC LIMIT 30
            """),
            {"moi": infos["username"], "autre": autre},
        )
        derniers_messages = [_formater_message(ligne) for ligne in resultat]
    derniers_messages.reverse()
    emit("historique_prive", _attacher_reactions(derniers_messages, prive=True))
    emit("lectures", {"prive": True, "lectures": _lectures_de(conversation)})

@socketio.on("message_prive_envoye")
def gerer_message_prive(data):
    infos = utilisateurs_connectes.get(request.sid)
    if not infos or not infos.get("conversation"):
        return
    autre = infos["conversation_avec"]
    apercu = _apercu_si_visible(infos, data.get("repond_a"), prive=True)
    repond_a = data.get("repond_a") if apercu else None
    image_url = _image_valide(data.get("image_url"))
    texte = (data.get("texte") or "").strip()
    if not texte and not image_url:
        return

    with engine.connect() as conn:
        resultat = conn.execute(
            text("""
                INSERT INTO messages_prives (expediteur, destinataire, texte, repond_a, image_url)
                VALUES (:e, :d, :t, :r, :img) RETURNING id, envoye_le
            """),
            {"e": infos["username"], "d": autre, "t": texte, "r": repond_a, "img": image_url},
        )
        message_id, envoye_le = resultat.fetchone()
        conn.commit()
    emit(
        "nouveau_message_prive",
        {
            "id": message_id,
            "expediteur": infos["username"],
            "destinataire": autre,
            "texte": texte,
            "envoye_le": envoye_le.isoformat(),
            "reactions": [],
            "repond_a": apercu,
            "image_url": image_url,
        },
        to=infos["conversation"],
    )

# ---------- accuses de lecture ----------

@socketio.on("marquer_lu")
def gerer_lecture(data):
    infos = utilisateurs_connectes.get(request.sid)
    if not infos:
        return
    prive = bool((data or {}).get("prive"))
    message_id = (data or {}).get("message_id")
    salle = _salle_de_frappe(infos, prive)
    if not salle or _apercu_si_visible(infos, message_id, prive) is None:
        return

    with engine.connect() as conn:
        # GREATEST : un accuse de lecture ne recule jamais. Sans lui, ouvrir
        # un vieux message ferait regresser la position deja enregistree.
        resultat = conn.execute(
            text("""
                INSERT INTO lectures (pseudo, salle, dernier_message_id, maj_le)
                VALUES (:pseudo, :salle, :message_id, NOW())
                ON CONFLICT (pseudo, salle) DO UPDATE
                SET dernier_message_id = GREATEST(lectures.dernier_message_id, EXCLUDED.dernier_message_id),
                    maj_le = NOW()
                RETURNING dernier_message_id
            """),
            {"pseudo": infos["username"], "salle": salle, "message_id": message_id},
        )
        position = resultat.scalar()
        conn.commit()

    # On diffuse la position reellement enregistree, pas celle recue : si le
    # client etait en retard, les autres ne doivent pas voir l'accuse reculer.
    emit(
        "lecture_maj",
        {"pseudo": infos["username"], "message_id": position, "prive": prive},
        to=salle,
    )

# ---------- reactions emoji ----------

APERCU_MAX = 120  # on ne cite pas un roman au-dessus d'un message

def _apercu_si_visible(infos, message_id, prive):
    """Renvoie {"pseudo", "texte"} si l'utilisateur a le droit de voir ce
    message, sinon None.

    Sert deux fois : pour reagir, et pour citer. Sans ce controle, n'importe
    qui pourrait envoyer un id au hasard et atteindre un message prive entre
    deux autres personnes. On ne fait jamais confiance a un id venu du client.
    """
    if not isinstance(message_id, int):
        return None
    with engine.connect() as conn:
        if prive:
            if not infos.get("conversation_avec"):
                return None
            ligne = conn.execute(
                text("""
                    SELECT expediteur AS pseudo, texte FROM messages_prives WHERE id = :id
                    AND ((expediteur = :moi AND destinataire = :autre)
                      OR (expediteur = :autre AND destinataire = :moi))
                """),
                {"id": message_id, "moi": infos["username"], "autre": infos["conversation_avec"]},
            ).fetchone()
        else:
            if not infos.get("salon"):
                return None
            ligne = conn.execute(
                text("SELECT pseudo, texte FROM messages WHERE id = :id AND salon = :salon"),
                {"id": message_id, "salon": infos["salon"]},
            ).fetchone()
    if ligne is None:
        return None
    return {"pseudo": ligne.pseudo, "texte": ligne.texte[:APERCU_MAX]}

@socketio.on("reagir")
def gerer_reaction(data):
    infos = utilisateurs_connectes.get(request.sid)
    if not infos:
        return
    emoji = (data or {}).get("emoji")
    message_id = (data or {}).get("message_id")
    prive = bool((data or {}).get("prive"))
    if emoji not in EMOJIS:
        return
    if _apercu_si_visible(infos, message_id, prive) is None:
        return

    parametres = {"id": message_id, "prive": prive, "pseudo": infos["username"], "emoji": emoji}
    with engine.connect() as conn:
        # Un clic bascule : si la reaction existe deja, on l'enleve.
        supprimees = conn.execute(
            text("""
                DELETE FROM reactions
                WHERE message_id = :id AND prive = :prive AND pseudo = :pseudo AND emoji = :emoji
            """),
            parametres,
        ).rowcount
        if not supprimees:
            conn.execute(
                text("""
                    INSERT INTO reactions (message_id, prive, pseudo, emoji)
                    VALUES (:id, :prive, :pseudo, :emoji)
                """),
                parametres,
            )
        conn.commit()

    emit(
        "reactions_maj",
        {
            "message_id": message_id,
            "prive": prive,
            "reactions": _reactions_pour([message_id], prive).get(message_id, []),
        },
        to=_salle_de_frappe(infos, prive),  # meme regle que pour la frappe
    )

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5050)
