from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from flask_wtf.csrf import CSRFProtect
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired
from flask_bcrypt import Bcrypt
from functools import wraps
import mysql.connector
import os
from werkzeug.utils import secure_filename
import time 
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# --- INITIALISATION DE BCRYPT (C'est ça qui manquait !) ---
bcrypt = Bcrypt(app)
csrf = CSRFProtect(app)
talisman = Talisman(app, content_security_policy=None, force_https=True)

# --- INITIALISATION DES OUTILS DE SÉCURITÉ ---
csrf = CSRFProtect(app)

# NOUVEAU : Le videur anti-brute-force !
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"] # Limites générales pour tout le site
)

# --- CONFIGURATION UPLOAD ---
UPLOAD_FOLDER = 'static/uploads/cours'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- SECURITE ---
secret = os.getenv('SECRET_KEY')
if not secret:
    raise RuntimeError("SECRET_KEY non définie ! Arrêt du serveur.")
app.config['SECRET_KEY'] = secret

# --- SÉCURITÉ DES COOKIES ---
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True

def get_db():
    db_host = os.getenv('DB_HOST', 'db')
    db_user = os.getenv('DB_USER', 'pronote_user') 
    db_pass = os.getenv('DB_PASSWORD', 'userpassword')
    db_name = os.getenv('DB_NAME', 'ecole_secu')

    for i in range(10): 
        try:
            conn = mysql.connector.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                connect_timeout=5 
            )
            if conn.is_connected():
                return conn
        except mysql.connector.Error as err:
            print(f"Base de données non prête (Tentative {i+1}/10). Erreur : {err}")
            time.sleep(3) 

    raise RuntimeError("Erreur critique : Impossible de joindre la base de données après 10 tentatives.")
# --- PROTECTIONS (RBAC) ---
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

class LoginForm(FlaskForm):
    username = StringField('Identifiant', validators=[DataRequired()])
    password = PasswordField('Mot de passe', validators=[DataRequired()])
    submit = SubmitField('Se connecter')

# --- GESTION DES ERREURS GLOBALES ---

@app.errorhandler(AttributeError)
def handle_db_error(e):
    if "'NoneType' object has no attribute 'cursor'" in str(e):
        return render_template('errors/db_down.html'), 530 
    return "Une erreur système est survenue.", 500

@app.errorhandler(RuntimeError)
def handle_runtime_error(e):
    if "Impossible de joindre la base de données" in str(e):
        return render_template('errors/db_down.html'), 530
    return "Erreur interne du serveur.", 500

