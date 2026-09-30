# Oodi Energy Manager

ECAM Brussels · Information Systems Project · Solo Project · 17.1/20

Designed and developed from scratch a Python desktop application to automatically optimize the production schedule of an industrial Fablab — based on real-time spot electricity prices on the European energy market (ENTSO-E). Case study: Oodi Library, Helsinki.

---

## Key Technical Highlights

**Constraint-based optimization algorithm** — scalable, no machine limit, minute-by-minute scheduling over 24h, collision detection, configurable price thresholds.

**Full ETL pipeline** — 3 external API sources (ENTSO-E, Nuuka Cloud, Open-Meteo) aggregated via Pandas, with persistent SQLite cache and automatic fallback.

**Multi-threaded architecture** — PyQt6 / QThread keeps the UI fully responsive during asynchronous API calls.

**Relational SQLite database** — parameterized queries (SQL injection prevention), schema migration, session-persistent order management.

**Real-time dashboard** — Matplotlib embedded in PyQt6: hourly price curves, national energy mix breakdown, opportunity window alerts.

**Automatic production schedule generation** — personalized planning per machine operator, exported as structured text.

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | PyQt6, Qt Designer (.ui) |
| Data processing | Pandas, Matplotlib |
| APIs | ENTSO-E Transparency, Nuuka Cloud (Helsinki), Open-Meteo |
| Database | SQLite (via Python stdlib) |
| Concurrency | QThread, pyqtSignal |
| Config | python-dotenv, JSON |

---

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/nezycartier/Oodi-Energy-Manager.git
cd Oodi-Energy-Manager
```

### 2. Install dependencies
```bash
pip install PyQt6 pandas matplotlib requests entsoe-py python-dotenv
```

### 3. Configure API keys
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

```
ENTSOE_TOKEN=your_entsoe_api_token
OODI_CODE=your_nuuka_property_code
```

> Free ENTSO-E token available at [transparency.entsoe.eu](https://transparency.entsoe.eu/)

### 4. Run the application
```bash
python main_window.py
```

---

## Project Structure

```
├── main_window.py      # Main window (PyQt6) — dashboard, orders, alerts
├── main_window.ui      # Qt Designer layout
├── api.py              # Business logic — cost calculation, scheduling, optimization
├── fetch_data.py       # ETL pipeline — ENTSO-E, Nuuka, Open-Meteo
├── oodi_energy.py      # SQLite database layer
├── setup_wizard.py     # First-run configuration wizard
├── config.json         # Persistent price threshold config
├── .env.example        # Environment variable template
└── .gitignore
```

---

## License

Academic project — educational use only.
