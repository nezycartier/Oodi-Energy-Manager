# OODI Energy Manager

Application de gestion et d'optimisation énergétique pour le bâtiment OODI (Helsinki).  
Développée dans le cadre du cours de **Systèmes d'Information** (remise 22270).

## Fonctionnalités

- 📊 **Tableau de bord** : visualisation des prix de l'électricité (ENTSO-E), consommation et mix énergétique finlandais
- 🏭 **Gestion de production** : planification de commandes produit/machine avec calcul du coût énergétique heure par heure
- ⚡ **Optimisation automatique** : recherche du meilleur créneau de démarrage selon le seuil de prix configuré
- 📧 **Planning d'envoi** : génération du planning de production par opérateur machine
- 🔐 **Authentification** : système de login/inscription par utilisateur

## Technologies

- Python 3.10+
- PyQt6 (interface graphique)
- SQLite (base de données locale)
- `entsoe-py` (API ENTSO-E Transparency Platform)
- `pandas`, `matplotlib`

## Installation

### 1. Cloner le dépôt
```bash
git clone https://github.com/<votre-compte>/oodi-energy-manager.git
cd oodi-energy-manager
```

### 2. Installer les dépendances
```bash
pip install PyQt6 pandas matplotlib requests entsoe-py python-dotenv
```

### 3. Configurer les clés API
Copiez le fichier `.env.example` en `.env` et renseignez vos clés :
```bash
cp .env.example .env
```

Éditez `.env` :
```
ENTSOE_TOKEN=votre_token_entsoe
OODI_CODE=votre_code_propriete_nuuka
```

> **Token ENTSO-E** : inscription gratuite sur [transparency.entsoe.eu](https://transparency.entsoe.eu/)

### 4. Lancer l'application
```bash
python main_window.py
```

## Structure du projet

```
├── main_window.py      # Fenêtre principale (PyQt5)
├── main_window.ui      # Layout Qt Designer
├── api.py              # Logique métier (calculs, planning)
├── fetch_data.py       # Appels API ENTSO-E & Nuuka
├── oodi_energy.py      # Couche base de données SQLite
├── setup_wizard.py     # Assistant de configuration initiale
├── config.json         # Seuil d'alerte prix (persisté localement)
├── .env.example        # Template des variables d'environnement
└── .gitignore
```

## Licence

Projet académique — usage éducatif uniquement.
