import streamlit as st
import aiohttp
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
import unicodedata
import re
import os
from rapidfuzz import process
from datetime import datetime
import pytz

# ── Prijzen laden uit Excel ───────────────────────────────────────────────────
file_path = os.path.join(os.path.dirname(__file__), "data/PrijzenWielermanager.xlsx")

@st.cache_data
def load_prices():
    if os.path.exists(file_path):
        df = pd.read_excel(file_path, sheet_name='Blad1')
        df.columns = ["Renner", "Prijs"]
        df = df.dropna()
        df["Prijs"] = pd.to_numeric(df["Prijs"], errors='coerce')
        df = df.dropna(subset=['Prijs'])
        df["Normalized"] = df["Renner"].apply(normalize_name)
        return df
    else:
        st.warning("Prijzenbestand niet gevonden.")
        return pd.DataFrame(columns=['Renner', 'Prijs', 'Normalized'])

# ── Naam normalisatie ─────────────────────────────────────────────────────────
def normalize_name(name):
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

    # 1. Exacte match
    for original, norm in normalized_riders.items():
        if norm == normalized_input:
            return original

    # 2. Omgekeerde volgorde
    words = normalized_input.split()
    reversed_input = ' '.join(reversed(words)) if len(words) >= 2 else None
    if reversed_input:
        for original, norm in normalized_riders.items():
            if norm == reversed_input:
                return original

    # 3. Fuzzy match op beide varianten
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
    df_prices = load_prices()
    if df_prices.empty:
        return ""
    normalized_input = normalize_name(rider_name)
    price_row = df_prices[df_prices["Normalized"] == normalized_input]
    if price_row.empty:
        for idx, norm_name in enumerate(df_prices["Normalized"]):
            if normalized_input in norm_name or norm_name in normalized_input:
                price_row = df_prices.iloc[[idx]]
                break
    if price_row.empty:
        match_result = process.extractOne(normalized_input, df_prices["Normalized"].tolist())
        if match_result and match_result[1] > 85:
            price_row = df_prices[df_prices["Normalized"] == match_result[0]]
    return f" ({int(price_row.iloc[0]['Prijs'])}M)" if not price_row.empty else ""

# ── Achtergrond ───────────────────────────────────────────────────────────────
st.markdown("""
    <style>
    .stApp { background: linear-gradient(to bottom, #e3f2fd, #bbdefb); }
    </style>
""", unsafe_allow_html=True)

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

# ── Startlijsten scrapen ──────────────────────────────────────────────────────
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

# ── Riders laden bij opstarten ────────────────────────────────────────────────
if "all_riders" not in st.session_state:
    st.session_state.all_riders = []

if not st.session_state.all_riders:
    with st.spinner("🔄 Startlijsten laden, even geduld..."):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            st.session_state.all_riders = loop.run_until_complete(fetch_all_riders())
            loop.close()
        except Exception as e:
            st.error(f"Fout bij laden startlijsten: {e}")

# ── Helpers ───────────────────────────────────────────────────────────────────
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

def add_prices_to_schedule(schedule):
    return {rider + get_rider_price(rider): rs for rider, rs in schedule.items()}

async def fetch_data(selected_riders):
    results = []
    rider_participation = {rider: 0 for rider in selected_riders}
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    weak_races = {}

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
            results.append({"Wedstrijd": race_name, "Datum": race_date, "Categorie": category, "Aantal renners": str(renners_count)})

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
async def main():
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
        results, rider_participation, rider_schedule, recommended_transfers = await fetch_data(selected_riders)

        df = pd.DataFrame(results)
        df.index = df.index + 1
        st.dataframe(df.drop(columns=["Datum"]))

        st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
        st.dataframe(pd.DataFrame.from_dict(add_prices_to_schedule(rider_schedule), orient="index").sort_index())

        st.subheader("🔍 Vergelijk mogelijke transfers")
        available_transfers = [r for r in st.session_state.all_riders if r not in selected_riders]
        transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", available_transfers)

        if transfer_riders:
            with st.spinner("Bezig met ophalen van schema's..."):
                transfer_schedule = await get_rider_schedule(transfer_riders)
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
        st.dataframe(add_prices_to_rider_participation(rider_participation).set_index("Renner"))

        next_race, days, hours, minutes = countdown_to_next_race()
        if next_race:
            st.markdown("---")
            st.subheader(f"⏳ Nog **{days} dagen, {hours} uur en {minutes} minuten** tot **{next_race}**!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
