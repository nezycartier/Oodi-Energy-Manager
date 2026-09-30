import os
import pandas as pd
import requests
from datetime import datetime, timedelta
from entsoe import EntsoePandasClient

# Chargement du fichier .env si présent (développement local)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optionnel, les variables d'env système suffisent

TZ_FINLAND = "Europe/Helsinki"

# Clés API — à définir dans un fichier .env (voir .env.example)
ENTSOE_TOKEN = os.environ.get("ENTSOE_TOKEN", "")
OODI_CODE    = os.environ.get("OODI_CODE", "")

ENERGY_SOURCES = {
    'Nuclear':                         ('#8B008B', 'Nucléaire'),
    'Hydro Run-of-river and poundage': ('#1E90FF', 'Hydraulique'),
    'Wind Onshore':                    ('#00CED1', 'Éolien'),
    'Solar':                           ('#FFD700', 'Solaire'),
    'Biomass':                         ('#228B22', 'Biomasse'),
    'Other renewable':                 ('#90EE90', 'Autre renouvelable'),
    'Fossil Gas':                      ('#FF8C00', 'Gaz fossile'),
    'Fossil Hard coal':                ('#2F4F4F', 'Charbon'),
    'Fossil Oil':                      ('#8B4513', 'Pétrole'),
    'Fossil Peat':                     ('#A0522D', 'Tourbe'),
    'Waste':                           ('#808080', 'Déchets'),
    'Other':                           ('#D3D3D3', 'Autre'),
}

def get_all_data(start_dt, end_dt):

    warnings = []
    
    # 1. CONSOMMATION OODI (API NUUKA HELSINKI)
    url_nuuka = (
        f"https://helsinki-openapi.nuuka.cloud/api/v1.0/EnergyData/Daily/"
        f"ListByProperty?Record=PropertyCode&SearchString={OODI_CODE}"
        f"&ReportingGroup=Electricity&StartTime={start_dt}&EndTime={end_dt}"
    )
    try:
        r_nuuka = requests.get(url_nuuka, timeout=15)
        df_oodi = pd.DataFrame(r_nuuka.json())
        if df_oodi.empty: raise Exception("Vide")
        
        df_oodi['timestamp'] = pd.to_datetime(df_oodi['timestamp']).dt.tz_localize('UTC').dt.tz_convert(TZ_FINLAND).dt.tz_localize(None)
        df_oodi.set_index('timestamp', inplace=True)
        df_oodi = df_oodi[['value']].rename(columns={'value': 'Conso_kWh'})
    except:
        warnings.append("Consommation Oodi indisponible (utilisé : Simulation)")
        idx = pd.date_range(start_dt, end_dt, freq='D')
        df_oodi = pd.DataFrame({'Conso_kWh': [200.0*24]*len(idx)}, index=idx)

    # 2. ENTSO-E (Prix & Production)
    start_pd = pd.Timestamp(start_dt, tz=TZ_FINLAND)
    end_pd   = pd.Timestamp(end_dt, tz=TZ_FINLAND) + pd.Timedelta(days=1)
    
    client = EntsoePandasClient(api_key=ENTSOE_TOKEN)
    try:
        prices = client.query_day_ahead_prices('FI', start=start_pd, end=end_pd)
        prices.index = prices.index.tz_convert(TZ_FINLAND).tz_localize(None)
        daily_prices = prices.resample('D').mean()
    except:
        warnings.append("Prix ENTSO-E indisponibles (utilisé : 50€/MWh)")
        daily_prices = pd.Series(50.0, index=df_oodi.index)

    try:
        gen_entsoe = client.query_generation('FI', start=start_pd, end=end_pd)
        gen_entsoe.index = gen_entsoe.index.tz_convert(TZ_FINLAND).tz_localize(None)
        daily_prod_total = gen_entsoe.sum(axis=1).resample('D').mean()
    except:
        warnings.append("Mix Énergétique indisponible (utilisé : 0)")
        daily_prod_total = pd.Series(8000.0, index=df_oodi.index)
        gen_entsoe = pd.DataFrame(0.0, index=df_oodi.index, columns=ENERGY_SOURCES.keys())


    def fetch_meteo():
        # Helsinki: 60.17, 24.94
        url = f"https://archive-api.open-meteo.com/v1/archive?latitude=60.17&longitude=24.94&start_date={start_dt}&end_date={end_dt}&hourly=temperature_2m"
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            df = pd.DataFrame({
                'timestamp': pd.to_datetime(data['hourly']['time']),
                'Temperature': data['hourly']['temperature_2m']
            })
            df.set_index('timestamp', inplace=True)
            # Moyenne journalière puis alignement sur l'index d'Oodi
            df_daily = df.resample('D').mean()
            return df_daily['Temperature'].reindex(df_oodi.index, method='ffill').fillna(15.0)
        except Exception:
            warnings.append("Météo indisponible (utilisé : 15°C)")
            return pd.Series(15.0, index=df_oodi.index)

    daily_temp = fetch_meteo()

    # 4. AGRÉGATION FINALE
    df = df_oodi.copy()
    if 'Conso_kWh' in df.columns:
        df['Conso_kWh'] = pd.to_numeric(df['Conso_kWh'], errors='coerce').fillna(0)
    df['Prix_EUR_MWh']      = pd.to_numeric(daily_prices.reindex(df.index, method='ffill'), errors='coerce').fillna(50.0)
    df['Prod_Nationale_MW'] = pd.to_numeric(daily_prod_total.reindex(df.index, method='ffill'), errors='coerce').fillna(8000.0)
    df['Temp_C']            = pd.to_numeric(daily_temp, errors='coerce').fillna(15.0)
    df['Facture_EUR']       = (df['Conso_kWh'] / 1000) * df['Prix_EUR_MWh']

    daily_sources_dict = {}
    for col, (color, label) in ENERGY_SOURCES.items():
        try:
            if col in gen_entsoe.columns:
                data = gen_entsoe[col]
                if isinstance(data, pd.DataFrame): data = data.iloc[:, 0]
                series = data.resample('D').mean()
                final_val = series.reindex(df.index, method='ffill').fillna(0)
                if isinstance(final_val, pd.DataFrame): final_val = final_val.iloc[:, 0]
                daily_sources_dict[col] = final_val
            else:
                daily_sources_dict[col] = pd.Series(0.0, index=df.index)
        except:
            daily_sources_dict[col] = pd.Series(0.0, index=df.index)
    
    daily_sources_df = pd.DataFrame(daily_sources_dict, index=df.index)

    parts = {}
    for col, (color, label) in ENERGY_SOURCES.items():
         series = daily_sources_df[col]
         # Sécurité division par zéro
         prod = df['Prod_Nationale_MW'].replace(0, 1e-9)
         parts[label] = (series / prod * 100).fillna(0).mean()
    parts_series = pd.Series(parts).sort_values(ascending=False)

    return {
        'df':            df.fillna(0),
        'daily_sources': daily_sources_df.fillna(0),
        'parts_series':  parts_series,
        'warnings':      warnings
    }


