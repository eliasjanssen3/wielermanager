import streamlit as st
import aiohttp
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
import unicodedata
import re
import os

# Inlezen van het Excel-bestand met prijzen
# Zoek het pad naar het bestand in de repository
file_path = os.path.join(os.path.dirname(__file__), "data/PrijzenWielermanager.xlsx")

# Controleer of het bestand bestaat en laad het in
if os.path.exists(file_path):
    df_prices = pd.read_excel(file_path, sheet_name='Blad1')
    st.write("✅ Prijzenbestand geladen!")  # Debug check
else:
    st.error("❌ Prijzenbestand niet gevonden! Zorg ervoor dat het in de repository staat.")
xls = pd.ExcelFile(file_path)
df_prices = pd.read_excel(xls, sheet_name='Blad1')
df_prices.columns = ["Renner", "Prijs"]
df_prices = df_prices.dropna()
df_prices["Prijs"] = pd.to_numeric(df_prices["Prijs"], errors='coerce')

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
    
    # Vervang specifieke tekens
    for special, replacement in replacements.items():
        name = name.replace(special, replacement)

    # Verwijder overige accenten
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')

    # Verwijder overige niet-ASCII tekens (mocht er iets achterblijven)
    name = re.sub(r'[^a-zA-Z\s-]', '', name)

    return name.strip().lower()

def get_rider_price(rider_name):
    """Zoekt de prijs van een renner in de Excel-lijst zonder accenten."""
    normalized_rider_name = normalize_name(rider_name)

    # Normaliseer de Excel-namen
    df_prices["Normalized"] = df_prices["Renner"].apply(normalize_name)

    # Zoek op exacte match
    price_row = df_prices[df_prices["Normalized"] == normalized_rider_name]

    # Als er geen exacte match is, zoek naar een gedeeltelijke match
    if price_row.empty:
        for excel_name in df_prices["Normalized"]:
            if normalized_rider_name in excel_name or excel_name in normalized_rider_name:
                price_row = df_prices[df_prices["Normalized"] == excel_name]
                break

    return f" ({int(price_row.iloc[0]['Prijs'])}M)" if not price_row.empty else ""

# 🎨 Achtergrond instellen
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

# 🎯 Lijst met correcte namen en categorieën
races = [
    ("Omloop Het Nieuwsblad", "1 maart", "World Tour"),
    ("Kuurne-Brussel-Kuurne", "2 maart", "Niet-World Tour"),
    ("GP-Samyn", "4 maart", "Niet-World Tour"),
    ("Strade Bianche", "8 maart", "World Tour"),
    ("Nokere Koers", "19 maart", "Niet-World Tour"),
    ("Bredene Koksijde Classic", "21 maart", "Niet-World Tour"),
    ("Milano-Sanremo", "22 maart", "Monument"),
    ("Classic Brugge-De Panne", "26 maart", "World Tour"),
    ("E3 Harelbeke", "28 maart", "World Tour"),
    ("Gent-Wevelgem", "30 maart", "World Tour"),
    ("Dwars door Vlaanderen", "2 april", "World Tour"),
    ("Ronde van Vlaanderen", "6 april", "Monument"),
    ("Scheldeprijs", "9 april", "Niet-World Tour"),
    ("Paris-Roubaix", "13 april", "Monument"),
    ("Ronde van Limburg", "16 april", "Niet-World Tour"),
    ("Brabantse Pijl", "18 april", "Niet-World Tour"),
    ("Amstel Gold Race", "20 april", "World Tour"),
    ("La Fleche Wallone", "23 april", "World Tour"),
    ("Liège-Bastogne-Liège", "27 april", "Monument"),
]

# 🎯 Scrape startlijst van ProCyclingStats
async def get_startlist(session, race_name):
    race_url = f"https://www.procyclingstats.com/race/{race_name.replace(' ', '-').lower()}/2025/startlist"
    
    async with session.get(race_url) as response:
        if response.status != 200:
            return []

        soup = BeautifulSoup(await response.text(), "html.parser")
        startlist = [rider.text.strip() for rider in soup.select("div.ridersCont ul li a, ul.riders li a")]

        return startlist if startlist else []

# 🎯 Haal alle startlijsten op en verzamel unieke renners
async def fetch_all_riders():
        all_riders = set()
        async with aiohttp.ClientSession() as session:
            tasks = [get_startlist(session, race_name) for race_name, _, _ in races]
            results = await asyncio.gather(*tasks)
            for startlist in results:
                all_riders.update(startlist)
        return sorted(all_riders)

if "all_riders" not in st.session_state:
    st.session_state.all_riders = []  # Zorg dat de variabele bestaat

    # Start asynchrone taak om renners op te halen
    async def load_riders():
        st.session_state.all_riders = await fetch_all_riders()
    
    asyncio.run(load_riders())  # Start ophalen zonder UI-blokkade

