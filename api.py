# =============================================================================
# api.py — Logique métier OODI Energy Manager
# =============================================================================
# Ce fichier contient toute la logique "non-visuelle" du projet :
#   - Calcul du coût d'une commande heure par heure
#   - Construction du planning d'emails par opérateur
#   - Envoi SMTP réel (avec fallback simulation si config absente)
#   - Vérification des alertes de prix négatifs
# =============================================================================

import json
import os
from datetime import datetime, timedelta

# Imports internes du projet
from fetch_data import get_tomorrow_hourly_prices
import oodi_energy as database


# ---------------------------------------------------------------------------
# CALCUL DU COÛT D'UNE COMMANDE
# ---------------------------------------------------------------------------

def calculate_order_cost(nom_produit, heure_depart_str, qte=1, 
                         df_prices_prefetched=None, 
                         produits_prefetched=None, 
                         machines_prefetched=None):
    """
    Simule la demande et calcule le coût exact de la fabrication.
    """
    if df_prices_prefetched is not None:
        df_prices = df_prices_prefetched
    else:
        df_prices, _, _ = get_tomorrow_hourly_prices()

    if produits_prefetched is not None:
        produits = produits_prefetched
    else:
        produits = database.select_produits("")

    if machines_prefetched is not None:
        machines = machines_prefetched
    else:
        machines = {m[1]: m for m in database.select_machines("")}

    prod = next((p for p in produits if p[1] == nom_produit), None)
    if not prod:
        raise Exception(f"Produit '{nom_produit}' introuvable.")

    etapes = json.loads(prod[2])
    h, m = map(int, heure_depart_str.split(':'))
    current_min = h * 60 + m

    total_cost_unit = 0.0
    detail = []

    for et in etapes:
        m_nom = et['machine']
        duree_min_unit = et['duree']
        total_duree_etape = duree_min_unit * qte

        if m_nom not in machines:
            raise Exception(f"Machine '{m_nom}' introuvable.")

        puissance_kw = float(machines[m_nom][2]) / 1000.0
        
        # Vérification Sécurité Minuit (AVANT l'accès aux index)
        total_duree_etape = duree_min_unit * qte
        if current_min + total_duree_etape > 24 * 60:
            raise Exception(f"Le process pour {qte}x {nom_produit} dépasse minuit sur la machine {m_nom}.")

        # --- Découpage Horaire Précis (calcul exact minute par minute) ---
        if not hasattr(df_prices, '_prices_1440'):
            prices_arr = [50.0] * 1440
            if not df_prices.empty:
                import pandas as pd
                df_sorted = df_prices.copy()
                
                if not hasattr(df_sorted['Heure'].iloc[0], 'hour'):
                    df_sorted['Heure'] = pd.to_datetime(df_sorted['Heure'])
                df_sorted = df_sorted.sort_values('Heure')
                
                for i in range(len(df_sorted)):
                    row_t = df_sorted.iloc[i]['Heure']
                    start_min = row_t.hour * 60 + row_t.minute
                    end_min = 1440
                    if i + 1 < len(df_sorted):
                        next_t = df_sorted.iloc[i+1]['Heure']
                        end_min = next_t.hour * 60 + next_t.minute
                    if end_min < start_min: end_min = 1440
                    for _m in range(start_min, end_min):
                        if _m < 1440: prices_arr[_m] = float(df_sorted.iloc[i]['Prix_EUR_MWh'])
            df_prices._prices_1440 = prices_arr
        else:
            prices_arr = df_prices._prices_1440

        etape_cost_total = 0.0
        start_t = current_min
        end_t = current_min + total_duree_etape
        
        for t in range(start_t, end_t):
            prix = prices_arr[t] if t < 1440 else 50.0
            etape_cost_total += (puissance_kw * (1.0 / 60.0)) * (prix / 1000.0)

        sh, sm = current_min // 60, current_min % 60
        # On avance le curseur de temps du temps TOTAL (unité * qté) pour l'étape suivante
        current_min += (duree_min_unit * qte)
        eh, em = current_min // 60, current_min % 60

        detail.append({
            "machine":    m_nom,
            "email":      machines[m_nom][3],
            "start":      f"{sh:02d}:{sm:02d}",
            "end":        f"{eh:02d}:{em:02d}",
            "duree_min":  total_duree_etape, # On garde la durée totale de l'étape pour le rapport
            "cout_eur":   etape_cost_total,
        })
        total_cost_unit += etape_cost_total

    return total_cost_unit, detail


# ---------------------------------------------------------------------------
# CONSTRUCTION DU PLANNING D'EMAILS
# ---------------------------------------------------------------------------

