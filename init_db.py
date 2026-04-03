import mysql.connector
from flask_bcrypt import Bcrypt
from flask import Flask
import os
import time
import secrets  # Ajouté pour générer des mots de passe sécurisés par défaut

app = Flask(__name__)
bcrypt = Bcrypt(app)

DB_HOST = os.getenv('DB_HOST', 'db')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = os.getenv('DB_PASSWORD', 'rootpassword')
DB_NAME = os.getenv('DB_NAME', 'ecole_secu')

def init_db():
    conn = None
    for i in range(10):
        try:
            conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS)
            if conn.is_connected(): break
        except:
            time.sleep(3)
    
    if not conn: return

    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
    cursor.execute(f"USE {DB_NAME}")

    # Nettoyage (Ajout de 'devoirs' et 'documents' dans la liste)
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    for t in ['devoirs', 'documents', 'messages', 'emploi_du_temps', 'notes', 'utilisateurs', 'roles', 'classes']:
        cursor.execute(f"DROP TABLE IF EXISTS {t}")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

    # Création des tables
    cursor.execute("CREATE TABLE roles (id INT PRIMARY KEY, nom VARCHAR(50))")
    cursor.execute("CREATE TABLE classes (id INT AUTO_INCREMENT PRIMARY KEY, nom VARCHAR(50))")
    
    cursor.execute("""
        CREATE TABLE utilisateurs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE,
            password_hash VARCHAR(255),
            role_id INT,
            classe_id INT NULL,
            FOREIGN KEY (role_id) REFERENCES roles(id),
            FOREIGN KEY (classe_id) REFERENCES classes(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE emploi_du_temps (
            id INT AUTO_INCREMENT PRIMARY KEY,
            jour VARCHAR(20),
            heure VARCHAR(20),
            matiere VARCHAR(50),
            salle VARCHAR(20),
            prof_id INT,
            classe_id INT,
            FOREIGN KEY (prof_id) REFERENCES utilisateurs(id),
            FOREIGN KEY (classe_id) REFERENCES classes(id)
        )
    """)

    # Ajout de la colonne "lu" pour les notifications dynamiques
    cursor.execute("""
        CREATE TABLE messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            expediteur_id INT,
            destinataire_id INT,
            contenu TEXT,
            lu BOOLEAN DEFAULT FALSE,
            date_envoi DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (expediteur_id) REFERENCES utilisateurs(id),
            FOREIGN KEY (destinataire_id) REFERENCES utilisateurs(id)
        )
    """)

    # Création de la table pour les documents PDF
    cursor.execute("""
        CREATE TABLE documents (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nom_affichage VARCHAR(255) NOT NULL,
            nom_fichier VARCHAR(255) NOT NULL,
            classe_id INT,
            prof_id INT,
            date_depot TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (classe_id) REFERENCES classes(id),
            FOREIGN KEY (prof_id) REFERENCES utilisateurs(id)
        )
    """)

    # --- TABLE : DEVOIRS ---
    cursor.execute("""
        CREATE TABLE devoirs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            prof_id INT,
            classe_id INT,
            jour VARCHAR(20),
            heure VARCHAR(50),
            contenu TEXT,
            date_creation VARCHAR(50),
            date_modification VARCHAR(50) DEFAULT NULL,
            FOREIGN KEY (prof_id) REFERENCES utilisateurs(id),
            FOREIGN KEY (classe_id) REFERENCES classes(id)
        )
    """)

    cursor.execute("CREATE TABLE notes (id INT AUTO_INCREMENT PRIMARY KEY, valeur DECIMAL(4,2), matiere VARCHAR(50), etudiant_id INT, FOREIGN KEY (etudiant_id) REFERENCES utilisateurs(id))")

    # --- INSERTION DES DONNEES DE BASE ---
    cursor.execute("INSERT INTO roles VALUES (1, 'Administrateur'), (2, 'Professeur'), (3, 'Etudiant')")
    cursor.execute("INSERT INTO classes (nom) VALUES ('GCS2-A'), ('GCS2-B'), ('GCS2-C')")
    
    # Récupération des mots de passe depuis l'environnement ou génération aléatoire sécurisée
    admin_pw = os.getenv('SEED_ADMIN_PASSWORD', secrets.token_urlsafe(12))
    prof_pw = os.getenv('SEED_PROF_PASSWORD', secrets.token_urlsafe(12))
    eleve_pw = os.getenv('SEED_ELEVE_PASSWORD', secrets.token_urlsafe(12))
    
    print("\n================================================")
    print("🔐 MOTS DE PASSE D'INITIALISATION GÉNÉRÉS/RÉCUPÉRÉS")
    print(f"Admin  (admin)       : {admin_pw}")
    print(f"Profs  (prof_*)      : {prof_pw}")
    print(f"Élèves (eleve_*)     : {eleve_pw}")
    print("================================================\n")

    pw_admin = bcrypt.generate_password_hash(admin_pw).decode('utf-8')
    pw_prof = bcrypt.generate_password_hash(prof_pw).decode('utf-8')
    pw_eleve = bcrypt.generate_password_hash(eleve_pw).decode('utf-8')
    
    # 1. Administrateur
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id) VALUES ('admin', %s, 1)", (pw_admin,))
    
    # 2. Professeurs (ID 2: Maths, ID 3: Info, ID 4: Cyber)
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id) VALUES ('prof_maths', %s, 2)", (pw_prof,))
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id) VALUES ('prof_info', %s, 2)", (pw_prof,))
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id) VALUES ('prof_cyber', %s, 2)", (pw_prof,))
    
    # 3. Etudiants
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id, classe_id) VALUES ('eleve_a', %s, 3, 1)", (pw_eleve,))
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id, classe_id) VALUES ('eleve_b', %s, 3, 2)", (pw_eleve,))
    cursor.execute("INSERT INTO utilisateurs (username, password_hash, role_id, classe_id) VALUES ('eleve_c', %s, 3, 3)", (pw_eleve,))

    # --- EMPLOI DU TEMPS HEBDOMADAIRE PROPRE ---
    planning = [
        # --- LUNDI ---
        ('Lundi', '08h00 - 10h00', 'Mathématiques', '101', 2, 1),
        ('Lundi', '08h00 - 10h00', 'Développement', 'S.Info', 3, 2),
        ('Lundi', '08h00 - 10h00', 'Cybersécurité', 'Labo', 4, 3),
        ('Lundi', '10h00 - 12h00', 'Cybersécurité', 'Labo', 4, 1),
        ('Lundi', '10h00 - 12h00', 'Mathématiques', '101', 2, 2),
        ('Lundi', '10h00 - 12h00', 'Développement', 'S.Info', 3, 3),
        ('Lundi', '14h00 - 16h00', 'Développement', 'S.Info', 3, 1),
        ('Lundi', '14h00 - 16h00', 'Cybersécurité', 'Labo', 4, 2),
        ('Lundi', '14h00 - 16h00', 'Mathématiques', '101', 2, 3),

        # --- MARDI ---
        ('Mardi', '08h00 - 10h00', 'Développement', 'S.Info', 3, 1),
        ('Mardi', '08h00 - 10h00', 'Cybersécurité', 'Labo', 4, 2),
        ('Mardi', '08h00 - 10h00', 'Mathématiques', '101', 2, 3),
        ('Mardi', '10h00 - 12h00', 'Mathématiques', '101', 2, 1),
        ('Mardi', '10h00 - 12h00', 'Développement', 'S.Info', 3, 2),
        ('Mardi', '10h00 - 12h00', 'Cybersécurité', 'Labo', 4, 3),
        ('Mardi', '14h00 - 16h00', 'Cybersécurité', 'Labo', 4, 1),
        ('Mardi', '14h00 - 16h00', 'Mathématiques', '101', 2, 2),
        ('Mardi', '14h00 - 16h00', 'Développement', 'S.Info', 3, 3),

        # --- MERCREDI ---
        ('Mercredi', '08h00 - 10h00', 'Cybersécurité', 'Labo', 4, 1),
        ('Mercredi', '08h00 - 10h00', 'Mathématiques', '101', 2, 2),
        ('Mercredi', '08h00 - 10h00', 'Développement', 'S.Info', 3, 3),
        ('Mercredi', '10h00 - 12h00', 'Développement', 'S.Info', 3, 1),
        ('Mercredi', '10h00 - 12h00', 'Cybersécurité', 'Labo', 4, 2),
        ('Mercredi', '10h00 - 12h00', 'Mathématiques', '101', 2, 3),
        ('Mercredi', '14h00 - 16h00', 'Mathématiques', '101', 2, 1),
        ('Mercredi', '14h00 - 16h00', 'Développement', 'S.Info', 3, 2),
        ('Mercredi', '14h00 - 16h00', 'Cybersécurité', 'Labo', 4, 3),

        # --- JEUDI ---
        ('Jeudi', '08h00 - 10h00', 'Mathématiques', '101', 2, 1),
        ('Jeudi', '08h00 - 10h00', 'Développement', 'S.Info', 3, 2),
        ('Jeudi', '08h00 - 10h00', 'Cybersécurité', 'Labo', 4, 3),
        ('Jeudi', '10h00 - 12h00', 'Cybersécurité', 'Labo', 4, 1),
        ('Jeudi', '10h00 - 12h00', 'Mathématiques', '101', 2, 2),
        ('Jeudi', '10h00 - 12h00', 'Développement', 'S.Info', 3, 3),
        ('Jeudi', '14h00 - 16h00', 'Développement', 'S.Info', 3, 1),
        ('Jeudi', '14h00 - 16h00', 'Cybersécurité', 'Labo', 4, 2),
        ('Jeudi', '14h00 - 16h00', 'Mathématiques', '101', 2, 3),

        # --- VENDREDI ---
        ('Vendredi', '08h00 - 10h00', 'Développement', 'S.Info', 3, 1),
        ('Vendredi', '08h00 - 10h00', 'Cybersécurité', 'Labo', 4, 2),
        ('Vendredi', '08h00 - 10h00', 'Mathématiques', '101', 2, 3),
        ('Vendredi', '10h00 - 12h00', 'Mathématiques', '101', 2, 1),
        ('Vendredi', '10h00 - 12h00', 'Développement', 'S.Info', 3, 2),
        ('Vendredi', '10h00 - 12h00', 'Cybersécurité', 'Labo', 4, 3),
        ('Vendredi', '14h00 - 16h00', 'Cybersécurité', 'Labo', 4, 1),
        ('Vendredi', '14h00 - 16h00', 'Mathématiques', '101', 2, 2),
        ('Vendredi', '14h00 - 16h00', 'Développement', 'S.Info', 3, 3)
    ]

    for p in planning:
        cursor.execute("INSERT INTO emploi_du_temps (jour, heure, matiere, salle, prof_id, classe_id) VALUES (%s, %s, %s, %s, %s, %s)", p)

    conn.commit()
    cursor.close()
    conn.close()
    print("Pronote Hebdomadaire initialise avec succes.")

if __name__ == '__main__':
    init_db()