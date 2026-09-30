import sys
import os
import json
import re
import time
import traceback
import warnings
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# Force PyQt6 and filter
os.environ["QT_API"] = "PyQt6"
warnings.filterwarnings("ignore", category=DeprecationWarning)

import matplotlib
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QTableWidgetItem,
    QCompleter, QDialog, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QTime, QStringListModel, QTimer
from PyQt6 import uic

from fetch_data import get_all_data, get_tomorrow_hourly_prices, ENERGY_SOURCES
import oodi_energy as database
import api
from setup_wizard import SetupWizard

def setup_poc():
    database.createAllTables()
    if len(database.select_machines("")) == 0:
        database.insert_machines("Imprimante 3D Prusa", 300, "prusa@oodi.fi")
        database.insert_machines("Découpeuse Laser", 1500, "laser@oodi.fi")
        database.insert_machines("Fraiseuse CNC", 2200, "cnc@oodi.fi")
        database.insert_machines("Broyeur Plastique", 800, "recycling@oodi.fi")
    if len(database.select_produits("")) == 0:
        database.insert_produits("Figurine 3D", json.dumps([{"machine": "Imprimante 3D Prusa", "duree": 120}]))
        database.insert_produits("Plaque signalétique", json.dumps([{"machine": "Découpeuse Laser", "duree": 15}]))
        database.insert_produits("Meuble en kit", json.dumps([{"machine": "Fraiseuse CNC", "duree": 45}]))
        database.insert_produits("Recyclage", json.dumps([{"machine": "Broyeur Plastique", "duree": 30}, {"machine": "Imprimante 3D Prusa", "duree": 90}]))

class AnalyseThread(QThread):
    finished = pyqtSignal(object, object, object, list, bool)
    error    = pyqtSignal(str)
    def __init__(self, start_dt, end_dt):
        super().__init__()
        self.start_dt = start_dt
        self.end_dt   = end_dt
    def run(self):
        try:
            data = get_all_data(self.start_dt, self.end_dt)
            df_tomorrow, is_simulated, _ = get_tomorrow_hourly_prices()
            self.finished.emit(data['df'], data['daily_sources'], df_tomorrow, data.get('warnings', []), is_simulated)
        except Exception as e:
            import traceback
            self.error.emit(traceback.format_exc())

class OptimisationThread(QThread):
    finished = pyqtSignal(str, float)
    error    = pyqtSignal(str)
    def __init__(self, nom_produit, qte, thres, existing_cmds=None):
        super().__init__()
        self.nom_produit   = nom_produit
        self.qte           = qte
        self.thres         = thres
        self.existing_cmds = existing_cmds if existing_cmds else []
    def run(self):
        try:
            df, _, _ = get_tomorrow_hourly_prices()
            if df.empty:
                raise Exception("Données de demain indisponibles pour l'optimisation.")
            ranges = api.get_price_ranges(self.thres, df=df)
            if not ranges:
                raise Exception(f"Aucune plage d'opportunité n'est disponible sous le seuil configuré ({self.thres} €).\nL'optimisation a été annulée.")
            best_time, min_cost = api.find_optimal_start_time(self.nom_produit, self.qte, self.existing_cmds, self.thres)
            self.finished.emit(best_time, min_cost)
        except Exception as e:
            self.error.emit(str(e))