def build_email_planning(commandes):
   
    planning = {}
    log_lines = ["Rapport d'Envoi des Plannings de Production :", "=" * 50]

    for (nom_produit, heure_depart, qte) in commandes:
        try:
            # On utilise le nouveau calculate_order_cost qui gère déjà la QTE
            total_cost, detail = calculate_order_cost(nom_produit, heure_depart, qte)
            log_lines.append(f"\n[OK] COMMANDE : {qte}x {nom_produit} | Départ : {heure_depart}")
            log_lines.append(f"   Coût Énergie Total : {total_cost:.2f} €")
        except Exception as e:
            log_lines.append(f"[ERREUR] pour {nom_produit} : {e}")
            continue

        for step in detail:
            email   = step["email"]
            machine = step["machine"]
            # L'heure de fin dans 'detail' prend déjà en compte la QTE car calc_order_cost 
            # avance current_min de (duree * qte).
            line = f"  → [{machine}] de {step['start']} à {step['end']} ({qte} unités)"

            log_lines.append(line)
            if email not in planning:
                planning[email] = []
            planning[email].append(f"MISSION : Produire {qte}x {nom_produit}\n{line}\n")

    # Formatage final des mails
    emails_content = {}
    for email, missions in planning.items():
        emails_content[email] = (
            "Bonjour,\n\nVoici votre planning OODI Energy Manager :\n\n"
            + "\n".join(missions)
            + "\nBonne production !\n"
        )

    log_text = "\n".join(log_lines)
    try:
        with open("emails_sent.log", "w", encoding="utf-8") as f:
            f.write(log_text)
    except Exception:
        pass

    return emails_content, log_text




# ---------------------------------------------------------------------------
# ENVOI SMTP
# ---------------------------------------------------------------------------

def send_emails(emails_content):
   
    output_path = os.path.join(os.path.dirname(__file__), "planning_emails.txt")
    lines = []
    lines.append("=" * 60)
    lines.append("  PLANNING DE PRODUCTION — OODI Energy Manager")
    lines.append(f"  Généré le : {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")

    for to_addr, body in emails_content.items():
        lines.append(f"┌─ DESTINATAIRE : {to_addr}")
        lines.append("│")
        for line in body.splitlines():
            lines.append(f"│  {line}")
        lines.append("└" + "─" * 58)
        lines.append("")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        recipients = list(emails_content.keys())
        return True, (
            f"Planning écrit dans 'planning_emails.txt'.\n"
            f"{len(recipients)} destinataire(s) : {', '.join(recipients)}"
        )
    except Exception as e:
        return False, f"Impossible d'écrire le fichier planning_emails.txt : {e}"



def get_price_ranges(threshold=0.0, df=None):
    
    threshold = float(threshold)
    if df is None:
        df, _, _ = get_tomorrow_hourly_prices()
    if df.empty:
        return []
    
    # Sécurité : Tri et suppression des doublons par heure
    df = df.sort_values('Heure').drop_duplicates('Heure').reset_index(drop=True)

    # Calcul de la durée d'un point (en heures)
    point_dur_h = 1.0
    if len(df) > 1:
        t0 = df['Heure'].iloc[0]
        t1 = df['Heure'].iloc[1]
        # Protection: s'assurer que ce sont des datetime
        if hasattr(t1, 'total_seconds'):
            delta = t1.total_seconds() / 3600.0
        else:
            delta = (t1 - t0).total_seconds() / 3600.0
        point_dur_h = max(round(delta, 4), 1/60)  # Minimum 1 minute

    ranges = []
    current_range = None

    for _, row in df.iterrows():
        prix = float(row['Prix_EUR_MWh'])
        heure = row['Heure']
        # S'assurer que heure est bien un Timestamp/datetime
        if not hasattr(heure, 'strftime'):
            import pandas as pd
            heure = pd.Timestamp(heure)

        is_below = prix <= threshold

        if is_below:
            if current_range is None:
                # Début d'une nouvelle plage : début = heure exacte du point
                current_range = {
                    "debut":    heure,
                    "fin":      heure + timedelta(hours=point_dur_h),
                    "prix_sum": prix,
                    "count":    1
                }
            else:
                # Extension de la plage : fin = heure du point courant + durée d'un point
                current_range["fin"]      = heure + timedelta(hours=point_dur_h)
                current_range["prix_sum"] += prix
                current_range["count"]   += 1
        else:
            if current_range is not None:
                ranges.append(current_range)
                current_range = None

    # Ne pas oublier la dernière plage ouverte
    if current_range is not None:
        ranges.append(current_range)

    # Formatage final
    result = []
    for r in ranges:
        duree = r["count"] * point_dur_h
        result.append({
            "debut":      r["debut"].strftime("%H:%M"),
            "fin":        r["fin"].strftime("%H:%M"),
            "duree_h":    round(duree, 2),
            "prix_moyen": round(r["prix_sum"] / r["count"], 2)
        })
    return result