# Aanpassing in fetch_data om prijzen toe te voegen
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
    for rider, races in rider_schedule.items():
        rider_with_price = rider + get_rider_price(rider)
        updated_schedule[rider_with_price] = races
    return updated_schedule

def add_prices_to_transfer_schedule(transfer_rider_schedule):
    updated_schedule = {}
    for rider, races in transfer_rider_schedule.items():
        rider_with_price = rider + get_rider_price(rider)
        updated_schedule[rider_with_price] = races
    return updated_schedule

async def fetch_all_riders_async():
    st.session_state.all_riders = await fetch_all_riders()

async def fetch_data(selected_riders):
    results = []
    rider_participation = {rider: 0 for rider in selected_riders}
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    weak_races = {}
    all_riders_participation = {}

    async with aiohttp.ClientSession() as session:
        for race_name, race_date, category in races:
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

                if renners_count <= 7:
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
    """Haalt het wedstrijdschema op voor ingevoerde renners."""
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}

    async with aiohttp.ClientSession() as session:
        for race_name, _, _ in races:
            startlist = await get_startlist(session, race_name)
            for rider in selected_riders:
                if rider in startlist:
                    rider_schedule[rider][race_name] = "✅"

    return rider_schedule

# 🎯 Streamlit-app
async def main():
    st.title("🚴 Wielermanager Tools")

    if "all_riders" not in st.session_state:
        st.session_state.all_riders = []  # Zorg dat het altijd bestaat

    if "search_button" not in st.session_state:
        st.session_state.search_button = False

    if "selected_riders" not in st.session_state:
        st.session_state.selected_riders = []

    # ✅ Haal renners pas op bij klikken op de knop
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

    # ✅ Selecteer renners
    st.subheader("📋 Selecteer je team")
    if "all_riders" not in st.session_state:
        st.session_state.all_riders = []

    selected_riders = st.multiselect(
    "Kies jouw renners:", st.session_state.all_riders, default=st.session_state.get("selected_riders", []))

    if st.button("🔍 Zoeken"):
        st.session_state.search_button = True

    if st.session_state.search_button and selected_riders:
        results, rider_participation, rider_schedule, recommended_transfers = await fetch_data(selected_riders)

        df = pd.DataFrame(results)
        df.index = df.index + 1
        st.dataframe(df)

        # 🎯 Overzicht per renner en wedstrijd
        st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
        rider_schedule_with_prices = add_prices_to_rider_schedule(rider_schedule)
        schedule_df = pd.DataFrame.from_dict(rider_schedule_with_prices, orient="index")
        st.dataframe(schedule_df.sort_index())

        # 🎯 Vergelijk mogelijke transfers
        st.subheader("🔍 Vergelijk mogelijke transfers")
        available_transfers = [rider for rider in st.session_state.all_riders if rider not in selected_riders]

        transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", available_transfers)

        # Zorg ervoor dat transfer_rider_schedule altijd geïnitialiseerd is
        transfer_rider_schedule = {}

        if transfer_riders:
            with st.spinner("Bezig met ophalen van schema's..."):
                transfer_rider_schedule = await get_rider_schedule(transfer_riders)

        # ✅ Toon schema in tabel alleen als er renners zijn ingevoerd
        if transfer_rider_schedule:
            st.subheader("📅 Wedstrijdschema van mogelijke transfers")
            transfer_schedule_with_prices = add_prices_to_transfer_schedule(transfer_rider_schedule)
            transfer_schedule_df = pd.DataFrame.from_dict(transfer_schedule_with_prices, orient="index").sort_index()
            st.dataframe(transfer_schedule_df)

        # 🎯 Aangeraden transfers
        df_transfers = add_prices_to_recommended_transfers(recommended_transfers)
        st.subheader("🔄 Voorgestelde transfers voor zwak bezette wedstrijden")
        st.dataframe(df_transfers.set_index("Renner"))

        # 🎯 Jouw renners per wedstrijd
        st.subheader("🏁 Jouw startlijst per wedstrijd")
        wedstrijd_optie = st.selectbox("Selecteer een wedstrijd om jouw renners te zien:", [r["Wedstrijd"] for r in results])

        if wedstrijd_optie:
            async with aiohttp.ClientSession() as session:
                startlist = await get_startlist(session, wedstrijd_optie)
            team_riders = [rider for rider in selected_riders if rider in startlist]

            st.subheader(f"🏁 Jouw renners in {wedstrijd_optie}:")
            if team_riders:
                for rider in sorted(team_riders):  # ✅ Sorteer alfabetisch
                    st.success(f"✅ **{rider}**")
            else:
                st.warning("🚨 Geen renners van jouw team in deze wedstrijd!")

        # 🎯 Aantal deelnames per renner
        st.subheader("📊 Deelnames per renner")
        df_rider_participation = add_prices_to_rider_participation(rider_participation)
        st.dataframe(df_rider_participation.set_index("Renner"))

# 🎯 Start de Streamlit-app
if __name__ == "__main__":
    import streamlit as st
    import asyncio

    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())