import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import unicodedata
import re
import os
import io
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

def _img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

LOGO_PATH = "data/logo.png"
logo_b64 = _img_to_base64(LOGO_PATH) if os.path.exists(LOGO_PATH) else ""

@st.cache_data(ttl=300)  # refresh elke 5 minuten
def load_csv():
    """Haalt altijd de nieuwste versie op door versienummers af te proberen."""
    base = "https://datawrapper.dwcdn.net/dgT0d"
    # Probeer versies van hoog naar laag
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
    """Geeft lijst van renners die een X (toekomstig) of punten (al gereden) hebben voor de gegeven race."""
    afk = next((k for k, v in RACE_AFKORTINGEN.items() if v == race_name), None)
    if afk is None or afk not in df.columns:
        return []

    col = df[afk]

    def heeft_deelgenomen(val):
        if pd.isna(val) or val == "" or val == 0:
            return False
        if str(val).strip().upper() == "X":
            return True
        try:
            return float(val) > 0  # Punten > 0 = heeft gereden
        except (ValueError, TypeError):
            return False

    riders = df[col.apply(heeft_deelgenomen)]["Renner"].tolist()
    return [pcs_format(r) for r in riders]

def pcs_format(name):
    """Zet ACHTERNAAM Voornaam om naar Voornaam ACHTERNAAM."""
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
    # ✅ Maak het safe voor NaN/None/niet-strings
    if name is None:
        return ""
    # pandas NaN is float en is "not equal to itself"
    try:
        if name != name:  # NaN-check zonder pandas import
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

    # 1. Exacte match
    price_row = df[df["Normalized"] == normalized_input]

    # 2. Alle splits van voornaam/achternaam proberen
    # bv "arnaud de lie" → probeer "de lie arnaud", "lie arnaud de", etc.
    if price_row.empty:
        words = normalized_input.split()
        for i in range(1, len(words)):
            variant = ' '.join(words[i:] + words[:i])
            price_row = df[df["Normalized"] == variant]
            if not price_row.empty:
                break

    # 3. Fuzzy match als laatste redmiddel
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

    /* GROTER logo */
    .wm-floating-logo {{
        position: fixed;
        top: 130px;
        width: 220px;   /* ← was 150px */
        height: auto;
        opacity: 0.95;
        z-index: 9999;
        filter: drop-shadow(0 12px 20px rgba(0,0,0,.30));
        pointer-events: none;
    }}

    .wm-left {{
        left: 40px;
    }}

    .wm-right {{
        right: 40px;
        /* GEEN transform meer → niet gespiegeld */
    }}

    @media (max-width: 1300px) {{
        .wm-floating-logo {{
            display: none;
        }}
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
    ("Omloop Het Nieuwsblad", "2026-02-28 11:15", "World Tour"),
    ("Kuurne-Brussel-Kuurne", "2026-03-01 12:25", "Niet-World Tour"),
    ("GP-Samyn", "2026-03-03 12:35", "Niet-World Tour"),
    ("Strade Bianche", "2026-03-07 11:45", "World Tour"),
    ("Nokere Koerse", "2026-03-18 12:55", "Niet-World Tour"),
    ("Bredene Koksijde Classic", "2026-03-20 12:21", "Niet-World Tour"),
    ("Milano-Sanremo", "2026-03-21 10:00", "Monument"),
    ("Classic Brugge-De Panne", "2026-03-25 11:40", "World Tour"),
    ("E3 Harelbeke", "2026-03-27 12:52", "World Tour"),
    ("Gent-Wevelgem", "2026-03-29 10:00", "World Tour"),
    ("Dwars door Vlaanderen", "2026-04-01 12:09", "World Tour"),
    ("Ronde van Vlaanderen", "2026-04-05 10:00", "Monument"),
    ("Scheldeprijs", "2026-04-08 13:08", "Niet-World Tour"),
    ("Paris-Roubaix", "2026-04-12 10:00", "Monument"),
    ("Ronde van Limburg", "2026-04-15 13:15", "Niet-World Tour"),
    ("Brabantse Pijl", "2026-04-17 13:32", "Niet-World Tour"),
    ("Amstel Gold Race", "2026-04-19 10:00", "World Tour"),
    ("La Fleche Wallone", "2026-04-22 10:00", "World Tour"),
    ("Liège-Bastogne-Liège", "2026-04-26 10:00", "Monument")
]

# ── CSV laden ─────────────────────────────────────────────────────────────────
df_csv = load_csv()

# ── Renners laden bij opstarten uit CSV ───────────────────────────────────────
if "all_riders" not in st.session_state:
    if not df_csv.empty:
        st.session_state.all_riders = sorted([x for x in [pcs_format(r) for r in df_csv["Renner"].dropna().tolist()] if x and not x[0].isdigit()])
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
            # Match geselecteerde renners met startlijst via fuzzy matching
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

        results.append({"Wedstrijd": race_name, "Datum": race_date, "Categorie": category, "Aantal renners": str(renners_count)})

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

# ── Streamlit UI ──────────────────────────────────────────────────────────────
st.title("🚴 Wielermanager Tools")

if "search_button" not in st.session_state:
    st.session_state.search_button = False
if "selected_riders" not in st.session_state:
    st.session_state.selected_riders = []


st.subheader("📋 Snel jouw team invoeren")
st.caption("💡 Tip: ga naar 'Mijn ploeg' → 'Mijn renners' op de wielermanager-site, selecteer alles en plak het hieronder. Ploegnamen, prijzen en andere tekst worden automatisch genegeerd.")
rider_input = st.text_area(
    "Plak of typ rennersnamen (gescheiden door komma's of nieuwe regels):",
    placeholder="bv: Wout Van Aert, Van Der Poel, Pogacar...",
    height=200,
)

def extract_riders_from_paste(text: str, all_riders: list) -> tuple[list, list]:
    """
    Haalt rennersnamen uit ruwe geplakte tekst.
    Negeert ploegnamen, prijzen (€14M), lege regels en andere rommel.
    """
    kandidaten = re.split(r'[,\n]', text)
    kandidaten = [k.strip() for k in kandidaten if k.strip()]

    def is_likely_rider(s: str) -> bool:
        if re.match(r'^€', s):
            return False
        if re.match(r'^\d+[\./,]?\d*$', s):
            return False
        if len(s) < 4 or len(s) > 40:
            return False
        team_woorden = [
            "team", "cycling", "intermarché", "intermarche", "premier tech",
            "emirates", "groupama", "deceuninck", "quickstep", "quick-step",
            "soudal", "bahrain", "victorious", "ineos", "grenadiers", "visma",
            "lease", "bike", "alpecin", "uno-x", "lidl", "trek", "cofidis",
            "bora", "hansgrohe", "jayco", "alula", "movistar", "tudor",
            "astana", "arkéa", "arkea", "lotto", "red bull", "dsm",
            "firmenich", "picnic", "postnl", "pol", "rockets", "unibet",
            "xds", "tarteletto", "bingoal", "flanders", "tomorrow", "q36",
            "novo nordisk", "nsn", "xrg",
            # UI-tekst van de wielermanager-site
            "budget", "beheer", "ploeg", "opstelling", "renners", "resterend",
            "geselecteerde", "minicompetitie", "transfers", "klassement",
            "statistieken", "spelregels", "prijzen", "overzicht",
        ]
        s_lower = s.lower()
        if any(tw in s_lower for tw in team_woorden):
            return False
        if ' – ' in s or ' - ' in s:
            return False
        return True

    kandidaten_gefilterd = [k for k in kandidaten if is_likely_rider(k)]

    normalized_riders = {rider: normalize_name(rider) for rider in all_riders}

    def find_best_match_strict(input_name):
        norm_input = normalize_name(input_name)
        input_words = norm_input.split()
        input_first_letter = input_words[0][0] if input_words else ""

        # 1. Exacte match
        for original, norm in normalized_riders.items():
            if norm == norm_input:
                return original

        # 2. Omgekeerde volgorde exacte match
        words = norm_input.split()
        reversed_input = ' '.join(reversed(words)) if len(words) >= 2 else None
        if reversed_input:
            for original, norm in normalized_riders.items():
                if norm == reversed_input:
                    return original

        # 3. Fuzzy match: drempel 85 + achternaam moet exact matchen + eerste letter voornaam klopt
        match1 = process.extractOne(norm_input, list(normalized_riders.values()))
        match2 = process.extractOne(reversed_input, list(normalized_riders.values())) if reversed_input else None
        if match1 and match2:
            best = match1 if match1[1] >= match2[1] else match2
        else:
            best = match1 or match2

        if best and best[1] >= 85:
            match_words = best[0].split()
            # Achternaam = laatste woord — moet exact overeenkomen
            input_lastname = input_words[-1] if input_words else ""
            match_lastname = match_words[-1] if match_words else ""
            if input_lastname != match_lastname:
                return None
            # Eerste letter van voornaam moet kloppen (vangt "Tom" vs "Thomas")
            match_first_letter = match_words[0][0] if match_words else ""
            if input_first_letter and match_first_letter and input_first_letter != match_first_letter:
                return None
            for original, norm in normalized_riders.items():
                if norm == best[0]:
                    return original
        return None

    matched = []
    al_gevonden = set()

    for kandidaat in kandidaten_gefilterd:
        match = find_best_match_strict(kandidaat)
        if match and match not in al_gevonden:
            matched.append(match)
            al_gevonden.add(match)

    return matched, []

if st.button("✅ Voeg toe"):
    if rider_input:
        matched_riders, niet_gevonden = extract_riders_from_paste(
            rider_input, st.session_state.all_riders
        )
        if matched_riders:
            st.session_state.selected_riders = matched_riders
            st.success(f"✅ {len(matched_riders)} renners herkend en toegevoegd!")
        if niet_gevonden:
            st.warning(f"⚠️ Niet herkend (genegeerd): {', '.join(niet_gevonden)}")
        if len(matched_riders) != 20:
            st.warning(f"⚠️ Let op! Je hebt {len(matched_riders)} renners (verwacht: 20).")

st.subheader("📋 Selecteer je team")
selected_riders = st.multiselect(
    "Kies jouw renners:", st.session_state.all_riders,
    default=st.session_state.get("selected_riders", [])
)

if st.button("🔍 Zoeken"):
    st.session_state.search_button = True
    if len(selected_riders) != 20:
        st.warning(f"⚠️ Let op! Je hebt {len(selected_riders)} renners geselecteerd (verwacht: 20).")

if st.session_state.search_button and selected_riders:
    with st.spinner("Bezig met ophalen van data..."):
        results, rider_participation, rider_schedule, recommended_transfers = fetch_data(selected_riders)

    df = pd.DataFrame(results)
    df.index = df.index + 1
    st.dataframe(df.drop(columns=["Datum"]))

    st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
    schedule_with_prices = add_prices_to_schedule(rider_schedule)
    schedule_df = pd.DataFrame.from_dict(schedule_with_prices, orient="index")
    # Sorteer op prijs (hoog naar laag), prijs staat tussen haakjes bv " (14M)"
    def extract_price(name):
        import re
        m = re.search(r"\((\d+)M\)", name)
        return int(m.group(1)) if m else 0
    schedule_df = schedule_df.iloc[sorted(range(len(schedule_df)), key=lambda i: extract_price(schedule_df.index[i]), reverse=True)]
    st.dataframe(schedule_df)

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
