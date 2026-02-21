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

if os.path.exists(file_path):
    df_prices = pd.read_excel(file_path, sheet_name='Blad1')
    df_prices.columns = ["Renner", "Prijs"]
    df_prices = df_prices.dropna()
    df_prices["Prijs"] = pd.to_numeric(df_prices["Prijs"], errors='coerce')

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
    normalized_riders = {rider: normalize_name(rider) for rider in all_riders}
    normalized_input = normalize_name(input_name)

    # 1. Exacte match
    for original, norm in normalized_riders.items():
        if norm == normalized_input:
            return original

    # 2. Omgekeerde volgorde (bv. "van aert wout" → "wout van aert")
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
    if 'df_prices' not in globals() or df_prices.empty:
        return ""
    normalized_rider_name = normalize_name(rider_name)
    df_prices["Normalized"] = df_prices["Renner"].apply(normalize_name)
    price_row = df_prices[df_prices["Normalized"] == normalized_rider_name]
    if price_row.empty:
        for excel_name in df_prices["Normalized"]:
            if normalized_rider_name in excel_name or excel_name in normalized_rider_name:
                price_row = df_prices[df_prices["Normalized"] == excel_name]
                break
    return f" ({int(price_row.iloc[0]['Prijs'])}M)" if not price_row.empty else ""

# ── Achtergrond ───────────────────────────────────────────────────────────────
def set_background():
    st.markdown("""
        <style>
        .stApp { background: linear-gradient(to bottom, #e3f2fd, #bbdefb); }
        </style>
    """, unsafe_allow_html=True)

set_background()

# ── DEBUG ─────────────────────────────────────────────────────────────────────
import requests as req_debug
with st.expander('🔧 Debug info'):
    test_url = 'https://www.procyclingstats.com/race/omloop-het-nieuwsblad/2026/startlist'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.procyclingstats.com/',
    }
    try:
        r = req_debug.get(test_url, headers=headers, timeout=10)
        st.write(f'Status code: {r.status_code}')
        st.write(f'Aantal riders in session_state: {len(st.session_state.all_riders)}')
        from bs4 import BeautifulSoup as BS
        soup = BS(r.text, 'html.parser')
        riders = [x.text.strip() for x in soup.select('div.ridersCont ul li a, ul.riders li a')]
        st.write(f'Riders gevonden op PCS: {len(riders)}')
        if riders:
            st.write(f'Eerste 5: {riders[:5]}')
        else:
            st.write('HTML snippet:')
            st.code(r.text[:2000])
    except Exception as e:
        st.error(f'Fout: {e}')


# ── Wedstrijden ───────────────────────────────────────────────────────────────
races = [
    ("Omloop Het Nieuwsblad", "2026-02-28 11:30", "World Tour"),
    ("Kuurne-Brussel-Kuurne", "2026-03-01 12:14", "Niet-World Tour"),
    ("GP-Samyn", "2026-03-03 12:35", "Niet-World Tour"),
    ("Strade Bianche", "2026-03-07 11:25", "World Tour"),
    ("Nokere Koerse", "2026-03-18 12:55", "Niet-World Tour"),
    ("Bredene Koksijde Classic", "2026-03-20 12:22", "Niet-World Tour"),
    ("Milano-Sanremo", "2026-03-21 10:25", "Monument"),
    ("Classic Brugge-De Panne", "2026-03-25 12:50", "World Tour"),
    ("E3 Harelbeke", "2026-03-27 12:52", "World Tour"),
    ("Gent-Wevelgem", "2026-03-29 10:50", "World Tour"),
    ("Dwars door Vlaanderen", "2026-04-01 12:40", "World Tour"),
    ("Ronde van Vlaanderen", "2026-04-05 10:17", "Monument"),
    ("Scheldeprijs", "2026-04-08 13:09", "Niet-World Tour"),
    ("Paris-Roubaix", "2026-04-12 14:00", "Monument"),
    ("Ronde van Limburg", "2026-04-15 13:15", "Niet-World Tour"),
    ("Brabantse Pijl", "2026-04-17 13:12", "Niet-World Tour"),
    ("Amstel Gold Race", "2026-04-19 10:43", "World Tour"),
    ("La Fleche Wallone", "2026-04-22 14:00", "World Tour"),
    ("Liège-Bastogne-Liège", "2026-04-26 14:00", "Monument")
]

