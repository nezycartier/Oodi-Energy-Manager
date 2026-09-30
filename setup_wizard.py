"""
setup_wizard.py — Écran d'accueil Login de l'application VOODOO.
Fond vidéo via QGraphicsVideoItem + panneau d'auth sombre centré.
L'email agit comme une barre de recherche avec autocomplétion des emails connus.
Les nouveaux opérateurs inscrits sont ajoutés à la base.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QLabel,
    QLineEdit, QPushButton, QApplication,
    QGraphicsView, QGraphicsScene, QCompleter
)
from PyQt6.QtCore import Qt, QUrl, QRectF, QSizeF, QStringListModel
from PyQt6.QtGui import QPainterPath, QRegion, QFontDatabase, QPixmap, QBitmap, QPainter, QBrush, QColor
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
import os
import oodi_energy as database
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SetupWizard")


class OodiLogoWidget(QWidget):
    """Dessine le logo Oodi vectorisé de manière lisible à l'aide de cercles."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 100)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # Rendu en BLANC
        painter.setBrush(QBrush(QColor(255, 255, 255, 255)))

        cy = self.height() // 2
        spacing = 20
        
        diam1 = 86  
        diam2 = 64  
        diam3 = 48  

        x_current = 40
        
        # Grand 'O'
        painter.drawEllipse(int(x_current), int(cy - diam1 / 2), diam1, diam1)
        x_current += diam1 + spacing
        
        # Moyen 'o'
        painter.drawEllipse(int(x_current), int(cy - diam2 / 2), diam2, diam2)
        
        # Rapprochement spécifique
        x_current += diam2 + spacing - 20

        # Petit 'D'
        r3 = diam3 / 2.0
        cut_offset_d = 8
        cx3 = x_current + r3
        painter.save()
        painter.setClipRect(int(cx3 - cut_offset_d), int(cy - r3), int(r3 + cut_offset_d), diam3)
        painter.drawEllipse(int(x_current), int(cy - r3), diam3, diam3)
        painter.restore()
        
        width_d = r3 + cut_offset_d
        x_current += width_d + spacing + 12

        # Petit 'I'
        width_i = 12
        cx4 = x_current + width_i / 2.0
        painter.save()
        painter.setClipRect(int(cx4 - width_i / 2), int(cy - r3), width_i, diam3)
        painter.drawEllipse(int(cx4 - r3), int(cy - r3), diam3, diam3)
        painter.restore()

        painter.end()