def find_optimal_start_time(nom_produit, qte=1, existing_cmds=None, thres=0.0):
    
    if existing_cmds is None:
        existing_cmds = []

    best_time = None
    min_cost  = float('inf')

    # Chargement unique des données (rend la boucle quasi instantanée)
    df_prices, _, _ = get_tomorrow_hourly_prices()
    if df_prices.empty:
        raise Exception("Les prix de demain ne sont pas encore disponibles via ENTSO-E.\nVeuillez réessayer plus tard.")
        
    produits  = database.select_produits("")
    machines  = {m[1]: m for m in database.select_machines("")}

    # 1. CONSTRUCTION DU CALENDRIER D'OCCUPATION DES MACHINES (1440 minutes = 1 jour)
    machine_busy = { m_nom: [False] * 1440 for m_nom in machines.keys() }


    for (c_prod, c_heure, c_qte) in existing_cmds:
        try:
            _, details = calculate_order_cost(c_prod, c_heure, c_qte,
                                              df_prices_prefetched=df_prices,
                                              produits_prefetched=produits,
                                              machines_prefetched=machines)
            for step in details:
                m_nom = step["machine"]
                sh, sm = map(int, step["start"].split(':'))
                eh, em = map(int, step["end"].split(':'))
                start_min = sh * 60 + sm
                end_min   = eh * 60 + em
                if m_nom in machine_busy:  # Sécurité : machine connue seulement
                    for i in range(start_min, end_min):
                        if i < 1440:
                            machine_busy[m_nom][i] = True
        except Exception as ex:
            pass  # On ignore les commandes existantes qui buggent

    # 2. CONSTRUCTION DES MINUTES AUTORISEES (uniquement dans les plages sous le seuil)
    ranges_list = get_price_ranges(threshold=thres, df=df_prices)
    if not ranges_list:
        raise Exception(
            f"Aucune plage d'opportunité n'est disponible sous le seuil de {thres} €.\n"
            "L'optimisation a été annulée."
        )

    # Calculer la durée totale du process pour ce produit
    prod_obj = next((p for p in produits if p[1] == nom_produit), None)
    if not prod_obj:
        raise Exception(f"Produit '{nom_produit}' introuvable.")
    import json as _json
    etapes = _json.loads(prod_obj[2])
    duree_totale_min = sum(e['duree'] * qte for e in etapes)

    # Construire un ensemble de minutes de départ autorisées
    # CONTRAINTE : le process ENTIER (debut + durée) doit tenir dans la même plage
    allowed_start_mins = set()
    for r in ranges_list:
        dh, dm = map(int, r['debut'].split(':'))
        fh, fm = map(int, r['fin'].split(':'))
        r_start = dh * 60 + dm
        r_end   = fh * 60 + fm
        if r_end == 0 or r_end <= r_start:  # Minuit du lendemain = 1440 min
            r_end = 1440
        # Le départ max est tel que la fin (depart + durée) ne dépasse pas la fin de plage
        max_start = r_end - duree_totale_min
        for s in range(r_start, max_start + 1, 15):
            if s >= 0:
                allowed_start_mins.add(s)


    # 3. RECHERCHE DU MEILLEUR CRENEAU UNIQUEMENT DANS LES PLAGES AUTORISEES
    for start_min in sorted(allowed_start_mins):
        h = start_min // 60
        m = start_min % 60
        time_str = f"{h:02d}:{m:02d}"
        try:
            cost, details = calculate_order_cost(nom_produit, time_str, qte,
                                            df_prices_prefetched=df_prices,
                                            produits_prefetched=produits,
                                            machines_prefetched=machines)

            # Vérification des collisions avec le planning actuel
            overlap = False
            for step in details:
                m_nom = step["machine"]
                sh, sm = map(int, step["start"].split(':'))
                eh, em = map(int, step["end"].split(':'))
                start_m = sh * 60 + sm
                end_m   = eh * 60 + em
                for i in range(start_m, end_m):
                    if i >= 1440 or machine_busy[m_nom][i]:
                        overlap = True
                        break
                if overlap:
                    break


            if overlap:
                continue  # Ce créneau crée un conflit machine, on le rejette

            if cost < min_cost:
                min_cost  = cost
                best_time = time_str
        except Exception as ex:
            continue  # Créneau invalide (dépasse minuit, etc.)


    if best_time is None:
        raise Exception(
            f"Toutes les plages d'opportunité sous le seuil de {thres} € sont saturées\n"
            "par d'autres commandes en cours. Il n'y a plus de place disponible."
        )

    return best_time, min_cost
