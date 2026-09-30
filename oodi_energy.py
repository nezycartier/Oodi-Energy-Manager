# Module de gestion de la base de données SQLite OODI
# Sécurisé avec des requêtes paramétrées (Evite l'injection SQL)
#=========================================================
import sqlite3
import os

DB_NAME = "oodi_energy.db"

def _get_connection():
    return sqlite3.connect(DB_NAME)

def createAllTables():
    conn = _get_connection()
    cur = conn.cursor()
    # produits
    cur.execute('''
            CREATE TABLE IF NOT EXISTS produits
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT UNIQUE NOT NULL,
                etapes TEXT NOT NULL,
                budget_max REAL
            )
            ''')
    # Migration : ajouter budget_max si colonne absente (BDD existante)
    try:
        cur.execute("ALTER TABLE produits ADD COLUMN budget_max REAL")
    except: pass
    # machines
    cur.execute('''
            CREATE TABLE IF NOT EXISTS machines
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT UNIQUE NOT NULL,
                puissance REAL,
                email TEXT
            )
            ''')
    # users (pour l'authentification)
    cur.execute('''
            CREATE TABLE IF NOT EXISTS users
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
            ''')
    # prix_energie (Garde en mémoire le prix de l'électricité au jour le jour pour répondre aux critères du prof)
    cur.execute('''
            CREATE TABLE IF NOT EXISTS prix_energie
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_jour TEXT NOT NULL,
                heure TEXT NOT NULL,
                prix_mwh REAL NOT NULL,
                UNIQUE(date_jour, heure)
            )
            ''')
    # commandes (persistance du tableau de commandes entre sessions)
    cur.execute('''
            CREATE TABLE IF NOT EXISTS commandes
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produit TEXT NOT NULL,
                heure_debut TEXT NOT NULL,
                heure_fin TEXT,
                quantite INTEGER NOT NULL,
                cout_unitaire REAL,
                cout_total REAL,
                optimise INTEGER DEFAULT 0
            )
            ''')
    conn.commit()
    conn.close()

# INSERT INTO produits
def insert_produits(nom, etapes, budget_max=None):
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO produits (nom, etapes, budget_max) VALUES (?, ?, ?)", (nom, etapes, budget_max))
        conn.commit()
    finally:
        conn.close()

# INSERT INTO machines
def insert_machines(nom, puissance, email):
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO machines (nom, puissance, email) VALUES (?, ?, ?)", (nom, puissance, email))
        conn.commit()
    finally:
        conn.close()

# SELECT fields FROM produits
def select_produits(WHERE_clause=""):
    conn = _get_connection()
    cur = conn.cursor()
    query = "SELECT id, nom, etapes, budget_max FROM produits"
    if WHERE_clause.strip():
        query += f" WHERE {WHERE_clause}"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    return rows

# SELECT produits par nom (requête paramétrée, sécurisée contre les apostrophes)
def select_produits_par_nom(nom):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nom, etapes, budget_max FROM produits WHERE nom = ?", (nom,))
    rows = cur.fetchall()
    conn.close()
    return rows

# SELECT fields FROM machines
def select_machines(WHERE_clause=""):
    conn = _get_connection()
    cur = conn.cursor()
    query = "SELECT id, nom, puissance, email FROM machines"
    if WHERE_clause.strip():
        query += f" WHERE {WHERE_clause}"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    return rows

# UPDATE produits
def update_produits(id_val, nom, etapes, budget_max=None, WHERE_clause=""):
    conn = _get_connection()
    cur = conn.cursor()
    if not WHERE_clause.strip():
        WHERE_clause = f"id = {int(id_val)}"
    query = "UPDATE produits SET nom = ?, etapes = ?, budget_max = ? WHERE " + WHERE_clause
    cur.execute(query, (nom, etapes, budget_max))
    conn.commit()
    conn.close()

# UPDATE machines
def update_machines(id_val, nom, puissance, email, WHERE_clause=""):
    conn = _get_connection()
    cur = conn.cursor()
    if not WHERE_clause.strip():
        WHERE_clause = f"id = {int(id_val)}"
    query = "UPDATE machines SET nom = ?, puissance = ?, email = ? WHERE " + WHERE_clause
    cur.execute(query, (nom, puissance, email))
    conn.commit()
    conn.close()


# DELETE produits par nom (requête paramétrée, sécurisée contre les apostrophes)
def delete_produits_par_nom(nom):
    if not nom: return
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM produits WHERE nom = ?", (nom,))
    conn.commit()
    conn.close()


# DELETE machines par nom (requête paramétrée, sécurisée contre les apostrophes)
def delete_machines_par_nom(nom):
    if not nom: return
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM machines WHERE nom = ?", (nom,))
    conn.commit()
    conn.close()

# =================================================================
# GESTION DES COMMANDES (Persistance entre sessions)
# =================================================================
def insert_commande(produit, heure_debut, heure_fin, quantite, cout_unitaire, cout_total, optimise=False):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO commandes (produit, heure_debut, heure_fin, quantite, cout_unitaire, cout_total, optimise) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (produit, heure_debut, heure_fin, quantite, cout_unitaire, cout_total, 1 if optimise else 0)
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id

def select_commandes():
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, produit, heure_debut, heure_fin, quantite, cout_unitaire, cout_total, optimise FROM commandes ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_commande(row_id):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM commandes WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()


# =================================================================
# GESTION DU SEUIL (Persistance dans config.json)
# =================================================================
def save_threshold(thres):
    import json
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except:
        cfg = {}
    cfg["price_alert_threshold"] = thres
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

# =================================================================
# GESTION DES PRIX DE L'ÉNERGIE (Remplacement de la RAM globale)
# =================================================================
def save_hourly_prices(date_jour, df):
    """Sauvegarde le DataFrame des prix d'une journée précise dans SQLite"""
    if df.empty: return
    conn = _get_connection()
    cur = conn.cursor()
    # On insère les 24 heures
    for _, row in df.iterrows():
        # row['Heure'] est un datetime, on le stocke en format chaîne HH:MM ou datetime complet
        heure_str = str(row['Heure'])
        prix = float(row['Prix_EUR_MWh'])
        cur.execute("INSERT OR REPLACE INTO prix_energie (date_jour, heure, prix_mwh) VALUES (?, ?, ?)", 
                    (date_jour, heure_str, prix))
    conn.commit()
    conn.close()

def get_hourly_prices(date_jour):
    """Charge le DataFrame d'une journée à partir de la base SQLite"""
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT heure, prix_mwh FROM prix_energie WHERE date_jour = ? ORDER BY heure ASC", (date_jour,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return None
    import pandas as pd
    # Reconstruction du DataFrame identique à la sortie de l'API
    df = pd.DataFrame(rows, columns=['Heure', 'Prix_EUR_MWh'])
    df['Heure'] = pd.to_datetime(df['Heure'])
    return df

# =================================================================
# FONCTIONS D'AUTHENTIFICATION (Sécurisées)
# =================================================================

def user_exists(email):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return row is not None

def check_login(email, password):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email FROM users WHERE email = ? AND password = ?", (email, password))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1], "email": row[2]}
    return None

def create_user(name, email, password):
    conn = _get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (name, email, password))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_all_users():
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, email FROM users")
    rows = cur.fetchall()
    conn.close()
    return [{"name": r[0], "email": r[1]} for r in rows]
