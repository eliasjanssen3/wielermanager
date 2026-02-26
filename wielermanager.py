import streamlit as st
import pandas as pd
import unicodedata
import re
import os
import io
import random
import requests as req
from rapidfuzz import process
from datetime import datetime
import pytz
import base64

# ── Prijzen en programma's laden uit Datawrapper CSV ─────────────────────────
DATAWRAPPER_URL = "https://datawrapper.dwcdn.net/dgT0d/10/dataset.csv"

# Race afkortingen in CSV → volledige namen
RACE_AFKORTINGEN = {
    "OML": "Omloop Het Nieuwsblad",
    "KBK": "Kuurne-Brussel-Kuurne",
    "SAM": "GP-Samyn",
    "STR": "Strade Bianche",
    "NOK": "Nokere Koerse",
    "BKC": "Bredene Koksijde Classic",
    "MSR": "Milano-Sanremo",
    "RVB": "Classic Brugge-De Panne",
    "E3":  "E3 Harelbeke",
    "IFF": "Gent-Wevelgem",
    "DDV": "Dwars door Vlaanderen",
    "RVV": "Ronde van Vlaanderen",
    "SP":  "Scheldeprijs",
    "PR":  "Paris-Roubaix",
    "RVL": "Ronde van Limburg",
    "BR P":"Brabantse Pijl",
    "AGR": "Amstel Gold Race",
    "WA P":"La Fleche Wallone",
    "LBL": "Liège-Bastogne-Liège",
}

# ── Puntentabel per categorie ─────────────────────────────────────────────────
POINTS = {
    "Monument": {
        1:125,2:100,3:80,4:70,5:60,6:55,7:50,8:45,9:40,10:37,
        11:34,12:31,13:28,14:25,15:22,16:20,17:18,18:16,19:14,20:12,
        21:10,22:9,23:8,24:7,25:6,26:5,27:4,28:3,29:2,30:1
    },
    "World Tour": {
        1:100,2:80,3:65,4:55,5:48,6:44,7:40,8:36,9:32,10:30,
        11:27,12:24,13:22,14:20,15:18,16:16,17:14,18:12,19:10,20:9,
        21:8,22:7,23:6,24:5,25:4,26:3,27:2,28:2,29:1,30:1
    },
    "Niet-World Tour": {
        1:80,2:64,3:52,4:44,5:38,6:35,7:32,8:29,9:26,10:24,
        11:22,12:20,13:18,14:16,15:14,16:12,17:11,18:10,19:9,20:8,
        21:7,22:6,23:5,24:4,25:3,26:3,27:2,28:2,29:1,30:1
    },
}
TEAMGENOOT_BONUS = 10

# ── Unibet/Kambi event IDs per koers ─────────────────────────────────────────
# Vul hier de Unibet event URL ID in zodra beschikbaar (staat in de URL)
# bv: https://nl.unibetsports.be/betting/sports/event/1026768874 → ID = 1026768874
UNIBET_EVENT_IDS = {
    "Omloop Het Nieuwsblad": 1026768874,
    "Kuurne-Brussel-Kuurne": None,   # Vul in zodra beschikbaar
    "GP-Samyn": None,
    "Strade Bianche": None,
    "Nokere Koerse": None,
    "Bredene Koksijde Classic": None,
    "Milano-Sanremo": None,
    "Classic Brugge-De Panne": None,
    "E3 Harelbeke": None,
    "Gent-Wevelgem": None,
    "Dwars door Vlaanderen": None,
    "Ronde van Vlaanderen": None,
    "Scheldeprijs": None,
    "Paris-Roubaix": None,
    "Ronde van Limburg": None,
    "Brabantse Pijl": None,
    "Amstel Gold Race": None,
    "La Fleche Wallone": None,
    "Liège-Bastogne-Liège": None,
}

