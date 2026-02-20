import streamlit as st
import aiohttp
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
import unicodedata
import re
import io
from rapidfuzz import process
from datetime import datetime
import pytz

# ── Prijzen ophalen van Datawrapper ─────────────────────────────────────────
PRIJZEN_URL = "https://datawrapper.dwcdn.net/dgT0d/7/dataset.csv"

@st.cache_data(ttl=3600)  # Cache 1 uur
def load_prices():
    """Haalt rennersnamen en prijzen op van de Datawrapper CSV."""
    import requests
    try:
        response = requests.get(PRIJZEN_URL, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        df = df[['Renner', '€']].dropna()
        df.columns = ['Renner', 'Prijs']
        df['Prijs'] = pd.to_numeric(df['Prijs'], errors='coerce')
        df = df.dropna(subset=['Prijs'])
        return df
    except Exception as e:
        st.warning(f"⚠️ Kon prijzen niet ophalen: {e}")
        return pd.DataFrame(columns=['Renner', 'Prijs'])

df_prices = load_prices()

# ── Naam normalisatie ─────────────────────────────────────────────────────────
def normalize_name(name):
    """Vervang speciale tekens en verwijder accenten en niet-ASCII tekens."""
    replacements = {
        "Æ": "AE", "æ": "ae",
        "Ø": "O", "ø": "o",
        "Å": "A", "å": "a",
        "Č": "C", "č": "c",
        "Š": "S", "š": "s",
        "Đ": "D", "đ": "d",
        "Ž": "Z", "ž": "z",
        "Ć": "C", "ć": "c"
    }
    for special, replacement in replacements.items():
        name = name.replace(special, replacement)
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    name = re.sub(r'[^a-zA-Z\s-]', '', name)
    return name.strip().lower()

def find_best_match(input_name, all_riders):
    """Zoekt de beste match voor een renner in de lijst met fuzzy matching."""
    if not all_riders:
        return None
    normalized_riders = {rider: normalize_name(rider) for rider in all_riders}
    normalized_input = normalize_name(input_name)
    match_result = process.extractOne(normalized_input, list(normalized_riders.values()))
    if match_result is None:
        return None
    best_match = match_result[0]
    score = match_result[1]
    if score > 80:
        for original, norm in normalized_riders.items():
            if norm == best_match:
                return original
    return None

def get_rider_price(rider_name):
    """
    Zoekt de prijs van een renner in de Datawrapper-data.
    De CSV heeft namen als 'ACHTERNAAM Voornaam', PCS heeft 'Voornaam ACHTERNAAM'.
    We normaliseren beide en gebruiken fuzzy matching.
    """
    if df_prices.empty:
        return ""

    normalized_input = normalize_name(rider_name)

    # Normaliseer prijslijst (eenmalig berekend via cache)
    if "normalized_prices" not in st.session_state:
        df_prices["Normalized"] = df_prices["Renner"].apply(normalize_name)
        st.session_state.normalized_prices = True
    
    # Exacte match
    price_row = df_prices[df_prices["Normalized"] == normalized_input]

    # Gedeeltelijke match als geen exacte match
    if price_row.empty:
        for idx, excel_name in enumerate(df_prices["Normalized"]):
            if normalized_input in excel_name or excel_name in normalized_input:
                price_row = df_prices.iloc[[idx]]
                break

    # Fuzzy match als laatste redmiddel
    if price_row.empty:
        match_result = process.extractOne(normalized_input, df_prices["Normalized"].tolist())
        if match_result and match_result[1] > 85:
            price_row = df_prices[df_prices["Normalized"] == match_result[0]]

    return f" ({int(price_row.iloc[0]['Prijs'])}M)" if not price_row.empty else ""

# ── Achtergrond ───────────────────────────────────────────────────────────────
def set_background():
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(to bottom, #e3f2fd, #bbdefb);
        }
        </style>
        """,
        unsafe_allow_html=True
    )

set_background()

# ── Wedstrijden ───────────────────────────────────────────────────────────────
races = [
    ("Omloop Het Nieuwsblad", "2025-03-01 11:30", "World Tour"),
    ("Kuurne-Brussel-Kuurne", "2025-03-02 12:14", "Niet-World Tour"),
    ("GP-Samyn", "2025-03-04 12:35", "Niet-World Tour"),
    ("Strade Bianche", "2025-03-08 11:25", "World Tour"),
    ("Nokere Koerse", "2025-03-19 12:55", "Niet-World Tour"),
    ("Bredene Koksijde Classic", "2025-03-21 12:22", "Niet-World Tour"),
    ("Milano-Sanremo", "2025-03-22 10:25", "Monument"),
    ("Classic Brugge-De Panne", "2025-03-26 12:50", "World Tour"),
    ("E3 Harelbeke", "2025-03-28 12:52", "World Tour"),
    ("Gent-Wevelgem", "2025-03-30 10:50", "World Tour"),
    ("Dwars door Vlaanderen", "2025-04-02 12:40", "World Tour"),
    ("Ronde van Vlaanderen", "2025-04-06 10:17", "Monument"),
    ("Scheldeprijs", "2025-04-09 13:09", "Niet-World Tour"),
    ("Paris-Roubaix", "2025-04-13 14:00", "Monument"),
    ("Ronde van Limburg", "2025-04-16 13:15", "Niet-World Tour"),
    ("Brabantse Pijl", "2025-04-18 13:12", "Niet-World Tour"),
    ("Amstel Gold Race", "2025-04-20 10:43", "World Tour"),
    ("La Fleche Wallone", "2025-04-23 14:00", "World Tour"),
    ("Liège-Bastogne-Liège", "2025-04-27 14:00", "Monument")
]

# ── Startlijst scrapen ────────────────────────────────────────────────────────
async def get_startlist(session, race_name):
    race_url = f"https://www.procyclingstats.com/race/{race_name.replace(' ', '-').lower()}/2025/startlist"
    async with session.get(race_url) as response:
        if response.status != 200:
            return []
        soup = BeautifulSoup(await response.text(), "html.parser")
        startlist = [rider.text.strip() for rider in soup.select("div.ridersCont ul li a, ul.riders li a")]
        return startlist if startlist else []

async def fetch_all_riders():
    all_riders = set()
    async with aiohttp.ClientSession() as session:
        tasks = [get_startlist(session, race_name) for race_name, _, _ in races]
        results = await asyncio.gather(*tasks)
        for startlist in results:
            all_riders.update(startlist)
    return sorted(all_riders)

if "all_riders" not in st.session_state:
    st.session_state.all_riders = []
    async def load_riders():
        st.session_state.all_riders = await fetch_all_riders()
    asyncio.run(load_riders())

# ── Prijzen toevoegen aan dataframes ─────────────────────────────────────────
def add_prices_to_recommended_transfers(recommended_transfers):
    df_transfers = pd.DataFrame(
        sorted(recommended_transfers.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal wedstrijden met laag aantal deelnemers"]
    )
    df_transfers["Prijs"] = df_transfers["Renner"].apply(get_rider_price)
    df_transfers["Renner"] = df_transfers["Renner"] + df_transfers["Prijs"]
    df_transfers.drop(columns=["Prijs"], inplace=True)
    return df_transfers

def add_prices_to_rider_participation(rider_participation):
    df_rider_participation = pd.DataFrame(
        sorted(rider_participation.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal deelnames"]
    )
    df_rider_participation["Prijs"] = df_rider_participation["Renner"].apply(get_rider_price)
    df_rider_participation["Renner"] = df_rider_participation["Renner"] + df_rider_participation["Prijs"]
    df_rider_participation.drop(columns=["Prijs"], inplace=True)
    return df_rider_participation

def add_prices_to_rider_schedule(rider_schedule):
    updated_schedule = {}
    for rider, races_sched in rider_schedule.items():
        rider_with_price = rider + get_rider_price(rider)
        updated_schedule[rider_with_price] = races_sched
    return updated_schedule

def add_prices_to_transfer_schedule(transfer_rider_schedule):
    updated_schedule = {}
    for rider, races_sched in transfer_rider_schedule.items():
        rider_with_price = rider + get_rider_price(rider)
        updated_schedule[rider_with_price] = races_sched
    return updated_schedule

# ── Data ophalen ──────────────────────────────────────────────────────────────
async def fetch_data(selected_riders):
    results = []
    rider_participation = {rider: 0 for rider in selected_riders}
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    weak_races = {}
    all_riders_participation = {}

    async with aiohttp.ClientSession() as session:
        now = datetime.now()
        for race_name, race_date, category in races:
            race_datetime = datetime.strptime(race_date, "%Y-%m-%d %H:%M")
            startlist = await get_startlist(session, race_name)
            if not startlist:
                renners_count = "⚠️ Geen data"
                team_riders = []
            else:
                team_riders = [rider for rider in selected_riders if rider in startlist]
                renners_count = len(team_riders)
                for rider in team_riders:
                    rider_participation[rider] += 1
                    rider_schedule[rider][race_name] = "✅"
                if race_datetime > now and renners_count <= 9:
                    weak_races[race_name] = startlist
                for rider in startlist:
                    all_riders_participation[rider] = all_riders_participation.get(rider, 0) + 1

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

async def get_rider_schedule(selected_riders):
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    async with aiohttp.ClientSession() as session:
        for race_name, _, _ in races:
            startlist = await get_startlist(session, race_name)
            for rider in selected_riders:
                if rider in startlist:
                    rider_schedule[rider][race_name] = "✅"
    return rider_schedule

def get_next_race(races):
    now = datetime.now()
    for race_name, race_datetime, _ in races:
        race_time = datetime.strptime(race_datetime, "%Y-%m-%d %H:%M")
        if race_time > now:
            return race_name
    return races[-1][0]

def countdown_to_next_race():
    now_utc = datetime.now(pytz.utc)
    cet = pytz.timezone("Europe/Brussels")
    now = now_utc.astimezone(cet)
    for race_name, race_datetime, _ in races:
        race_time = datetime.strptime(race_datetime, "%Y-%m-%d %H:%M")
        race_time = cet.localize(race_time)
        if race_time > now:
            countdown = race_time - now
            days = countdown.days
            hours, remainder = divmod(countdown.seconds, 3600)
            minutes = remainder // 60
            return race_name, days, hours, minutes
    return None, None, None, None

# ── Streamlit app ─────────────────────────────────────────────────────────────
async def main():
    st.title("🚴 Wielermanager Tools")

    if "all_riders" not in st.session_state:
        st.session_state.all_riders = []
    if "search_button" not in st.session_state:
        st.session_state.search_button = False
    if "selected_riders" not in st.session_state:
        st.session_state.selected_riders = []

    all_riders = set()
    selected_riders = st.session_state.get("selected_riders", [])

    if st.session_state.get("search_button", False) and selected_riders:
        with st.spinner("Bezig met zoeken in startlijsten..."):
            async with aiohttp.ClientSession() as session:
                all_riders = set()
                for race_name, _, _ in races:
                    startlist = await get_startlist(session, race_name)
                    all_riders.update(startlist)
            st.session_state.all_riders = sorted(all_riders)

    all_riders = st.session_state.all_riders

    st.subheader("📋 Snel jouw team invoeren")
    rider_input = st.text_area("Plak of typ rennersnamen, gescheiden door komma's of nieuwe regels:")

    if st.button("✅ Voeg toe"):
        if rider_input:
            input_riders = re.split(r',|\n', rider_input)
            input_riders = [rider.strip() for rider in input_riders if rider.strip()]
            matched_riders = []
            for rider in input_riders:
                match = find_best_match(rider, st.session_state.all_riders)
                if match:
                    matched_riders.append(match)
            if matched_riders:
                st.session_state.selected_riders = matched_riders
                st.success(f"{len(matched_riders)} renners toegevoegd!")
            else:
                st.warning("Geen renners gevonden. Controleer de spelling of probeer andere varianten.")
            if len(matched_riders) != 20:
                st.warning("⚠️ Let op! Je hebt geen 20 renners geselecteerd.")

    st.subheader("📋 Selecteer je team")
    selected_riders = st.multiselect(
        "Kies jouw renners:", st.session_state.all_riders,
        default=st.session_state.get("selected_riders", []))

    if st.button("🔍 Zoeken"):
        st.session_state.search_button = True

    if st.session_state.search_button and selected_riders:
        results, rider_participation, rider_schedule, recommended_transfers = await fetch_data(selected_riders)

        df = pd.DataFrame(results)
        df.index = df.index + 1
        st.dataframe(df.drop(columns=["Datum"]))

        st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
        rider_schedule_with_prices = add_prices_to_rider_schedule(rider_schedule)
        schedule_df = pd.DataFrame.from_dict(rider_schedule_with_prices, orient="index")
        st.dataframe(schedule_df.sort_index())

        st.subheader("🔍 Vergelijk mogelijke transfers")
        available_transfers = [rider for rider in st.session_state.all_riders if rider not in selected_riders]
        transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", available_transfers)

        transfer_rider_schedule = {}
        if transfer_riders:
            with st.spinner("Bezig met ophalen van schema's..."):
                transfer_rider_schedule = await get_rider_schedule(transfer_riders)

        if transfer_rider_schedule:
            st.subheader("📅 Wedstrijdschema van mogelijke transfers")
            transfer_schedule_with_prices = add_prices_to_transfer_schedule(transfer_rider_schedule)
            transfer_schedule_df = pd.DataFrame.from_dict(transfer_schedule_with_prices, orient="index").sort_index()
            st.dataframe(transfer_schedule_df)

        df_transfers = add_prices_to_recommended_transfers(recommended_transfers)
        st.subheader("🔄 Voorgestelde transfers voor zwak bezette toekomstige wedstrijden")
        st.dataframe(df_transfers.set_index("Renner"))

        next_race = get_next_race(races)
        st.subheader("🏁 Jouw startlijst per wedstrijd")
        wedstrijd_optie = st.selectbox(
            "Selecteer een wedstrijd om jouw renners te zien:",
            [race[0] for race in races],
            index=[race[0] for race in races].index(next_race)
        )

        if wedstrijd_optie:
            async with aiohttp.ClientSession() as session:
                startlist = await get_startlist(session, wedstrijd_optie)
            team_riders = [rider for rider in selected_riders if rider in startlist]
            st.subheader(f"🏁 Jouw renners in {wedstrijd_optie}:")
            if team_riders:
                for rider in sorted(team_riders):
                    st.success(f"✅ **{rider}**")
            else:
                st.warning("🚨 Geen renners van jouw team in deze wedstrijd!")

        st.subheader("📊 Deelnames per renner")
        df_rider_participation = add_prices_to_rider_participation(rider_participation)
        st.dataframe(df_rider_participation.set_index("Renner"))

        next_race, days, hours, minutes = countdown_to_next_race()
        if next_race:
            st.markdown("---")
            st.subheader(f"⏳ Nog **{days} dagen, {hours} uur en {minutes} minuten** tot **{next_race}**!")

if __name__ == "__main__":
    import streamlit as st
    import asyncio
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