class AlertesThread(QThread):
    finished = pyqtSignal(object, bool)   # df, is_simulated
    error_status = pyqtSignal(str)  
    def run(self):
        while not self.isInterruptionRequested():
            try:
                df, is_simulated, err = get_tomorrow_hourly_prices()
                if not df.empty:
                    self.finished.emit(df, is_simulated)
                    break
                else:
                    self.error_status.emit(err)
            except Exception as e:
                self.error_status.emit(str(e))
            time.sleep(10)  

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Load the generated UI File
        ui_path = os.path.join(os.path.dirname(__file__), "main_window.ui")
        uic.loadUi(ui_path, self)

        # Basic init
        setup_poc()
        mois = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        now = datetime.now()
        self.lbl_date.setText(f"{jours[now.weekday()]} {now.day} {mois[now.month]} {now.year}")

        # ----- DASHBOARD TAB INIT -----
        self.date_debut.setDate(QDate.currentDate().addDays(-30))
        self.date_fin.setDate(QDate.currentDate())
        self.btn_analyse.clicked.connect(self.lancer_analyse)
        self.lbl_status_data.hide()
        self.canvases = []
        self.thread = None

        # ----- CONFIG TAB INIT -----
        self._etapes_en_cours = []
        self._editing_machine_nom = None
        self._editing_produit_nom = None
        self.btn_add.clicked.connect(self.ajouter_machine)
        self.btn_del.clicked.connect(self.supprimer_machine)
        self.btn_add_etape.clicked.connect(self.ajouter_etape)
        self.btn_reset.clicked.connect(self.reset_etapes)
        self.btn_add2.clicked.connect(self.ajouter_produit)
        self.btn_del2.clicked.connect(self.supprimer_produit)
        self.btn_edit.clicked.connect(self.charger_machine_pour_modif)
        self.btn_edit2.clicked.connect(self.charger_produit_pour_modif)


        # ----- COMMANDES TAB INIT -----
        self.check_optimiser.toggled.connect(lambda checked: self.time_heure.setEnabled(not checked))
        self.btn_lancer.clicked.connect(self.ajouter_commande)
        self.btn_del_cmd.clicked.connect(self.supprimer_commande)
        self.btn_envoyer.clicked.connect(self.envoyer_mails)
        self._optim_thread = None
        self._pending_prod = None
        self._pending_qte  = None
        self.time_heure.setTime(QTime(8, 0))

        # ----- ALERTS TAB INIT -----
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        try:
            with open(config_path, "r") as f: 
                cfg = json.load(f)
                val = cfg.get("price_alert_threshold", 0.0)
                self.price_threshold = float(val)
        except: 
            self.price_threshold = 0.0
        self.spin_threshold.setValue(int(self.price_threshold))
        self.spin_threshold.valueChanged.connect(self._on_threshold_changed)
        self.btn_refresh_alert.clicked.connect(self.check_alertes)
        self.canvas_prices = None
        self._fetch_thread = None
        QTimer.singleShot(100, self.check_alertes)

        # Global loading sequence
        for table in [self.table_machines, self.table_produits, self.table_commandes, self.table_alertes]:
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.refresh_users()
        self.afficher_db()
        self._refresh_produits()
        self._charger_commandes_db()
        self.update_total()
        self._check_startup_alert()


    # ==========================
    # LOGIQUE DASHBOARD
    # ==========================
    def lancer_analyse(self):
        start_dt = self.date_debut.date().toString("yyyy-MM-dd")
        end_dt   = self.date_fin.date().toString("yyyy-MM-dd")
        if self.date_debut.date() > self.date_fin.date():
            QMessageBox.warning(self, "Dates invalides", "La date de début doit être avant la date de fin.")
            return
        self.btn_analyse.setText("Chargement...")
        self.btn_analyse.setEnabled(False)
        self.lbl_placeholder.show()
        self.lbl_placeholder.setText(f"Récupération des données du {start_dt} au {end_dt}...")
        self.thread = AnalyseThread(start_dt, end_dt)
        self.thread.finished.connect(self.on_analyse_done)
        self.thread.error.connect(self.on_analyse_error)
        self.thread.start()
    
    def on_analyse_done(self, df, daily_sources, df_tomorrow, warnings, is_tomorrow_simulated):
        all_warnings = list(warnings)
        if is_tomorrow_simulated:
            all_warnings.insert(0, "Prix demain indisponibles (utilisé : Simulation)")
        if all_warnings:
            self.lbl_status_data.setText("Attention : " + " | ".join(all_warnings))
            self.lbl_status_data.show()
        else:
            self.lbl_status_data.hide()
            
        start_dt = self.date_debut.date().toString("yyyy-MM-dd")
        end_dt   = self.date_fin.date().toString("yyyy-MM-dd")
        self.lbl_facture_val.setText(f"{df['Facture_EUR'].sum():.2f}")
        self.lbl_conso_val.setText(f"{df['Conso_kWh'].sum():.0f}")
        self.lbl_prix_val.setText(f"{df['Prix_EUR_MWh'].mean():.2f}")
        self.btn_analyse.setText("CHERCHER")
        self.btn_analyse.setEnabled(True)
        self.lbl_placeholder.hide()
        for c in self.canvases:
            self.scroll_layout.removeWidget(c)
            c.deleteLater()
        self.canvases.clear()
        try:
            fig1 = Figure(figsize=(10, 4))
            ax1 = fig1.add_subplot(111)
            fig2 = Figure(figsize=(10, 4))
            ax2 = fig2.add_subplot(111)
            fig3 = Figure(figsize=(10, 4))
            ax3 = fig3.add_subplot(111)

            fig1.suptitle(f"Consommation vs Température ({start_dt} → {end_dt})", fontsize=10, fontweight='bold')
            fig2.suptitle(f"Production & Prix vs Facture ({start_dt} → {end_dt})", fontsize=10, fontweight='bold')
            fig3.suptitle(f"Mix Énergétique Finlandais ({start_dt} → {end_dt})", fontsize=10, fontweight='bold')

            # BLINDAGE ABSOLU MATPLOTLIB (Conversion NumPy/Lists)
            # Sécurisation de l'axe X (toujours des Datetime et non des String)
            x_dates = pd.to_datetime(df.index, errors='coerce')
            
            # Extraction purement numérique
            conso = pd.to_numeric(df.get('Conso_kWh', pd.Series(0, index=df.index)), errors='coerce').fillna(0).to_numpy()
            temp = pd.to_numeric(df.get('Temp_C', pd.Series(15.0, index=df.index)), errors='coerce').fillna(0).to_numpy()
            facture = pd.to_numeric(df.get('Facture_EUR', pd.Series(0, index=df.index)), errors='coerce').fillna(0).to_numpy()
            prix = pd.to_numeric(df.get('Prix_EUR_MWh', pd.Series(0, index=df.index)), errors='coerce').fillna(0).to_numpy()
            prod = pd.to_numeric(df.get('Prod_Nationale_MW', pd.Series(0, index=df.index)), errors='coerce').fillna(0).to_numpy()
            
            ax1.bar(x_dates, conso, color='steelblue', alpha=0.6, label='Conso (kWh)')
            ax1.set_ylabel("kWh", fontsize=9); ax1.grid(axis='y', linestyle='--', alpha=0.4)
            ax1b = ax1.twinx(); ax1b.plot(x_dates, temp, color='red', marker='o', linewidth=1.5, label='Temp (°C)')
            ax1b.set_ylabel("°C", fontsize=9); ax1.legend(loc='upper left', fontsize=8); ax1b.legend(loc='upper right', fontsize=8)
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))

            ax2.bar(x_dates, facture, color='orange', alpha=0.4, label='Facture (€)', zorder=1)
            ax2.set_ylabel("Facture (€)", color='orange', fontsize=9); ax2.tick_params(axis='y', labelcolor='orange')
            ax2.grid(axis='y', linestyle='--', alpha=0.4); ax2b = ax2.twinx()
            ax2b.plot(x_dates, prix, color='darkorange', linestyle='--', linewidth=2, label='Prix (€/MWh)')
            ax2b.set_ylabel("Prix (€/MWh)", color='darkorange', fontsize=9); ax2b.tick_params(axis='y', labelcolor='darkorange')
            ax2c = ax2.twinx(); ax2c.spines['right'].set_position(('outward', 55))
            ax2c.plot(x_dates, prod, color='green', marker='x', markersize=4, linestyle=':', alpha=0.7, label='Production (MW)')
            ax2c.set_ylabel("Prod (MW)", color='green', fontsize=9); ax2c.tick_params(axis='y', labelcolor='green')
            lines, labels = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2b.get_legend_handles_labels()
            lines3, labels3 = ax2c.get_legend_handles_labels()
            ax2.legend(lines + lines2 + lines3, labels + labels2 + labels3, loc='upper left', fontsize=8)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))

            # Graphique en barres empilées par couche (mix énergétique journalier)
            if hasattr(daily_sources, "apply"):
                clean_sources = daily_sources.apply(pd.to_numeric, errors='coerce').fillna(0)
                bottom = None
                for col in clean_sources.columns:
                    serie = clean_sources[col].to_numpy()
                    if serie.sum() == 0:
                        continue
                    color = ENERGY_SOURCES[col][0] if col in ENERGY_SOURCES else '#AAAAAA'
                    label_name = ENERGY_SOURCES[col][1] if col in ENERGY_SOURCES else col
                    if bottom is None:
                        ax3.bar(x_dates, serie, color=color, alpha=0.85, label=label_name)
                        bottom = serie.copy()
                    else:
                        ax3.bar(x_dates, serie, bottom=bottom, color=color, alpha=0.85, label=label_name)
                        bottom = bottom + serie
                ax3.set_ylabel("Mix Energie (MW)", fontsize=9)
                ax3.legend(loc='upper left', fontsize=7, ncol=2)
                ax3.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
                ax3.grid(axis='y', linestyle='--', alpha=0.4)
            else:
                ax3.text(0.5, 0.5, "Aucune donnee de mix energetique", ha='center', va='center')

            # Scrollbar verticale toujours visible
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

            for fig in (fig1, fig2, fig3):
                fig.autofmt_xdate(rotation=45)
                fig.tight_layout()
                c = FigureCanvas(fig)
                c.setMinimumHeight(350)
                self.canvases.append(c)
                self.scroll_layout.addWidget(c)
        except Exception as e:
            QMessageBox.critical(self, "Erreur graphiques", traceback.format_exc())

    def on_analyse_error(self, err_msg):
        self.btn_analyse.setText("CHERCHER")
        self.btn_analyse.setEnabled(True)
        self.lbl_placeholder.setText("Erreur lors de la récupération : " + err_msg)


    # ==========================
    # LOGIQUE CONFIGURATION
    # ==========================
    def refresh_users(self):
        users = database.get_all_users()
        email_list = [f"{u['name']} ({u['email']})" for u in users]
        self._completer_model = QStringListModel(email_list)
        completer = QCompleter(self._completer_model, self.input_operateur)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.input_operateur.setCompleter(completer)
        self._refresh_combo_machines()

    def _refresh_combo_machines(self):
        machines = database.select_machines("")
        self.combo_machine.clear()
        for m in machines:
            self.combo_machine.addItem(m[1])

    def ajouter_etape(self):
        machine_nom = self.combo_machine.currentText()
        duree = self.spin_duree.value()
        if not machine_nom:
            QMessageBox.warning(self, "Aucune machine", "Ajoutez d'abord des machines.")
            return
        self._etapes_en_cours.append({"machine": machine_nom, "duree": duree})
        self._update_etapes_recap()

    def reset_etapes(self):
        self._etapes_en_cours = []
        self._update_etapes_recap()

    def _update_etapes_recap(self):
        if not self._etapes_en_cours:
            self.lbl_etapes_recap.setText("Étapes : (aucune)")
        else:
            parts = [f"{e['machine']} — {e['duree']} min" for e in self._etapes_en_cours]
            self.lbl_etapes_recap.setText("Étapes : " + " → ".join(parts))

    def afficher_db(self):
        machines = database.select_machines("")
        self.table_machines.setRowCount(0)
        for m in machines:
            r = self.table_machines.rowCount()
            self.table_machines.insertRow(r)
            self.table_machines.setItem(r, 0, QTableWidgetItem(m[1]))
            self.table_machines.setItem(r, 1, QTableWidgetItem(str(m[2])))
            self.table_machines.setItem(r, 2, QTableWidgetItem(m[3]))

        produits = database.select_produits("")
        self.table_produits.setRowCount(0)
        for p in produits:
            r = self.table_produits.rowCount()
            self.table_produits.insertRow(r)
            self.table_produits.setItem(r, 0, QTableWidgetItem(p[1]))
            try:
                etapes = json.loads(p[2])
                s = " → ".join([f"{e['machine']} ({e['duree']} min)" for e in etapes])
                self.table_produits.setItem(r, 1, QTableWidgetItem(s))
            except:
                self.table_produits.setItem(r, 1, QTableWidgetItem(p[2]))
            # Colonne budget (index 3 dans BDD)
            budget = p[3] if len(p) > 3 else None
            budget_txt = f"{budget:.2f} €" if budget and budget > 0 else "—"
            self.table_produits.setItem(r, 2, QTableWidgetItem(budget_txt))
        self._refresh_combo_machines()

    def ajouter_machine(self):
        nom = self.input_nom.text()
        puiss = self.input_puissance.text()
        ope_text = self.input_operateur.text().strip()

        match = re.search(r'\((.*?)\)', ope_text)
        ope_email = match.group(1) if match else ope_text

        if not (nom and puiss and ope_email):
            QMessageBox.warning(self, "Champs", "Remplissez nom, puissance et opérateur.")
            return

        # Vérification que l'email appartient à un utilisateur enregistré
        if not database.user_exists(ope_email):
            QMessageBox.warning(
                self, "Opérateur inconnu",
                f"L'email « {ope_email} » ne correspond à aucun utilisateur enregistré.\n\n"
                f"Créez d'abord le compte de cet opérateur avant d'assigner la machine."
            )
            return

        if self._editing_machine_nom:
            # MODE ÉDITION : mise à jour de la machine existante
            machines = database.select_machines("")
            m = next((m for m in machines if m[1] == self._editing_machine_nom), None)
            if m:
                database.update_machines(m[0], nom, float(puiss), ope_email)
            self._editing_machine_nom = None
            self.btn_add.setText("Ajouter Machine")
        else:
            # MODE AJOUT : insertion d'une nouvelle machine
            database.insert_machines(nom, float(puiss), ope_email)

        self.input_nom.clear()
        self.input_puissance.clear()
        self.input_operateur.clear()
        self.afficher_db()

    def charger_machine_pour_modif(self):
        row = self.table_machines.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Sélection", "Sélectionnez d'abord une machine dans le tableau.")
            return
        self.input_nom.setText(self.table_machines.item(row, 0).text())
        self.input_puissance.setText(self.table_machines.item(row, 1).text())
        self.input_operateur.setText(self.table_machines.item(row, 2).text())
        self._editing_machine_nom = self.table_machines.item(row, 0).text()
        self.btn_add.setText("Enregistrer Modification")

    def supprimer_machine(self):
        row = self.table_machines.currentRow()
        if row >= 0:
            nom = self.table_machines.item(row, 0).text()
            produits = database.select_produits("")
            used_in = []
            for p in produits:
                try:
                    etapes = json.loads(p[2])
                    if any(e.get("machine") == nom for e in etapes):
                        used_in.append(p[1])
                except Exception:
                    pass
            if used_in:
                for prod_name in used_in:
                    database.delete_produits_par_nom(prod_name)
                prods = ", ".join(used_in)
                QMessageBox.information(self, "Suppression", 
                                        f"La machine '{nom}' a été supprimée.\n\nLes process suivants ont également été effacés : {prods}.")
            
            database.delete_machines_par_nom(nom)
            self.afficher_db()
            self._refresh_produits()

    def ajouter_produit(self):
        nom = self.input_produit_nom.text().strip()
        if not nom: return
        if not self._etapes_en_cours: return
        budget_val = self.spin_budget_produit.value()
        budget_max = budget_val if budget_val > 0 else None
        if self._editing_produit_nom:
            # MODE ÉDITION : mise à jour du produit existant
            produits = database.select_produits_par_nom(self._editing_produit_nom)
            if produits:
                database.update_produits(produits[0][0], nom, json.dumps(self._etapes_en_cours), budget_max)
            self._editing_produit_nom = None
            self.btn_add2.setText("Sauvegarder produit")
        else:
            # MODE AJOUT : insertion d'un nouveau produit
            database.insert_produits(nom, json.dumps(self._etapes_en_cours), budget_max)

        self.input_produit_nom.clear()
        self.spin_budget_produit.setValue(0)
        self._etapes_en_cours = []
        self._update_etapes_recap()
        self.afficher_db()
        self._refresh_produits()

    def charger_produit_pour_modif(self):
        row = self.table_produits.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Sélection", "Sélectionnez d'abord un produit dans le tableau.")
            return
        nom = self.table_produits.item(row, 0).text()
        produits = database.select_produits_par_nom(nom)
        if not produits:
            return
        prod = produits[0]
        self.input_produit_nom.setText(prod[1])
        budget = prod[3] if len(prod) > 3 and prod[3] else 0
        self.spin_budget_produit.setValue(float(budget))
        try:
            self._etapes_en_cours = json.loads(prod[2])
            self._update_etapes_recap()
        except:
            pass
        self._editing_produit_nom = nom
        self.btn_add2.setText("Enregistrer Modification")

    def supprimer_produit(self):
        row = self.table_produits.currentRow()
        if row >= 0:
            nom = self.table_produits.item(row, 0).text()
            # Vérifier si ce produit est utilisé dans des commandes existantes
            commandes_actives = database.select_commandes()
            utilise = any(c[1] == nom for c in commandes_actives)
            if utilise:
                QMessageBox.warning(
                    self, "Suppression impossible",
                    f"Le process '{nom}' est utilisé dans des commandes actives.\n"
                    f"Supprimez d'abord les commandes associées avant de supprimer ce process."
                )
                return
            database.delete_produits_par_nom(nom)
            self.afficher_db()
            self._refresh_produits()


    # ==========================
    # LOGIQUE COMMANDES
    # ==========================
    def _refresh_produits(self):
        produits = database.select_produits("")
        current = self.combo_produit.currentText()
        self.combo_produit.clear()
        for p in produits:
            self.combo_produit.addItem(p[1])
        idx = self.combo_produit.findText(current)
        if idx >= 0: self.combo_produit.setCurrentIndex(idx)

    def ajouter_commande(self):
        prod = self.combo_produit.currentText()
        raw_heure = self.time_heure.time().toString("HH:mm")
        qte_str = self.input_qte.text().strip()
        if not prod or not qte_str:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner un produit et saisir une quantité.")
            return

        try:
            qte = int(qte_str)
            if qte <= 0: raise ValueError
            if self.check_optimiser.isChecked():
                thres = self.spin_threshold.value()
                self.btn_lancer.setText("Optimisation...")
                self.btn_lancer.setEnabled(False)
                existing_cmds = []
                for row in range(self.table_commandes.rowCount()):
                    c_prod  = self.table_commandes.item(row, 0).text()
                    c_heure = self.table_commandes.item(row, 1).text()
                    c_qte   = int(self.table_commandes.item(row, 3).text())
                    existing_cmds.append((c_prod, c_heure, c_qte))
                self._pending_prod = prod
                self._pending_qte  = qte
                self._optim_thread = OptimisationThread(prod, qte, thres, existing_cmds)
                self._optim_thread.finished.connect(self._on_optim_done)
                self._optim_thread.error.connect(self._on_optim_error)
                self._optim_thread.start()
                return

            self._enregistrer_commande(prod, raw_heure, qte)
        except ValueError:
            QMessageBox.warning(self, "Erreur", "La quantité doit être un entier.")
        except Exception as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def _on_optim_done(self, heure, min_cost):
        self.btn_lancer.setText("Lancer")
        self.btn_lancer.setEnabled(True)
        self._enregistrer_commande(self._pending_prod, heure, self._pending_qte, is_optimised=True)

    def _on_optim_error(self, msg):
        self.btn_lancer.setText("Lancer")
        self.btn_lancer.setEnabled(True)
        QMessageBox.critical(self, "Erreur d'optimisation", msg)

    def _charger_commandes_db(self):
        try:
            rows = database.select_commandes()
            self.table_commandes.setRowCount(0)
            for row in rows:
                db_id, prod, h_debut, h_fin, qte, c_unit, c_total, optimise = row
                r = self.table_commandes.rowCount()
                self.table_commandes.insertRow(r)
                self.table_commandes.setItem(r, 0, QTableWidgetItem(prod))
                self.table_commandes.setItem(r, 1, QTableWidgetItem(h_debut))
                self.table_commandes.setItem(r, 2, QTableWidgetItem(h_fin or "—"))
                self.table_commandes.setItem(r, 3, QTableWidgetItem(str(qte)))
                self.table_commandes.setItem(r, 4, QTableWidgetItem(f"{c_unit:.4f}"))
                self.table_commandes.setItem(r, 5, QTableWidgetItem(f"{c_total:.4f}"))
                item_opt = QTableWidgetItem("OUI" if optimise else "")
                item_opt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table_commandes.setItem(r, 6, item_opt)
                self.table_commandes.item(r, 0).setData(Qt.ItemDataRole.UserRole, db_id)
                # Colonne budget respecté : recalculé depuis la BDD des produits
                produits = database.select_produits_par_nom(prod)
                budget_txt = "—"
                if produits:
                    budget = produits[0][3] if len(produits[0]) > 3 else None
                    if budget and budget > 0:
                        budget_txt = "Oui" if (c_total or 0) <= budget else "Non"
                item_bud = QTableWidgetItem(budget_txt)
                item_bud.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table_commandes.setItem(r, 7, item_bud)
            self.update_total()
        except: pass

    def _enregistrer_commande(self, prod, heure, qte, is_optimised=False):
        try:
            total_cost, details = api.calculate_order_cost(prod, heure, qte)
            unit_cost = total_cost / qte if qte > 0 else 0
            heure_fin = details[-1]["end"] if details else "—"
            db_id = database.insert_commande(prod, heure, heure_fin, qte, unit_cost, total_cost, is_optimised)

            # Vérification du budget max du produit
            produits_info = database.select_produits_par_nom(prod)
            budget_ok = None  # None = pas de budget défini
            budget_txt = "—"
            if produits_info:
                budget = produits_info[0][3] if len(produits_info[0]) > 3 else None
                if budget and budget > 0:
                    budget_ok = total_cost <= budget
                    if budget_ok:
                        budget_txt = "Oui"
                    else:
                        budget_txt = "Non"
                        QMessageBox.warning(
                            self, "Budget depasse !",
                            f"Le cout de la commande '{prod}' est de {total_cost:.2f} EUR\n"
                            f"Le budget maximum defini est de {budget:.2f} EUR\n\n"
                            f"La commande a ete ajoutee, mais le budget n'est pas respecte."
                        )

            r = self.table_commandes.rowCount()
            self.table_commandes.insertRow(r)
            item_prod = QTableWidgetItem(prod)
            item_prod.setData(Qt.ItemDataRole.UserRole, db_id)
            self.table_commandes.setItem(r, 0, item_prod)
            self.table_commandes.setItem(r, 1, QTableWidgetItem(heure))
            self.table_commandes.setItem(r, 2, QTableWidgetItem(heure_fin))
            self.table_commandes.setItem(r, 3, QTableWidgetItem(str(qte)))
            self.table_commandes.setItem(r, 4, QTableWidgetItem(f"{unit_cost:.4f}"))
            self.table_commandes.setItem(r, 5, QTableWidgetItem(f"{total_cost:.4f}"))
            item_opt = QTableWidgetItem("OUI" if is_optimised else "")
            item_opt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_commandes.setItem(r, 6, item_opt)
            item_bud = QTableWidgetItem(budget_txt)
            item_bud.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_commandes.setItem(r, 7, item_bud)

            self.time_heure.setTime(QTime(8, 0))
            self.input_qte.clear()
            self.update_total()
        except Exception as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def supprimer_commande(self):
        row = self.table_commandes.currentRow()
        if row >= 0:
            item = self.table_commandes.item(row, 0)
            if item:
                db_id = item.data(Qt.ItemDataRole.UserRole)
                if db_id is not None:
                    try: database.delete_commande(db_id)
                    except: pass
            self.table_commandes.removeRow(row)
            self.update_total()

    def update_total(self):
        total = 0.0
        for r in range(self.table_commandes.rowCount()):
            item = self.table_commandes.item(r, 5)
            if item: total += float(item.text())
        self.lbl_total.setText(f"Coût total journalier : {total:.4f} €")

    def envoyer_mails(self):
        if self.table_commandes.rowCount() == 0:
            return QMessageBox.information(self, "Aucune commande", "Ajoutez des commandes avant d'envoyer.")
        commandes = [(self.table_commandes.item(r, 0).text(), self.table_commandes.item(r, 1).text(), int(self.table_commandes.item(r, 3).text())) for r in range(self.table_commandes.rowCount())]
        emails_content, log_text = api.build_email_planning(commandes)
        success, summary = api.send_emails(emails_content)
        if success: QMessageBox.information(self, "Planning généré", summary + "\n\n" + log_text)
        else: QMessageBox.critical(self, "Erreur", summary)


    # ==========================
    # LOGIQUE ALERTES
    # ==========================
    def check_alertes(self):
        if self._fetch_thread and self._fetch_thread.isRunning(): return
        self.btn_refresh_alert.setText("Chargement...")
        self.btn_refresh_alert.setEnabled(False)
        self.lbl_statut.setText("En attente des prix de l'ENTSO-E pour demain (boucle)...")

        self._fetch_thread = AlertesThread()
        self._fetch_thread.finished.connect(self._on_prices_received)
        self._fetch_thread.error_status.connect(self._on_error_status)
        self._fetch_thread.start()

    def _on_error_status(self, erreur_msg):
        self.lbl_statut.setText(f"En attente... ({erreur_msg})")

    def _on_threshold_changed(self, value):
        self.price_threshold = value
        try: database.save_threshold(value)
        except: pass

    def _on_prices_received(self, df, is_simulated=False):
        self.btn_refresh_alert.setText("ACTUALISER")
        self.btn_refresh_alert.setEnabled(True)

        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        thres = self.spin_threshold.value()

        if df.empty:
            self.lbl_statut.setText("Prix de demain pas encore publies -- Reessaie apres 12h30 (heure Helsinki)")
            self.lbl_statut.setStyleSheet("")
            self.lbl_statut.show()
            return

        # Donnees disponibles (meme partielles)
        nb_heures = len(df)
        if nb_heures < 24:
            self.lbl_statut.setText(f"Donnees partielles : {nb_heures}/24 heures disponibles")
            self.lbl_statut.setStyleSheet("")
            self.lbl_statut.show()
        else:
            self.lbl_statut.hide()

        df['Prix_EUR_MWh'] = pd.to_numeric(df['Prix_EUR_MWh'], errors='coerce').fillna(0)
        max_price = df['Prix_EUR_MWh'].max()
        self.prixleplushaut.setText(f"Prix max demain : {max_price:.2f} €/MWh")
        ranges = api.get_price_ranges(thres, df=df)
        self.table_alertes.setRowCount(0)

        if not ranges:
            self.lbl_statut.hide()
        else:
            self.lbl_statut.hide()
            for r_data in ranges:
                r = self.table_alertes.rowCount()
                self.table_alertes.insertRow(r)
                d_h = r_data['duree_h']
                h = int(d_h)
                m = int(round((d_h - h) * 60))
                dur_str = f"{h}h{m:02d}"
                self.table_alertes.setItem(r, 0, QTableWidgetItem(r_data['debut']))
                self.table_alertes.setItem(r, 1, QTableWidgetItem(r_data['fin']))
                self.table_alertes.setItem(r, 2, QTableWidgetItem(dur_str))
                self.table_alertes.setItem(r, 3, QTableWidgetItem(f"{r_data['prix_moyen']:.2f}"))

        if self.canvas_prices:
            self.graph_layout_alertes.removeWidget(self.canvas_prices)
            self.canvas_prices.deleteLater()
            self.canvas_prices = None

        fig = Figure(figsize=(10, 4))
        ax = fig.add_subplot(111)
        ax.set_title(f"Prix horaires — Demain {tomorrow_str}", fontsize=9, color='#1A1A1A', fontweight='bold')
        
        df['Heure'] = pd.to_datetime(df['Heure'])
        df['Prix_EUR_MWh'] = pd.to_numeric(df['Prix_EUR_MWh'], errors='coerce').fillna(0)

        ax.plot(df['Heure'], df['Prix_EUR_MWh'], marker='o', color='steelblue', linewidth=1.5, label="Prix (€/MWh)")
        ax.axhline(thres, color='red', linestyle='--', label=f"Seuil ({thres} €/MWh)")
        ax.fill_between(
            df['Heure'], df['Prix_EUR_MWh'], thres,
            where=(pd.to_numeric(df['Prix_EUR_MWh']) <= thres),
            color='salmon', alpha=0.5, label="Zone opportunité"
        )
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        fig.autofmt_xdate(rotation=90)
        ax.legend(fontsize=8)
        ax.grid(axis='both', linestyle='--', alpha=0.4)
        fig.tight_layout()
        self.canvas_prices = FigureCanvas(fig)
        self.graph_layout_alertes.addWidget(self.canvas_prices)

    def _check_startup_alert(self):
        try:
            ranges = api.get_price_ranges(self.price_threshold)
            if ranges:
                txt = "\n".join([f" • De {r['debut']} à {r['fin']}" for r in ranges])
                QMessageBox.warning(self, "Opportunité !", f"Prix sous {self.price_threshold} € demain :\n\n{txt}")
        except: pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    database.createAllTables()
    wizard = SetupWizard(video_path=os.path.join(os.path.dirname(__file__), "2102745852.mp4"))
    if wizard.exec() == QDialog.DialogCode.Accepted:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    else: 
        sys.exit(0)