# ── Kambi API scraper ─────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_unibet_odds(event_id: int) -> dict:
    """
    Haalt odds op via de Kambi API (Unibet's sportsbook provider).
    Probeert meerdere URL-varianten. Geeft dict terug: {renner_naam: decimal_odds}
    """
    urls_to_try = [
        f"https://eu-offering-api.kambicdn.com/offering/v2018/unibet_belgium/betoffer/event/{event_id}.json?lang=nl_BE&market=BE",
        f"https://eu-offering-api.kambicdn.com/offering/v2018/unibet_belgium/betoffer/event/{event_id}.json",
        f"https://offering-api.kambicdn.com/offering/v2018/unibet_belgium/betoffer/event/{event_id}.json?lang=nl_BE&market=BE",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": f"https://nl.unibetsports.be/betting/sports/event/{event_id}",
        "Origin": "https://nl.unibetsports.be",
    }

    data = None
    for url in urls_to_try:
        try:
            r = req.get(url, timeout=8, headers=headers)
            if r.status_code == 200:
                data = r.json()
                break
        except Exception:
            continue

    if not data:
        return {}

    odds = {}
    betoffers = data.get("betOffers", [])

    for betoffer in betoffers:
        criterion = betoffer.get("criterion", {})
        label = criterion.get("label", "").lower()
        criterion_id = criterion.get("id", 0)

        # Accepteer alle mogelijke winnaar-markten
        is_winner_market = (
            "winner" in label
            or "winnaar" in label
            or "to win" in label
            or criterion_id in (1001159179, 1001159185, 1001159200)  # bekende Kambi outright IDs
        )

        if not is_winner_market:
            continue

        for outcome in betoffer.get("outcomes", []):
            name = outcome.get("label", "").strip()
            odds_val = outcome.get("odds", 0)
            # Kambi: odds 190 = 1.90, 1100 = 11.00
            if odds_val and name and odds_val > 100:
                odds[name] = odds_val / 100

    # Fallback: als geen winnaar-markt gevonden, pak grootste betoffer
    if not odds and betoffers:
        biggest = max(betoffers, key=lambda b: len(b.get("outcomes", [])), default=None)
        if biggest:
            for outcome in biggest.get("outcomes", []):
                name = outcome.get("label", "").strip()
                odds_val = outcome.get("odds", 0)
                if odds_val and name and odds_val > 100:
                    odds[name] = odds_val / 100

    return odds