# --- ROUTES ---

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('commun/index.html')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    form = LoginForm()
    if form.validate_on_submit():
        conn = get_db()
        if not conn:
            flash("Erreur de connexion à la base de données. Réessayez dans un instant.", "danger")
            return render_template('authentification/connexion.html', form=form)
        
        cursor = conn.cursor(dictionary=True)
        # On récupère l'user et son nom de rôle via une jointure
        cursor.execute("""
            SELECT u.*, r.nom as role_nom 
            FROM utilisateurs u 
            JOIN roles r ON u.role_id = r.id 
            WHERE u.username = %s
        """, (form.username.data,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        # Correction ici : on récupère le mot de passe du formulaire (form.password.data)
        if user and bcrypt.check_password_hash(user['password_hash'], form.password.data):
            session['user_id'] = user['id']
            session['user'] = user['username']
            session['role'] = user['role_nom']
            session['classe_id'] = user['classe_id']
            
            # Redirection intelligente selon le rôle
            if user['role_nom'] == 'Professeur':
                return redirect(url_for('prof_dashboard'))
            elif user['role_nom'] == 'Etudiant':
                return redirect(url_for('student_dashboard')) # ou ta route étudiant
            elif user['role_nom'] == 'Administrateur':
                return redirect(url_for('admin_dashboard'))
            
            return redirect(url_for('index'))
        
        flash('Identifiant ou mot de passe incorrect.', 'danger')
    return render_template('authentification/connexion.html', form=form)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- EMPLOI DU TEMPS ---
@app.route('/emploi-du-temps')
def schedule():
    if 'user_id' not in session:
        flash("Veuillez vous connecter pour voir l'emploi du temps.", "danger")
        return redirect(url_for('login')) # Adapte 'login' selon le nom de ta
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    devoirs = []
    cours = [] 
    
    if session.get('role') == 'Professeur':
        # 1. On cherche d'abord les cours
        cursor.execute("""
            SELECT e.jour, e.heure, e.matiere, e.salle, c.nom as public_cible, e.classe_id 
            FROM emploi_du_temps e 
            LEFT JOIN classes c ON e.classe_id = c.id 
            WHERE e.prof_id = %s 
            ORDER BY FIELD(e.jour, 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'), e.heure
        """, (session['user_id'],))
        cours = cursor.fetchall() # <--- LA LIGNE MAGIQUE QUI MANQUAIT !
        
        # 2. Ensuite on cherche les devoirs
        cursor.execute("SELECT * FROM devoirs WHERE prof_id = %s", (session['user_id'],))
        devoirs = cursor.fetchall()
        
    else:
        # 1. Pareil pour les élèves : on cherche d'abord les cours
        cursor.execute("""
            SELECT e.jour, e.heure, e.matiere, e.salle, u.username as public_cible 
            FROM emploi_du_temps e 
            LEFT JOIN utilisateurs u ON e.prof_id = u.id 
            WHERE e.classe_id = %s
            ORDER BY FIELD(e.jour, 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'), e.heure
        """, (session['classe_id'],))
        cours = cursor.fetchall() # <--- LA LIGNE MAGIQUE QUI MANQUAIT !
        
        # 2. Ensuite on cherche les devoirs de la classe
        cursor.execute("SELECT * FROM devoirs WHERE classe_id = %s", (session['classe_id'],))
        devoirs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # On envoie les deux listes remplies proprement au HTML
    return render_template('commun/emploi_du_temps.html', cours=cours, devoirs=devoirs)

@app.route('/professeur/ajouter-devoir', methods=['POST'])
@role_required('Professeur')
def ajouter_devoir():
    jour = request.form.get('jour')
    heure = request.form.get('heure')
    classe_id = request.form.get('classe_id')
    contenu = request.form.get('contenu')
    
    # Génération de la date au format français
    tz_france = ZoneInfo("Europe/Paris")
    date_creation = datetime.now(tz_france).strftime("%d/%m/%Y à %Hh%M")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO devoirs (prof_id, classe_id, jour, heure, contenu, date_creation) 
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], classe_id, jour, heure, contenu, date_creation))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Le devoir a bien été ajouté !", "success")
    return redirect(url_for('schedule'))