# ── Startlijst scrapen ────────────────────────────────────────────────────────
async def get_startlist(session, race_name):
    race_url = f"https://www.procyclingstats.com/race/{race_name.replace(' ', '-').lower()}/2026/startlist"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'nl-BE,nl;q=0.9,en;q=0.8',
        'Referer': 'https://www.procyclingstats.com/',
        'Connection': 'keep-alive',
    }
    async with session.get(race_url, headers=headers) as response:
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

# ── Riders laden bij opstarten uit Excel ─────────────────────────────────────
if "all_riders" not in st.session_state:
    if os.path.exists(file_path):
        # Laad rennersnamen uit Excel, converteer van ACHTERNAAM Voornaam naar Voornaam ACHTERNAAM
        def to_pcs_format(name):
            parts = name.strip().split()
            if len(parts) >= 2:
                # Zoek waar de voornaam begint (eerste woord dat niet volledig hoofdletters is)
                for i, part in enumerate(parts):
                    if not part.isupper():
                        return ' '.join(parts[i:] + parts[:i])
            return name
        
        excel_riders = df_prices["Renner"].tolist()
        st.session_state.all_riders = sorted([to_pcs_format(r) for r in excel_riders])
    else:
        st.session_state.all_riders = []

# ── Helpers ───────────────────────────────────────────────────────────────────
def add_prices_to_recommended_transfers(recommended_transfers):
    df = pd.DataFrame(
        sorted(recommended_transfers.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal wedstrijden met laag aantal deelnemers"]
    )
    df["Prijs"] = df["Renner"].apply(get_rider_price)
    df["Renner"] = df["Renner"] + df["Prijs"]
    df.drop(columns=["Prijs"], inplace=True)
    return df

def add_prices_to_rider_participation(rider_participation):
    df = pd.DataFrame(
        sorted(rider_participation.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal deelnames"]
    )
    df["Prijs"] = df["Renner"].apply(get_rider_price)
    df["Renner"] = df["Renner"] + df["Prijs"]
    df.drop(columns=["Prijs"], inplace=True)
    return df

def add_prices_to_rider_schedule(rider_schedule):
    updated_schedule = {}
    for rider, race_data in rider_schedule.items():
        updated_schedule[rider + get_rider_price(rider)] = race_data
    return updated_schedule

def add_prices_to_transfer_schedule(transfer_rider_schedule):
    updated_schedule = {}
    for rider, race_data in transfer_rider_schedule.items():
        updated_schedule[rider + get_rider_price(rider)] = race_data
    return updated_schedule

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

def get_next_race(races):
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

# ── Streamlit app ─────────────────────────────────────────────────────────────
async def main():
    st.title("🚴 Wielermanager Tools")

    if "all_riders" not in st.session_state:
        st.session_state.all_riders = []
    if "search_button" not in st.session_state:
        st.session_state.search_button = False
    if "selected_riders" not in st.session_state:
        st.session_state.selected_riders = []

    if st.session_state.get("search_button", False) and st.session_state.get("selected_riders", []):
        with st.spinner("Bezig met zoeken in startlijsten..."):
            async with aiohttp.ClientSession() as session:
                all_riders = set()
                for race_name, _, _ in races:
                    startlist = await get_startlist(session, race_name)
                    all_riders.update(startlist)
            st.session_state.all_riders = sorted(all_riders)

    st.subheader("📋 Snel jouw team invoeren")
    rider_input = st.text_area(
        "Plak of typ rennersnamen, gescheiden door komma's of nieuwe regels:",
        placeholder="bv: wout van aert, van der poel, pogacar..."
    )

    if st.button("✅ Voeg toe"):
        if rider_input:
            input_riders = re.split(r',|\n', rider_input)
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
        rider_schedule_with_prices = add_prices_to_rider_schedule(rider_schedule)
        st.dataframe(pd.DataFrame.from_dict(rider_schedule_with_prices, orient="index").sort_index())

        st.subheader("🔍 Vergelijk mogelijke transfers")
        available_transfers = [r for r in st.session_state.all_riders if r not in selected_riders]
        transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", available_transfers)
        transfer_rider_schedule = {}
        if transfer_riders:
            with st.spinner("Bezig met ophalen van schema's..."):
                transfer_rider_schedule = await get_rider_schedule(transfer_riders)
        if transfer_rider_schedule:
            st.subheader("📅 Wedstrijdschema van mogelijke transfers")
            st.dataframe(pd.DataFrame.from_dict(add_prices_to_transfer_schedule(transfer_rider_schedule), orient="index").sort_index())

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