def debug_unibet_api(event_id: int):
    """Toont ruwe API-response voor debugging in Streamlit."""
    url = (
        f"https://eu-offering-api.kambicdn.com/offering/v2018/unibet_belgium"
        f"/betoffer/event/{event_id}.json?lang=nl_BE&market=BE"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": f"https://nl.unibetsports.be/betting/sports/event/{event_id}",
    }
    try:
        r = req.get(url, timeout=8, headers=headers)
        st.write(f"**Status:** {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            betoffers = data.get("betOffers", [])
            st.write(f"**Aantal betOffers:** {len(betoffers)}")
            for i, bo in enumerate(betoffers[:5]):
                st.write(f"BetOffer {i}: label=`{bo.get('criterion',{}).get('label')}`, "
                         f"id=`{bo.get('criterion',{}).get('id')}`, "
                         f"outcomes={len(bo.get('outcomes',[]))}")
                if bo.get("outcomes"):
                    first = bo["outcomes"][0]
                    st.write(f"  → Eerste outcome: `{first.get('label')}` odds=`{first.get('odds')}`")
        else:
            st.write(f"Response: {r.text[:500]}")
    except Exception as e:
        st.error(f"Fout: {e}")

# ── Monte Carlo EP berekening ─────────────────────────────────────────────────
def bereken_expected_points(odds_dict: dict, category: str, rider_teams: dict,
                             selected_riders: list, n_sim: int = 50000) -> dict:
    """
    Berekent expected points via Plackett-Luce Monte Carlo simulatie.
    - odds_dict: {renner: decimal_odds}
    - category: 'Monument', 'World Tour' of 'Niet-World Tour'
    - rider_teams: {renner: team_afkorting} voor alle renners in het veld
    - selected_riders: jouw wielermanager-ploeg (voor teamgenoot-bonus)
    - Geeft {renner: expected_points} terug
    """
    if not odds_dict:
        return {}

    points_table = POINTS.get(category, POINTS["World Tour"])
    riders = list(odds_dict.keys())

    # Normaliseer kansen (verwijder bookmaker marge)
    raw = {r: 1 / odds_dict[r] for r in riders}
    total = sum(raw.values())
    win_probs = {r: p / total for r, p in raw.items()}

    probs_list = [win_probs[r] for r in riders]
    ep_totals = {r: 0.0 for r in riders}

    # Maak lookup: renner → team (genormaliseerde naam)
    norm_selected = {normalize_name(r): r for r in selected_riders}

    random.seed(42)
    for _ in range(n_sim):
        remaining_riders = riders[:]
        remaining_probs = probs_list[:]
        race_points = {r: 0.0 for r in riders}
        winner = None
        winner_team = None

        for pos in range(1, 31):
            if not remaining_riders:
                break
            total_w = sum(remaining_probs)
            norm_p = [w / total_w for w in remaining_probs]

            # Trek renner via gewogen random
            rand = random.random()
            cumsum = 0.0
            chosen_idx = 0
            for i, p in enumerate(norm_p):
                cumsum += p
                if rand <= cumsum:
                    chosen_idx = i
                    break

            chosen = remaining_riders[chosen_idx]
            pts = points_table.get(pos, 0)
            race_points[chosen] = pts

            if pos == 1:
                winner = chosen
                winner_team = rider_teams.get(normalize_name(chosen))

            # Verwijder gekozen renner voor volgende positie
            remaining_riders.pop(chosen_idx)
            remaining_probs.pop(chosen_idx)

        # Teamgenoot bonus: +10 voor jouw geselecteerde renners
        # waarvan een ploegmaat gewonnen heeft
        if winner and winner_team:
            for r in riders:
                if r == winner:
                    continue
                r_team = rider_teams.get(normalize_name(r))
                if r_team and r_team == winner_team:
                    # Alleen bonus als deze renner in jouw wielermanager-ploeg zit
                    if normalize_name(r) in norm_selected:
                        race_points[r] += TEAMGENOOT_BONUS

        for r in riders:
            ep_totals[r] += race_points[r]

    return {r: ep_totals[r] / n_sim for r in riders}

# ── EP ophalen voor een koers (gecached) ──────────────────────────────────────
@st.cache_data(ttl=300)
def get_ep_for_race(race_name: str, category: str, selected_riders_tuple: tuple) -> dict:
    """
    Haalt odds op en berekent EP. Gecached voor 5 minuten.
    selected_riders_tuple: tuple van geselecteerde renners (voor cache-key)
    """
    event_id = UNIBET_EVENT_IDS.get(race_name)
    if not event_id:
        return {}  # Geen event ID bekend voor deze koers

    odds = fetch_unibet_odds(event_id)
    if not odds:
        return {}

    # Haal team-info op uit CSV
    rider_teams = get_rider_teams_from_csv()

    return bereken_expected_points(
        odds_dict=odds,
        category=category,
        rider_teams=rider_teams,
        selected_riders=list(selected_riders_tuple),
    )

@st.cache_data(ttl=300)
def get_rider_teams_from_csv() -> dict:
    """Geeft {normalize_name(renner): team_afkorting} voor alle renners in CSV."""
    if df_csv.empty:
        return {}
    result = {}
    for _, row in df_csv.iterrows():
        naam = row.get("Renner", "")
        team = row.get("T", "")
        if naam and team:
            result[normalize_name(pcs_format(str(naam)))] = str(team)
    return result

# ── Logo ──────────────────────────────────────────────────────────────────────
def _img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

LOGO_PATH = "data/logo.png"
logo_b64 = _img_to_base64(LOGO_PATH) if os.path.exists(LOGO_PATH) else ""

# ── CSV laden ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_csv():
    base = "https://datawrapper.dwcdn.net/dgT0d"
    for version in range(40, 0, -1):
        url = f"{base}/{version}/dataset.csv"
        try:
            r = req.get(url, timeout=5)
            if r.status_code == 200:
                df = pd.read_csv(io.StringIO(r.text))
                if not df.empty:
                    return df
        except Exception:
            continue
    st.warning("⚠️ Kon CSV niet ophalen.")
    return pd.DataFrame()

def get_startlist_from_csv(race_name, df):
    afk = next((k for k, v in RACE_AFKORTINGEN.items() if v == race_name), None)
    if afk is None or afk not in df.columns:
        return []
    riders = df[df[afk] == "X"]["Renner"].tolist()
    return [pcs_format(r) for r in riders]

def pcs_format(name):
    if not isinstance(name, str) or not name.strip():
        return ""
    parts = name.strip().split()
    for i, part in enumerate(parts):
        if not part.isupper():
            return ' '.join(parts[i:] + parts[:i])
    if len(parts) >= 2:
        return ' '.join(parts[1:] + [parts[0].capitalize()])
    return name

# ── Naam normalisatie ─────────────────────────────────────────────────────────
def normalize_name(name):
    if name is None:
        return ""
    try:
        if name != name:
            return ""
    except Exception:
        pass
    if not isinstance(name, str):
        name = str(name)
    replacements = {
        "Æ": "AE", "æ": "ae", "Ø": "O", "ø": "o",
        "Å": "A", "å": "a", "Č": "C", "č": "c",
        "Š": "S", "š": "s", "Đ": "D", "đ": "d",
        "Ž": "Z", "ž": "z", "Ć": "C", "ć": "c"
    }
    for special, replacement in replacements.items():
        name = name.replace(special, replacement)
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    name = re.sub(r'[^a-zA-Z\s-]', '', name)
    return name.strip().lower()

def find_best_match(input_name, all_riders):
    if not all_riders:
        return None
    normalized_input = normalize_name(input_name)
    normalized_riders = {rider: normalize_name(rider) for rider in all_riders}
    for original, norm in normalized_riders.items():
        if norm == normalized_input:
            return original
    words = normalized_input.split()
    reversed_input = ' '.join(reversed(words)) if len(words) >= 2 else None
    if reversed_input:
        for original, norm in normalized_riders.items():
            if norm == reversed_input:
                return original
    match1 = process.extractOne(normalized_input, list(normalized_riders.values()))
    match2 = process.extractOne(reversed_input, list(normalized_riders.values())) if reversed_input else None
    if match1 and match2:
        best = match1 if match1[1] >= match2[1] else match2
    else:
        best = match1 or match2
    if best and best[1] > 75:
        for original, norm in normalized_riders.items():
            if norm == best[0]:
                return original
    return None

def get_rider_price(rider_name):
    if df_csv.empty:
        return ""
    normalized_input = normalize_name(rider_name)
    df = df_csv.copy()
    df["Normalized"] = df["Renner"].apply(normalize_name)
    price_row = df[df["Normalized"] == normalized_input]
    if price_row.empty:
        words = normalized_input.split()
        for i in range(1, len(words)):
            variant = ' '.join(words[i:] + words[:i])
            price_row = df[df["Normalized"] == variant]
            if not price_row.empty:
                break
    if price_row.empty:
        match_result = process.extractOne(normalized_input, df["Normalized"].tolist())
        if match_result and match_result[1] > 80:
            price_row = df[df["Normalized"] == match_result[0]]
    if not price_row.empty and "€" in price_row.columns:
        try:
            return f" ({int(price_row.iloc[0]['€'])}M)"
        except:
            return ""
    return ""

# ── Achtergrond ───────────────────────────────────────────────────────────────
def set_background():
    st.markdown(
    f"""
    <style>
    .stApp{{
        background: radial-gradient(circle at center,
            rgba(190, 235, 245, 1) 0%,
            rgba(140, 205, 225, 1) 35%,
            rgba(80, 165, 200, 1) 65%,
            rgba(45, 135, 185, 1) 100%);
        background-attachment: fixed;
    }}
    .wm-floating-logo {{
        position: fixed;
        top: 130px;
        width: 220px;
        height: auto;
        opacity: 0.95;
        z-index: 9999;
        filter: drop-shadow(0 12px 20px rgba(0,0,0,.30));
        pointer-events: none;
    }}
    .wm-left {{ left: 40px; }}
    .wm-right {{ right: 40px; }}
    @media (max-width: 1300px) {{
        .wm-floating-logo {{ display: none; }}
    }}
    </style>
    <img class="wm-floating-logo wm-left" src="data:image/png;base64,{logo_b64}" />
    <img class="wm-floating-logo wm-right" src="data:image/png;base64,{logo_b64}" />
    """,
    unsafe_allow_html=True
)

set_background()

# ── Wedstrijden ───────────────────────────────────────────────────────────────
races = [
    ("Omloop Het Nieuwsblad",   "2026-02-28 11:30", "World Tour"),
    ("Kuurne-Brussel-Kuurne",   "2026-03-01 12:14", "Niet-World Tour"),
    ("GP-Samyn",                "2026-03-03 12:35", "Niet-World Tour"),
    ("Strade Bianche",          "2026-03-07 11:25", "World Tour"),
    ("Nokere Koerse",           "2026-03-18 12:55", "Niet-World Tour"),
    ("Bredene Koksijde Classic","2026-03-20 12:22", "Niet-World Tour"),
    ("Milano-Sanremo",          "2026-03-21 10:25", "Monument"),
    ("Classic Brugge-De Panne","2026-03-25 12:50", "World Tour"),
    ("E3 Harelbeke",            "2026-03-27 12:52", "World Tour"),
    ("Gent-Wevelgem",           "2026-03-29 10:50", "World Tour"),
    ("Dwars door Vlaanderen",   "2026-04-01 12:40", "World Tour"),
    ("Ronde van Vlaanderen",    "2026-04-05 10:17", "Monument"),
    ("Scheldeprijs",            "2026-04-08 13:09", "Niet-World Tour"),
    ("Paris-Roubaix",           "2026-04-12 14:00", "Monument"),
    ("Ronde van Limburg",       "2026-04-15 13:15", "Niet-World Tour"),
    ("Brabantse Pijl",          "2026-04-17 13:12", "Niet-World Tour"),
    ("Amstel Gold Race",        "2026-04-19 10:43", "World Tour"),
    ("La Fleche Wallone",       "2026-04-22 14:00", "World Tour"),
    ("Liège-Bastogne-Liège",    "2026-04-26 14:00", "Monument"),
]

# ── CSV laden ─────────────────────────────────────────────────────────────────
df_csv = load_csv()

if "all_riders" not in st.session_state:
    if not df_csv.empty:
        st.session_state.all_riders = sorted([
            x for x in [pcs_format(r) for r in df_csv["Renner"].dropna().tolist()]
            if x and not x[0].isdigit()
        ])
    else:
        st.session_state.all_riders = []

# ── Helpers ───────────────────────────────────────────────────────────────────
def add_prices_to_schedule(schedule):
    return {rider + get_rider_price(rider): rs for rider, rs in schedule.items()}

def add_prices_to_recommended_transfers(recommended_transfers):
    df = pd.DataFrame(
        sorted(recommended_transfers.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal wedstrijden met laag aantal deelnemers"]
    )
    df["Renner"] = df["Renner"].apply(lambda r: r + get_rider_price(r))
    return df

def add_prices_to_rider_participation(rider_participation):
    df = pd.DataFrame(
        sorted(rider_participation.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal deelnames"]
    )
    df["Renner"] = df["Renner"].apply(lambda r: r + get_rider_price(r))
    return df

def fetch_data(selected_riders):
    results = []
    rider_participation = {rider: 0 for rider in selected_riders}
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    weak_races = {}
    now = datetime.now()

    for race_name, race_date, category in races:
        race_datetime = datetime.strptime(race_date, "%Y-%m-%d %H:%M")
        startlist = get_startlist_from_csv(race_name, df_csv)
        if not startlist:
            renners_count = "⚠️ Geen data"
            team_riders = []
        else:
            team_riders = []
            for selected in selected_riders:
                norm_selected = normalize_name(selected)
                for starter in startlist:
                    if normalize_name(starter) == norm_selected:
                        team_riders.append(selected)
                        break
            renners_count = len(team_riders)
            for rider in team_riders:
                rider_participation[rider] += 1
                rider_schedule[rider][race_name] = "✅"
            if race_datetime > now and renners_count <= 9:
                weak_races[race_name] = startlist

        results.append({
            "Wedstrijd": race_name,
            "Datum": race_date,
            "Categorie": category,
            "Aantal renners": str(renners_count)
        })

    recommended_transfers = {}
    for race, race_riders in weak_races.items():
        for rider in race_riders:
            if rider not in selected_riders:
                recommended_transfers[rider] = recommended_transfers.get(rider, 0) + 1

    return results, rider_participation, rider_schedule, recommended_transfers

def fetch_rider_schedule(selected_riders):
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    for race_name, _, _ in races:
        startlist = get_startlist_from_csv(race_name, df_csv)
        for rider in selected_riders:
            norm = normalize_name(rider)
            for starter in startlist:
                if normalize_name(starter) == norm:
                    rider_schedule[rider][race_name] = "✅"
                    break
    return rider_schedule

def get_next_race():
    now = datetime.now()
    for race_name, race_datetime, _ in races:
        if datetime.strptime(race_datetime, "%Y-%m-%d %H:%M") > now:
            return race_name
    return races[-1][0]

def countdown_to_next_race():
    cet = pytz.timezone("Europe/Brussels")
    now = datetime.now(pytz.utc).astimezone(cet)
    for race_name, race_datetime, _ in races:
        race_time = cet.localize(datetime.strptime(race_datetime, "%Y-%m-%d %H:%M"))
        if race_time > now:
            countdown = race_time - now
            days = countdown.days
            hours, remainder = divmod(countdown.seconds, 3600)
            minutes = remainder // 60
            return race_name, days, hours, minutes
    return None, None, None, None

def match_odds_naam_naar_csv(odds_naam: str, csv_riders: list) -> str | None:
    """Matcht een naam uit de Kambi/Unibet odds naar de naam in de CSV via fuzzy matching."""
    norm = normalize_name(odds_naam)
    for csv_rider in csv_riders:
        if normalize_name(csv_rider) == norm:
            return csv_rider
    # Probeer omgekeerde volgorde
    words = norm.split()
    if len(words) >= 2:
        reversed_n = ' '.join(reversed(words))
        for csv_rider in csv_riders:
            if normalize_name(csv_rider) == reversed_n:
                return csv_rider
    # Fuzzy fallback
    match = process.extractOne(norm, [normalize_name(r) for r in csv_riders])
    if match and match[1] > 80:
        norm_match = match[0]
        for csv_rider in csv_riders:
            if normalize_name(csv_rider) == norm_match:
                return csv_rider
    return None

# ── Streamlit UI ──────────────────────────────────────────────────────────────
st.title("🚴 Wielermanager Tools")

if "search_button" not in st.session_state:
    st.session_state.search_button = False
if "selected_riders" not in st.session_state:
    st.session_state.selected_riders = []

st.subheader("📋 Snel jouw team invoeren")
rider_input = st.text_area(
    "Plak of typ rennersnamen, gescheiden door komma's of nieuwe regels:",
    placeholder="bv: wout van aert, van der poel, pogacar..."
)

if st.button("✅ Voeg toe"):
    if rider_input:
        input_riders = re.split(r'[,\n]', rider_input)
        input_riders = [r.strip() for r in input_riders if r.strip()]
        matched_riders = []
        niet_gevonden = []
        for rider in input_riders:
            match = find_best_match(rider, st.session_state.all_riders)
            if match:
                matched_riders.append(match)
            else:
                niet_gevonden.append(rider)
        if matched_riders:
            st.session_state.selected_riders = matched_riders
            st.success(f"✅ {len(matched_riders)} renners toegevoegd!")
        if niet_gevonden:
            st.warning(f"⚠️ Niet gevonden: {', '.join(niet_gevonden)}")
        if len(matched_riders) != 20:
            st.warning(f"⚠️ Let op! Je hebt {len(matched_riders)} renners geselecteerd (verwacht: 20).")

st.subheader("📋 Selecteer je team")
selected_riders = st.multiselect(
    "Kies jouw renners:", st.session_state.all_riders,
    default=st.session_state.get("selected_riders", [])
)

if st.button("🔍 Zoeken"):
    st.session_state.search_button = True

if st.session_state.search_button and selected_riders:
    with st.spinner("Bezig met ophalen van data..."):
        results, rider_participation, rider_schedule, recommended_transfers = fetch_data(selected_riders)

    df = pd.DataFrame(results)
    df.index = df.index + 1
    st.dataframe(df.drop(columns=["Datum"]))

    st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
    schedule_with_prices = add_prices_to_schedule(rider_schedule)
    schedule_df = pd.DataFrame.from_dict(schedule_with_prices, orient="index")
    def extract_price(name):
        m = re.search(r"\((\d+)M\)", name)
        return int(m.group(1)) if m else 0
    schedule_df = schedule_df.iloc[
        sorted(range(len(schedule_df)), key=lambda i: extract_price(schedule_df.index[i]), reverse=True)
    ]
    st.dataframe(schedule_df)

    # ── Expected Points sectie ────────────────────────────────────────────────
    st.markdown("---")
    st.header("🎯 Expected Points")

    races_with_ep = [(name, cat) for name, _, cat in races if UNIBET_EVENT_IDS.get(name)]
    races_without_ep = [name for name, _, _ in races if not UNIBET_EVENT_IDS.get(name)]

    if not races_with_ep:
        st.info("ℹ️ Nog geen Unibet event IDs ingevuld. Voeg ze toe in UNIBET_EVENT_IDS bovenaan de code.")
    else:
        # Debug tool
        with st.expander("🔧 Debug: API response bekijken"):
            debug_race = st.selectbox("Koers voor debug:", [r for r, _ in races_with_ep], key="debug_race")
            if st.button("🔍 Toon ruwe API response"):
                debug_event_id = UNIBET_EVENT_IDS.get(debug_race)
                if debug_event_id:
                    debug_unibet_api(debug_event_id)
        if races_without_ep:
            st.caption(f"⚠️ Geen odds beschikbaar voor: {', '.join(races_without_ep)}")

        # ── 1. Overzichtstabel: totale EP per koers voor jouw ploeg ──────────
        st.subheader("📊 Totale Expected Points per koers")

        ep_overzicht = []
        all_ep_per_race = {}  # sla op voor hergebruik hieronder

        with st.spinner("Odds ophalen en EP berekenen... (kan even duren)"):
            for race_name, category in races_with_ep:
                ep_dict = get_ep_for_race(
                    race_name, category, tuple(selected_riders)
                )
                all_ep_per_race[race_name] = ep_dict

                if not ep_dict:
                    ep_overzicht.append({
                        "Koers": race_name,
                        "Categorie": category,
                        "Totale EP jouw ploeg": "⚠️ Geen odds",
                    })
                    continue

                # Match geselecteerde renners met odds-namen
                startlist_csv = get_startlist_from_csv(race_name, df_csv)
                totaal_ep = 0.0
                for selected in selected_riders:
                    # Probeer directe match met odds-namen
                    best_odds_naam = match_odds_naam_naar_csv(selected, list(ep_dict.keys()))
                    if best_odds_naam and best_odds_naam in ep_dict:
                        totaal_ep += ep_dict[best_odds_naam]

                ep_overzicht.append({
                    "Koers": race_name,
                    "Categorie": category,
                    "Totale EP jouw ploeg": round(totaal_ep, 2),
                })

        ep_overzicht_df = pd.DataFrame(ep_overzicht)
        st.dataframe(ep_overzicht_df, use_container_width=True)

        # ── 2. Dropdown: EP per renner per koers ─────────────────────────────
        st.subheader("🏁 Expected Points per renner per koers")

        koers_keuze = st.selectbox(
            "Selecteer een koers:",
            [r for r, _ in races_with_ep],
            key="ep_koers_dropdown"
        )

        if koers_keuze:
            ep_dict = all_ep_per_race.get(koers_keuze, {})
            category = next(cat for name, cat in races_with_ep if name == koers_keuze)

            if not ep_dict:
                st.warning("⚠️ Geen odds beschikbaar voor deze koers.")
            else:
                startlist_csv = get_startlist_from_csv(koers_keuze, df_csv)

                # Jouw renners met EP
                st.markdown("**Jouw ploeg:**")
                jouw_ep_rows = []
                for selected in selected_riders:
                    best_odds_naam = match_odds_naam_naar_csv(selected, list(ep_dict.keys()))
                    ep_val = ep_dict.get(best_odds_naam, 0.0) if best_odds_naam else 0.0
                    in_startlijst = any(normalize_name(selected) == normalize_name(s) for s in startlist_csv)
                    jouw_ep_rows.append({
                        "Renner": selected + get_rider_price(selected),
                        "Start": "✅" if in_startlijst else "❌",
                        "Expected Points": round(ep_val, 2) if in_startlijst else 0.0,
                    })

                jouw_ep_df = pd.DataFrame(jouw_ep_rows).sort_values("Expected Points", ascending=False)
                st.dataframe(jouw_ep_df, use_container_width=True)

                # ── 3. Renners die jij NIET hebt, gesorteerd op EP ───────────
                st.markdown("**Renners die jij niet hebt (gesorteerd op EP):**")
                selected_norm = {normalize_name(r) for r in selected_riders}

                niet_jouw_rows = []
                for odds_naam, ep_val in ep_dict.items():
                    # Sla over als dit een van jouw renners is
                    if normalize_name(odds_naam) in selected_norm:
                        continue
                    # Controleer ook via match
                    csv_match = match_odds_naam_naar_csv(odds_naam, st.session_state.all_riders)
                    if csv_match and normalize_name(csv_match) in selected_norm:
                        continue

                    display_naam = csv_match if csv_match else odds_naam
                    prijs = get_rider_price(display_naam) if csv_match else ""
                    in_startlijst = any(
                        normalize_name(odds_naam) == normalize_name(s) for s in startlist_csv
                    )

                    niet_jouw_rows.append({
                        "Renner": display_naam + prijs,
                        "Expected Points": round(ep_val, 2),
                    })

                niet_jouw_df = (
                    pd.DataFrame(niet_jouw_rows)
                    .sort_values("Expected Points", ascending=False)
                    .reset_index(drop=True)
                )
                niet_jouw_df.index += 1
                st.dataframe(niet_jouw_df, use_container_width=True)

    # ── Vergelijk mogelijke transfers ────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔍 Vergelijk mogelijke transfers")
    available_transfers = [r for r in st.session_state.all_riders if r not in selected_riders]
    transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", available_transfers)
    if transfer_riders:
        with st.spinner("Bezig met ophalen van schema's..."):
            transfer_schedule = fetch_rider_schedule(transfer_riders)
        st.subheader("📅 Wedstrijdschema van mogelijke transfers")
        st.dataframe(pd.DataFrame.from_dict(add_prices_to_schedule(transfer_schedule), orient="index").sort_index())

    st.subheader("🔄 Voorgestelde transfers voor zwak bezette toekomstige wedstrijden")
    st.dataframe(add_prices_to_recommended_transfers(recommended_transfers).set_index("Renner"))

    st.subheader("🏁 Jouw startlijst per wedstrijd")
    next_race = get_next_race()
    wedstrijd_optie = st.selectbox(
        "Selecteer een wedstrijd:",
        [race[0] for race in races],
        index=[race[0] for race in races].index(next_race)
    )
    if wedstrijd_optie:
        startlist = get_startlist_from_csv(wedstrijd_optie, df_csv)
        team_riders = [r for r in selected_riders if any(normalize_name(r) == normalize_name(s) for s in startlist)]
        st.subheader(f"🏁 Jouw renners in {wedstrijd_optie}:")
        if team_riders:
            for rider in sorted(team_riders, key=lambda r: " ".join(w for w in r.split() if w.isupper()) or r.split()[-1].lower()):
                st.success(f"✅ **{rider}{get_rider_price(rider)}**")
        else:
            st.warning("🚨 Geen renners van jouw team in deze wedstrijd!")

    st.subheader("📊 Deelnames per renner")
    st.dataframe(add_prices_to_rider_participation(rider_participation).set_index("Renner"))

    next_race, days, hours, minutes = countdown_to_next_race()
    if next_race:
        st.markdown("---")
        st.subheader(f"⏳ Nog **{days} dagen, {hours} uur en {minutes} minuten** tot **{next_race}**!")
