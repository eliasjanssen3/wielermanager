import streamlit as st
import aiohttp
import asyncio
import pandas as pd
from bs4 import BeautifulSoup

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

    if "selected_riders" not in st.session_state:
        st.session_state.selected_riders = []

    # ✅ Haal renners op
    with st.spinner("Bezig met ophalen van startlijsten van procyclingstats.com..."):
        async with aiohttp.ClientSession() as session:
            all_riders = set()
            for race_name, _, _ in races:
                startlist = await get_startlist(session, race_name)
                all_riders.update(startlist)

    all_riders = sorted(all_riders)

    # ✅ Selecteer renners
    st.subheader("📋 Selecteer je team")
    selected_riders = st.multiselect(
    "Kies jouw renners:", all_riders, default=st.session_state.selected_riders)

    # Sla keuzes op in session state
    st.session_state.selected_riders = selected_riders

    if selected_riders:
        results, rider_participation, rider_schedule, recommended_transfers = await fetch_data(selected_riders)

        df = pd.DataFrame(results)
        df.index = df.index + 1
        st.dataframe(df)

        # 🎯 Overzicht per renner en wedstrijd
        st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
        schedule_df = pd.DataFrame.from_dict(rider_schedule, orient="index")
        st.dataframe(schedule_df.sort_index())

        # 🎯 Vergelijk mogelijke transfers
        st.subheader("🔍 Vergelijk mogelijke transfers")
        transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", all_riders)

        # Zorg ervoor dat transfer_rider_schedule altijd geïnitialiseerd is
        transfer_rider_schedule = {}

        if transfer_riders:
            with st.spinner("Bezig met ophalen van schema's..."):
                transfer_rider_schedule = await get_rider_schedule(transfer_riders)

        # ✅ Toon schema in tabel alleen als er renners zijn ingevoerd
        if transfer_rider_schedule:
            st.subheader("📅 Wedstrijdschema van mogelijke transfers")
            transfer_schedule_df = pd.DataFrame.from_dict(transfer_rider_schedule, orient="index").sort_index()
            st.dataframe(transfer_schedule_df)

        # 🎯 Aangeraden transfers
        st.subheader("🔄 Voorgestelde transfers voor zwak bezette wedstrijden")
        transfer_df = pd.DataFrame(sorted(recommended_transfers.items(), key=lambda x: x[1], reverse=True), columns=["Renner", "Aantal wedstrijden met laag aantal deelnemers van mijn team"])
        st.dataframe(transfer_df.set_index("Renner"))

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
        rider_df = pd.DataFrame(sorted(rider_participation.items(), key=lambda x: x[1], reverse=True), columns=["Renner", "Aantal deelnames"])
        st.dataframe(rider_df.set_index("Renner"))

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