def get_tomorrow_hourly_prices():
    
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow ="2026-04-03"
    import oodi_energy as database

    # Vérification du cache persistant SQLite
    cached_df = database.get_hourly_prices(tomorrow)
    cache_is_complete = (cached_df is not None and not cached_df.empty and len(cached_df) >= 24)

    # Cache complet → retour immédiat sans appel API
    if cache_is_complete:
        return cached_df, False, ""

    # Cache partiel ou inexistant → on tente l'API pour obtenir plus de données
    import requests as _req
    session = _req.Session()
    session.timeout = 30

    client = EntsoePandasClient(api_key=ENTSOE_TOKEN, session=session)
    start = pd.Timestamp(tomorrow, tz=TZ_FINLAND)
    end = start + pd.Timedelta(days=1)
    try:
        prices = client.query_day_ahead_prices('FI', start=start, end=end)
        prices.index = prices.index.tz_convert(TZ_FINLAND).tz_localize(None)
        df = prices.reset_index()
        df.columns = ['Heure', 'Prix_EUR_MWh']
        if df.empty:
            # API ne retourne rien → fallback sur le cache partiel si disponible
            if cached_df is not None and not cached_df.empty:
                return cached_df, False, f"Prix partiels depuis le cache ({len(cached_df)}/24h)"
            return pd.DataFrame(), False, "Prix non encore publiés par ENTSO-E"
        # L'API retourne des données → on écrase le cache si on a plus de données qu'avant
        nb_cache = len(cached_df) if (cached_df is not None and not cached_df.empty) else 0
        if len(df) > nb_cache:
            database.save_hourly_prices(tomorrow, df)
        return df, False, ""
    except Exception as e:
        # API indisponible → fallback sur le cache partiel si disponible
        if cached_df is not None and not cached_df.empty:
            return cached_df, False, f"Prix partiels depuis le cache ({len(cached_df)}/24h)"
        return pd.DataFrame(), False, str(e)


def get_max_price():

    try:
        df, _, _ = get_tomorrow_hourly_prices()
        if df is None or df.empty:
            return None
        return float(pd.to_numeric(df['Prix_EUR_MWh'], errors='coerce').dropna().max())
    except Exception:
        return None