# ROUTE POUR MODIFIER UN DEVOIR (Prof)
@app.route('/professeur/modifier-devoir', methods=['POST'])
@role_required('Professeur')
def modifier_devoir():
    devoir_id = request.form.get('devoir_id')
    nouveau_contenu = request.form.get('contenu')
    
    # Génération de la date de modification au format français
    tz_france = ZoneInfo("Europe/Paris")
    date_modif = datetime.now(tz_france).strftime("%d/%m/%Y à %Hh%M")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE devoirs 
        SET contenu = %s, date_modification = %s 
        WHERE id = %s AND prof_id = %s
    """, (nouveau_contenu, date_modif, devoir_id, session['user_id']))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Le devoir a été modifié avec succès.", "success")
    return redirect(url_for('schedule'))

# --- MESSAGERIE ---
@app.route('/messagerie', methods=['GET', 'POST'])
@app.route('/messagerie/<int:contact_id>', methods=['GET', 'POST'])
@role_required('Professeur', 'Administrateur', 'Etudiant')
def messagerie(contact_id=None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Envoi de message
    if request.method == 'POST':
        dest_id = request.form.get('destinataire_id')
        msg = request.form.get('message')
        if msg and dest_id:
            cursor.execute("INSERT INTO messages (expediteur_id, destinataire_id, contenu) VALUES (%s, %s, %s)", 
                           (session['user_id'], dest_id, msg))
            conn.commit()
            return redirect(url_for('messagerie', contact_id=dest_id))

    # Liste des contacts avec le comptage des messages NON LUS (Correction : m.lu = 0)
    query_contacts = """
        SELECT u.id, u.username, u.role_id, MAX(m.date_envoi) as last_message_date,
               SUM(CASE WHEN m.destinataire_id = %s AND m.expediteur_id = u.id AND m.lu = 0 THEN 1 ELSE 0 END) as non_lus
        FROM utilisateurs u
        LEFT JOIN messages m 
            ON (m.expediteur_id = u.id AND m.destinataire_id = %s)
            OR (m.expediteur_id = %s AND m.destinataire_id = u.id)
        WHERE u.id != %s
        GROUP BY u.id, u.username, u.role_id
        ORDER BY last_message_date DESC, u.username ASC
    """
    cursor.execute(query_contacts, (session['user_id'], session['user_id'], session['user_id'], session['user_id']))
    contacts = cursor.fetchall()

    conversation = []
    selected_contact = None
    if contact_id:
        # On marque les messages comme LUS quand on clique sur le contact (Correction : lu = 1)
        cursor.execute("UPDATE messages SET lu = 1 WHERE expediteur_id = %s AND destinataire_id = %s", (contact_id, session['user_id']))
        conn.commit()

        # Détails du contact sélectionné
        cursor.execute("SELECT username FROM utilisateurs WHERE id = %s", (contact_id,))
        selected_contact = cursor.fetchone()
        
        # Historique des échanges
        query = """
            SELECT m.*, u.username as exp_name 
            FROM messages m 
            JOIN utilisateurs u ON m.expediteur_id = u.id 
            WHERE (expediteur_id = %s AND destinataire_id = %s) 
               OR (expediteur_id = %s AND destinataire_id = %s)
            ORDER BY date_envoi ASC
        """
        cursor.execute(query, (session['user_id'], contact_id, contact_id, session['user_id']))
        conversation = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('commun/messagerie.html', contacts=contacts, conversation=conversation, selected_contact=selected_contact, contact_id=contact_id)

# --- DASHBOARD ÉTUDIANT ---
@app.route('/etudiant/dashboard')
@role_required('Etudiant') # Attention : "Etudiant" sans accent pour correspondre à la base de données
def student_dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # 1. GESTION DES NOTES ET MOYENNE
    cursor.execute("SELECT matiere, valeur FROM notes WHERE etudiant_id = %s", (session['user_id'],))
    notes = cursor.fetchall()
    
    if notes:
        total_notes = sum(float(note['valeur']) for note in notes)
        moyenne = round(total_notes / len(notes), 2)
    else:
        moyenne = "N/A"

    # 2. GESTION DE L'EMPLOI DU TEMPS
    emploi_du_temps = []
    classe_id = session.get('classe_id') # Récupéré automatiquement à la connexion
    
    if classe_id:
        cursor.execute("""
            SELECT e.jour, e.heure, e.matiere, e.salle, u.username as public_cible 
            FROM emploi_du_temps e 
            LEFT JOIN utilisateurs u ON e.prof_id = u.id 
            WHERE e.classe_id = %s
            ORDER BY FIELD(e.jour, 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'), e.heure
        """, (classe_id,))
        emploi_du_temps = cursor.fetchall()

    cursor.close()
    conn.close()
    
    # On envoie tout (notes, moyenne, emploi du temps) au fichier HTML
    return render_template('etudiant/accueil_etudiant.html', notes=notes, moyenne=moyenne, emploi_du_temps=emploi_du_temps)
# --- DASHBOARD PROFESSEUR ---
@app.route('/professeur')
@role_required('Professeur')
def prof_dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        cursor.execute("INSERT INTO notes (valeur, matiere, etudiant_id) VALUES (%s, %s, %s)", 
                       (request.form.get('note'), request.form.get('matiere'), request.form.get('etudiant_id')))
        conn.commit()
    
    cursor.execute("SELECT id, username FROM utilisateurs WHERE role_id = 3")
    eleves = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('professeur/accueil_prof.html', eleves=eleves)

# --- DASHBOARD ADMINISTRATEUR ---
@app.route('/admin/dashboard')
@role_required('Administrateur')
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Compter les élèves (role_id = 3)
    cursor.execute("SELECT COUNT(*) as total FROM utilisateurs WHERE role_id = 3")
    nb_eleves = cursor.fetchone()['total']

    # Compter les professeurs (role_id = 2)
    cursor.execute("SELECT COUNT(*) as total FROM utilisateurs WHERE role_id = 2")
    nb_profs = cursor.fetchone()['total']

    # Récupérer la liste des utilisateurs avec leur rôle
    cursor.execute("""
        SELECT u.id, u.username, r.nom as role_nom 
        FROM utilisateurs u 
        JOIN roles r ON u.role_id = r.id 
        ORDER BY r.nom, u.username
    """)
    utilisateurs = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('administrateur/accueil_admin.html', 
                           nb_eleves=nb_eleves, 
                           nb_profs=nb_profs, 
                           utilisateurs=utilisateurs)

# --- ESPACE ADMINISTRATEUR (Gestion des cours) ---

@app.route('/admin/gestion-cours')
@role_required('Administrateur')
def admin_gestion_cours():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # On récupère TOUS les documents, avec le nom du prof et de la classe
    cursor.execute("""
        SELECT d.id, d.nom_affichage, d.nom_fichier, d.date_depot, 
               c.nom as classe_nom, u.username as prof_nom
        FROM documents d
        JOIN classes c ON d.classe_id = c.id
        JOIN utilisateurs u ON d.prof_id = u.id
        ORDER BY d.date_depot DESC
    """)
    documents = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('administrateur/gestion_cours.html', documents=documents)

@app.route('/admin/supprimer-cours/<int:doc_id>', methods=['POST'])
@role_required('Administrateur')
def admin_delete_pdf(doc_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # L'admin peut supprimer n'importe quel fichier, on a juste besoin du nom_fichier
    cursor.execute("SELECT nom_fichier FROM documents WHERE id = %s", (doc_id,))
    doc = cursor.fetchone()
    
    if doc:
        # Suppression du fichier physique
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], doc['nom_fichier'])
        if os.path.exists(filepath):
            os.remove(filepath)
        
        # Suppression dans la base
        cursor.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        conn.commit()
        flash("Le cours a été supprimé par l'administrateur.", "success")
    else:
        flash("Erreur : Document introuvable.", "danger")
        
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_gestion_cours'))

# --- DOSSIER ÉLÈVE ---
@app.route('/eleve/<int:eleve_id>')
@role_required('Professeur', 'Administrateur')
def view_student_folder(eleve_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # Infos élève
    cursor.execute("SELECT u.username, c.nom as classe_nom FROM utilisateurs u LEFT JOIN classes c ON u.classe_id = c.id WHERE u.id = %s", (eleve_id,))
    eleve = cursor.fetchone()
    if not eleve: abort(404)
    
    # Ses notes
    cursor.execute("SELECT matiere, valeur FROM notes WHERE etudiant_id = %s", (eleve_id,))
    notes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('professeur/dossier_eleve.html', eleve=eleve, notes=notes)

# --- ERREURS ---
@app.errorhandler(403)
def forbidden(e):
    return render_template('commun/403.html'), 403


# --- GÉRER UN UTILISATEUR (MODIFIER / SUPPRIMER / MDP) ---
@app.route('/admin/gerer/<int:user_id>', methods=['GET', 'POST'])
@role_required('Administrateur')
def gerer_utilisateur(user_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'modifier':
            nouveau_nom = request.form.get('username')
            nouveau_role = request.form.get('role_id')
            
            # NOUVEAU : Récupérer la classe sélectionnée
            nouvelle_classe = request.form.get('classe_id')
            if not nouvelle_classe: # Si "Aucune classe" est sélectionné
                nouvelle_classe = None
                
            # NOUVEAU : On met à jour la classe dans le UPDATE
            cursor.execute("UPDATE utilisateurs SET username = %s, role_id = %s, classe_id = %s WHERE id = %s", 
                           (nouveau_nom, nouveau_role, nouvelle_classe, user_id))
            conn.commit()
            flash(f"L'utilisateur {nouveau_nom} a été mis à jour.", "success")
        
        elif action == 'changer_mdp':
            nouveau_mdp = request.form.get('nouveau_mdp')
            if len(nouveau_mdp) < 12:
                flash("Le mot de passe doit faire au moins 12 caractères.", "danger")
            else:
                hashed_mdp = bcrypt.generate_password_hash(nouveau_mdp).decode('utf-8')
                cursor.execute("UPDATE utilisateurs SET password_hash = %s WHERE id = %s", (hashed_mdp, user_id))
                conn.commit()
                flash("Le mot de passe a été réinitialisé avec succès.", "success")
        
        elif action == 'supprimer':
            cursor.execute("DELETE FROM utilisateurs WHERE id = %s", (user_id,))
            conn.commit()
            flash("Utilisateur supprimé avec succès.", "success")
            return redirect(url_for('admin_dashboard'))

    # Récupérer les infos de l'utilisateur
    cursor.execute("SELECT * FROM utilisateurs WHERE id = %s", (user_id,))
    user_to_edit = cursor.fetchone()
    
    cursor.execute("SELECT * FROM roles")
    roles = cursor.fetchall()

    # NOUVEAU : Récupérer toutes les classes pour le menu déroulant
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()

    cursor.close()
    conn.close()
    
    # NOUVEAU : On envoie 'classes' au fichier HTML
    return render_template('administrateur/gerer_utilisateur.html', user_to_edit=user_to_edit, roles=roles, classes=classes)

# --- PAGE PROFIL (Changement de mot de passe) ---
@app.route('/profil', methods=['GET', 'POST'])
@role_required('Professeur', 'Administrateur', 'Etudiant')
def profil():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        ancien_mdp = request.form.get('ancien_mdp')
        nouveau_mdp = request.form.get('nouveau_mdp')
        confirmation_mdp = request.form.get('confirmation_mdp')

        # 2. Récupérer le mot de passe actuel
        cursor.execute("SELECT password_hash FROM utilisateurs WHERE id = %s", (session['user_id'],))
        user_data = cursor.fetchone()

        # 3. Vérifications de sécurité
        if not bcrypt.check_password_hash(user_data['password_hash'], ancien_mdp):
            flash("L'ancien mot de passe est incorrect.", "danger")
        elif nouveau_mdp != confirmation_mdp:
            flash("Les nouveaux mots de passe ne correspondent pas.", "danger")
        elif len(nouveau_mdp) < 12:
            flash("Le nouveau mot de passe doit faire au moins 12 caractères.", "danger")
        else:
            # 4. Mise à jour réussie
            nouveau_hash = bcrypt.generate_password_hash(nouveau_mdp).decode('utf-8')
            cursor.execute("UPDATE utilisateurs SET password_hash = %s WHERE id = %s", (nouveau_hash, session['user_id']))
            conn.commit()
            flash("Votre mot de passe a été mis à jour avec succès !", "success")
            return redirect(url_for('profil'))

    cursor.close()
    conn.close()
    return render_template('commun/profil.html')

# --- AJOUTER UN NOUVEL UTILISATEUR ---
@app.route('/admin/ajouter', methods=['GET', 'POST'])
@role_required('Administrateur')
def ajouter_utilisateur():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role_id = request.form.get('role_id')
        
        # NOUVEAU : On récupère la classe (si vide, on met None pour les profs/admins)
        classe_id = request.form.get('classe_id')
        if not classe_id:
            classe_id = None
        
        # 1. On vérifie si le nom d'utilisateur existe déjà
        cursor.execute("SELECT id FROM utilisateurs WHERE username = %s", (username,))
        if cursor.fetchone():
            flash("Erreur : Ce nom d'utilisateur est déjà pris.", "danger")
        elif len(password) < 12:
            flash("Erreur : Le mot de passe doit faire au moins 12 caractères.", "danger")
        else:
            # 2. On hache le mot de passe et on crée l'utilisateur avec sa classe
            hashed_mdp = bcrypt.generate_password_hash(password).decode('utf-8')
            cursor.execute(
                "INSERT INTO utilisateurs (username, password_hash, role_id, classe_id) VALUES (%s, %s, %s, %s)", 
                (username, hashed_mdp, role_id, classe_id)
            )
            conn.commit()
            flash(f"Succès : L'utilisateur {username} a été créé !", "success")
            return redirect(url_for('admin_dashboard'))

    # Récupérer la liste des rôles ET des classes pour les menus déroulants
    cursor.execute("SELECT * FROM roles")
    roles = cursor.fetchall()
    
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('administrateur/ajouter_utilisateur.html', roles=roles, classes=classes)

# --- PAGE NOTIFS ---
@app.route('/api/notifications')
def api_notifications():
    # Si l'utilisateur n'est pas connecté, on renvoie 0
    if 'user_id' not in session:
        return jsonify({'unread_count': 0})
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM messages WHERE destinataire_id = %s AND lu = 0", (session['user_id'],))
    count = cursor.fetchone()['total']
    cursor.close()
    conn.close()
    return jsonify({'unread_count': count})

# --- GESTION DES COURS (PDF) ---

# 1. Page de l'onglet Prof (Formulaire de dépôt + Liste de ses cours)
@app.route('/professeur/depot-cours')
@role_required('Professeur')
def page_depot_cours():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # On récupère tous les cours déposés par CE professeur, avec le nom de la classe
    cursor.execute("""
        SELECT d.id, d.nom_affichage, d.nom_fichier, d.date_depot, c.nom as classe_nom 
        FROM documents d
        JOIN classes c ON d.classe_id = c.id
        WHERE d.prof_id = %s
        ORDER BY d.date_depot DESC
    """, (session['user_id'],))
    documents = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # On envoie la liste des documents au template HTML
    return render_template('professeur/deposer_cours.html', documents=documents)

# NOUVELLE ROUTE : Pour supprimer un cours
@app.route('/prof/supprimer-cours/<int:doc_id>', methods=['POST'])
@role_required('Professeur')
def delete_pdf(doc_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Vérifier que le document existe et appartient bien à ce professeur (Sécurité !)
    cursor.execute("SELECT nom_fichier FROM documents WHERE id = %s AND prof_id = %s", (doc_id, session['user_id']))
    doc = cursor.fetchone()
    
    if doc:
        # 2. Supprimer le fichier physique du dossier uploads
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], doc['nom_fichier'])
        if os.path.exists(filepath):
            os.remove(filepath)
        
        # 3. Supprimer la ligne dans la base de données
        cursor.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        conn.commit()
        flash("Le cours a été supprimé avec succès.", "success")
    else:
        flash("Erreur : Document introuvable ou vous n'avez pas les droits.", "danger")
        
    cursor.close()
    conn.close()
    
    return redirect(url_for('page_depot_cours'))

# 2. Action d'upload (Le prof envoie le fichier)
@app.route('/prof/upload-pdf', methods=['POST'])
@role_required('Professeur')
def upload_pdf():
    if 'file' not in request.files:
        flash("Aucun fichier sélectionné", "danger")
        return redirect(url_for('page_depot_cours'))
    
    file = request.files['file']
    classe_id = request.form.get('classe_id')
    nom_cours = request.form.get('nom_cours')

    if file and allowed_file(file.filename):
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 1 FROM emploi_du_temps 
            WHERE prof_id = %s AND classe_id = %s LIMIT 1
        """, (session['user_id'], classe_id))
        
        if not cursor.fetchone():
            flash("Alerte de sécurité : Vous n'êtes pas autorisé à déposer un cours pour cette classe.", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for('page_depot_cours'))
 
        filename = secure_filename(file.filename)
        # On utilise time.time() pour avoir un nom vraiment unique
        unique_filename = f"{session['user_id']}_{int(time.time())}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        
        cursor.execute("""
            INSERT INTO documents (nom_affichage, nom_fichier, classe_id, prof_id) 
            VALUES (%s, %s, %s, %s)
        """, (nom_cours, unique_filename, classe_id, session['user_id']))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash("Le cours PDF a été mis en ligne !", "success")
    
    return redirect(url_for('page_depot_cours'))

# 3. Page pour l'élève (Liste des cours de sa classe)
@app.route('/etudiant/mes-cours')
@role_required('Etudiant')
def mes_cours():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    # On récupère les documents destinés à la classe de l'élève connecté via sa session
    cursor.execute("""
        SELECT d.*, u.username as prof_nom 
        FROM documents d
        JOIN utilisateurs u ON d.prof_id = u.id
        WHERE d.classe_id = %s
        ORDER BY d.date_depot DESC
    """, (session.get('classe_id'),))
    documents = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('etudiant/liste_cours.html', documents=documents)

if __name__ == '__main__':
    app.run(
        host='0.0.0.0', # nosec B104
        port=5000, 
        debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
        ssl_context='adhoc'
    )