class SetupWizard(QDialog):
    """Fenêtre d'authentification compacte, coins ronds, fond vidéo."""

    W, H = 960, 540

    def __init__(self, parent=None, video_path: str = None):
        super().__init__(parent)
        # Enregistrer Work Sans dès que QApplication est active
        _font_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "assets", "WorkSans-Regular.ttf"
        )
        if os.path.exists(_font_path):
            QFontDatabase.addApplicationFont(_font_path)
        self.setWindowTitle("VOODOO Startup × Oodi Helsinki")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)

        # Variables for dragging the frameless window
        self._drag_pos = None

        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            self.move((sg.width() - self.W) // 2, (sg.height() - self.H) // 2)

        self.video_path = video_path or r"C:\Users\mszeb\Desktop\PROJET OODI ANTIGRA\2102745852.mp4"
        self._setup_ui()
        self._setup_email_completer()

    def _setup_ui(self):
        # ── Fond Vidéo ─────────────────────────────────────────────────────────
        self._scene = QGraphicsScene(self)
        self._gview = QGraphicsView(self._scene, self)
        self._gview.setGeometry(self.rect())
        self._gview.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._gview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Pour que la vue ne cache pas les widgets par-dessus via opacité, 
        # mais ici elle est en arrière plan, c'est bon.

        self._video_item = QGraphicsVideoItem()
        self._scene.addItem(self._video_item)

        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._video_item)
        if os.path.exists(self.video_path):
            self._player.setSource(QUrl.fromLocalFile(os.path.abspath(self.video_path)))
            self._player.play()
        
        # Pour boucler correctement
        self._player.mediaStatusChanged.connect(self._loop_video)

        # ── Overlay Logo ───────────────────────────────────────────────────────
        self.logo_overlay = OodiLogoWidget(self)

        # ── Panneau d'identification (droite) ──────────────────────────────
        self.login_panel = QWidget(self)
        self.login_panel.setObjectName("login_panel")
        self.login_panel.setFixedWidth(310)
        self.login_panel.setStyleSheet("""
            QWidget#login_panel {
                background-color: rgba(10, 10, 14, 60);
                border-radius: 16px;
                border: 1px solid rgba(255,255,255,0.15);
            }
            QLabel {
                color: rgba(255,255,255,0.85);
                font-family: "Work Sans", "Segoe UI", sans-serif;
                background: transparent;
                border: none;
            }
            QLineEdit {
                background-color: rgba(0, 0, 0, 140);
                border: 1px solid rgba(255,255,255,0.15);
                padding: 10px 14px;
                color: rgba(255,255,255,0.92);
                border-radius: 8px;
                font-size: 10pt;
                font-family: "Work Sans", "Segoe UI", sans-serif;
            }
            QLineEdit:focus {
                background-color: rgba(0, 0, 0, 180);
                border: 1px solid rgba(255,255,255,0.40);
            }
            QPushButton {
                background-color: rgba(255,255,255,0.14);
                border: 1px solid rgba(255,255,255,0.20);
                border-radius: 8px;
                color: #ffffff;
                font-weight: 600;
                font-size: 10pt;
                padding: 10px;
                font-family: "Work Sans", "Segoe UI", sans-serif;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.25);
            }
            QPushButton:pressed {
                background-color: rgba(255,255,255,0.10);
            }
            QPushButton#btn_quit {
                background-color: transparent;
                color: rgba(255,255,255,0.25);
                font-size: 8pt;
                font-weight: normal;
                border: none;
                padding: 2px;
            }
            QPushButton#btn_quit:hover { color: rgba(255,255,255,0.60); }
        """)

        panel_layout = QVBoxLayout(self.login_panel)
        panel_layout.setContentsMargins(28, 32, 28, 28)
        panel_layout.setSpacing(12)

        lbl_title = QLabel("Oodi Helsinki")
        lbl_title.setStyleSheet(
            'font-family: "Work Sans", "Segoe UI", sans-serif; font-size: 22pt; font-weight: 700; color: #ffffff; letter-spacing: 3px;'
        )
        
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(lbl_title)

        self.lbl_subtitle = QLabel("Connexion")
        self.lbl_subtitle.setStyleSheet("font-size: 8pt; color: rgba(255,255,255,0.35); letter-spacing: 1px;")
        self.lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_subtitle.setWordWrap(True)
        panel_layout.addWidget(self.lbl_subtitle)

        panel_layout.addSpacing(4)

        # Email
        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("Email (@oodi.fi)")
        self.input_email.textChanged.connect(self._on_email_changed)
        panel_layout.addWidget(self.input_email)

        # Mot de passe (login)
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Mot de passe")
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_password.returnPressed.connect(self._on_action_clicked)
        self.input_password.setVisible(False)
        panel_layout.addWidget(self.input_password)

        # Nouveau mot de passe (signup uniquement)
        self.input_new_password = QLineEdit()
        self.input_new_password.setPlaceholderText("Créer un mot de passe")
        self.input_new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_new_password.setVisible(False)
        panel_layout.addWidget(self.input_new_password)

        self.input_confirm = QLineEdit()
        self.input_confirm.setPlaceholderText("Réécrire le mot de passe")
        self.input_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_confirm.returnPressed.connect(self._on_action_clicked)
        self.input_confirm.setVisible(False)
        panel_layout.addWidget(self.input_confirm)

        # Rôle / Poste (au lieu de Nom)
        self.input_role = QLineEdit()
        self.input_role.setPlaceholderText("Poste de l'opérateur")
        self.input_role.setVisible(False)
        panel_layout.addWidget(self.input_role)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #ff6666; font-size: 8pt;")
        self.lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        panel_layout.addWidget(self.lbl_error)

        self.btn_action = QPushButton("Continuer")
        self.btn_action.clicked.connect(self._on_action_clicked)
        panel_layout.addWidget(self.btn_action)

        self.btn_quit = QPushButton("Quitter")
        self.btn_quit.setObjectName("btn_quit")
        self.btn_quit.clicked.connect(self.reject)
        panel_layout.addWidget(self.btn_quit, alignment=Qt.AlignmentFlag.AlignCenter)

        self.current_mode = "unknown"
        self._reposition_panel()
        self.login_panel.raise_()

    # ── Autocomplétion ───────────────────────────────────────────────────────

    def _setup_email_completer(self):
        """Charge les emails connus depuis la base et les branche sur l'input."""
        try:
            users = database.get_all_users()
            emails = [u["email"] for u in users if u.get("email")]
        except Exception:
            emails = []

        self._completer_model = QStringListModel(emails)
        completer = QCompleter(self._completer_model, self.input_email)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.input_email.setCompleter(completer)

    # ── Geometry ─────────────────────────────────────────────────────────────

    def _reposition_panel(self):
        self.login_panel.adjustSize()
        # Panneau ancré à droite avec une marge de 40px
        margin_right = 40
        x = self.W - self.login_panel.width() - margin_right
        y = (self.H - self.login_panel.height()) // 2
        self.login_panel.move(x, y)
        
        # Position du Logo blanc
        logo_w, logo_h = 320, 100
        logo_x = max(40, (self.W // 2 - self.login_panel.width() // 2 - logo_w) // 2)
        logo_y = (self.H - logo_h) // 2
        self.logo_overlay.move(logo_x, logo_y)

    def _apply_rounded_mask(self):
        """Masque bitmap antialiasé pour des coins vraiment ronds et nets."""
        bmp = QBitmap(self.size())
        bmp.fill(Qt.GlobalColor.color0)          # tout en noir (masqué)
        painter = QPainter(bmp)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Dessiner le rectangle plein (fenêtre visible)
        painter.setBrush(Qt.GlobalColor.color1)  # blanc = visible
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 20, 20)
        
        painter.end()
        self.setMask(bmp)

    # ── Mouvement de la fenêtre ───────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._gview.setGeometry(self.rect())
        self._video_item.setSize(QSizeF(self.width(), self.height()))
        self._scene.setSceneRect(0, 0, self.width(), self.height())
        self._reposition_panel()
        self.login_panel.raise_()
        self._apply_rounded_mask()

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_panel()
        self.login_panel.raise_()
        self._apply_rounded_mask()

    # ── Media ─────────────────────────────────────────────────────────────────

    def _loop_video(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    # ── Auth Logic ────────────────────────────────────────────────────────────

    def _show_error(self, message):
        self.lbl_error.setText(message)
        self.lbl_error.setVisible(True)

    def _hide_error(self):
        self.lbl_error.setVisible(False)

    def _on_email_changed(self, text):
        self._hide_error()
        email = text.strip()

        if not email or "@" not in email:
            # Pas encore d'email valide : on attend
            self.current_mode = "unknown"
            self.btn_action.setText("Continuer")
            self.input_password.setVisible(False)
            self.input_new_password.setVisible(False)
            self.input_confirm.setVisible(False)
            self.input_role.setVisible(False)
            self.lbl_subtitle.setText("Identifiez-vous pour accéder à l'application")

        elif database.user_exists(email):
            # Email connu → formulaire de connexion
            self.current_mode = "login"
            self.btn_action.setText("Se connecter")
            self.input_password.setVisible(True)
            self.input_new_password.setVisible(False)
            self.input_confirm.setVisible(False)
            self.input_role.setVisible(False)
            self.lbl_subtitle.setText("Bon retour ! Entrez votre mot de passe.")

        else:
            # Email inconnu → formulaire d'inscription
            self.current_mode = "signup"
            self.btn_action.setText("Créer mon compte")
            self.input_password.setVisible(False)
            self.input_new_password.setVisible(True)
            self.input_confirm.setVisible(True)
            self.input_role.setVisible(True)
            self.lbl_subtitle.setText("Nouvel utilisateur. Créez votre compte.")

        self._reposition_panel()

    def _on_action_clicked(self):
        self._hide_error()
        email = self.input_email.text().strip()

        if not email or "@" not in email:
            self._show_error("Entrez une adresse e-mail valide.")
            return

        if self.current_mode == "login":
            password = self.input_password.text()
            if not password:
                self._show_error("Veuillez entrer votre mot de passe.")
                return
            user = database.check_login(email, password)
            if user:
                logger.info(f"Connexion réussie : {email}")
                self.accept()
            else:
                self._show_error("Mot de passe incorrect.")

        elif self.current_mode == "signup":
            role = self.input_role.text().strip()
            password = self.input_new_password.text()
            confirm = self.input_confirm.text()
            if not role:
                self._show_error("Le poste de l'opérateur est requis.")
                return
            if not password:
                self._show_error("Veuillez créer un mot de passe.")
                return
            if password != confirm:
                self._show_error("Les mots de passe ne correspondent pas.")
                return
            if len(password) < 4:
                self._show_error("Mot de passe trop court (4 caractères min).")
                return

            # Créer le compte
            success = database.create_user(role, email, password)
            if success:
                logger.info(f"Nouveau compte créé : {role} <{email}>")
                # Mettre à jour l'autocomplétion avec le nouvel email
                existing = self._completer_model.stringList()
                if email not in existing:
                    self._completer_model.setStringList(existing + [email])
                self.accept()
            else:
                self._show_error("Erreur lors de la création du compte.")
        else:
            self._show_error("Entrez d'abord une adresse e-mail.")
