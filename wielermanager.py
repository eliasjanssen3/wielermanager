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
        /* Algemene achtergrondkleur */
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

        # ✅ Selector voor startlijsten
        startlist = [rider.text.strip() for rider in soup.select("div.ridersCont ul li a, ul.riders li a")]

        return startlist if startlist else []

# 🎯 Haal alle startlijsten op en verzamel unieke renners
async def fetch_data(selected_riders):
    results = []
    rider_participation = {rider: 0 for rider in selected_riders}  # Alleen voor geselecteerde renners
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    weak_races = {}  # Zwakke wedstrijden en hun startlijsten
    all_riders_participation = {}

    async with aiohttp.ClientSession() as session:
        for race_name, race_date, category in races:
            startlist = await get_startlist(session, race_name)
            if not startlist:
                renners_count = "⚠️ Geen data"
                team_riders = []
            else:
                # ✅ Alleen renners uit het geselecteerde team tellen
                team_riders = [rider for rider in selected_riders if rider in startlist]
                renners_count = len(team_riders)

                # ✅ Update deelnames per renner en schema
                for rider in team_riders:
                    rider_participation[rider] += 1
                    rider_schedule[rider][race_name] = "✅"

                # ✅ Detecteer zwakke wedstrijden
                if renners_count <= 7:
                    weak_races[race_name] = startlist  # Bewaar de volledige startlijst

                # ✅ Verzamel data voor alle renners
                for rider in startlist:
                    all_riders_participation[rider] = all_riders_participation.get(rider, 0) + 1

            results.append({
                "Wedstrijd": race_name,
                "Datum": race_date,
                "Categorie": category,
                "Aantal renners": str(renners_count)
            })

    # ✅ Filter aanbevolen transfers (renners die starten in zwakke wedstrijden)
    recommended_transfers = {}
    for race, race_riders in weak_races.items():
        for rider in race_riders:
            if rider not in selected_riders:
                if rider not in recommended_transfers:
                    recommended_transfers[rider] = 0
                recommended_transfers[rider] += 1  # ✅ Correcte telling per wedstrijd

    return results, rider_participation, rider_schedule, recommended_transfers

# 🎯 Streamlit-app
async def main():
    st.title("🚴 Wielermanager - Aantal renners per wedstrijd")

    # ✅ Haal renners op
    with st.spinner("Bezig met laden van startlijsten..."):
        async with aiohttp.ClientSession() as session:
            all_riders = set()
            for race_name, _, _ in races:
                startlist = await get_startlist(session, race_name)
                all_riders.update(startlist)

    all_riders = sorted(all_riders)

    # ✅ Selecteer renners
    st.subheader("📋 Selecteer je team")
    selected_riders = st.multiselect("Kies jouw renners:", all_riders)

    if selected_riders:
        # ✅ Haal data op
        results, rider_participation, rider_schedule, recommended_transfers = await fetch_data(selected_riders)

        # ✅ Maak dataframe en zorg voor correcte index
        df = pd.DataFrame(results)
        df.index = df.index + 1  # ✅ Start bij 1 i.p.v. 0
        st.dataframe(df)

        # 🎯 Overzicht van welke renners waar starten (schema)
        st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
        schedule_df = pd.DataFrame.from_dict(rider_schedule, orient="index")
        st.dataframe(schedule_df.sort_index())  # ✅ Sorteer alfabetisch op renner

        # 🎯 Keuzemenu om per wedstrijd de renners uit jouw team te tonen
        st.subheader("🏁 Jouw renners per wedstrijd")
        wedstrijd_optie = st.selectbox("Selecteer een wedstrijd om jouw renners te zien:", [r["Wedstrijd"] for r in results])
        if wedstrijd_optie:
            async with aiohttp.ClientSession() as session:
                startlist = await get_startlist(session, wedstrijd_optie)
            team_riders = [rider for rider in selected_riders if rider in startlist]

            st.subheader(f"🏁 Jouw renners in {wedstrijd_optie}:")
            if team_riders:
                st.success(" ".join([f"✅ **{rider}**" for rider in team_riders]))
            else:
                st.warning("🚨 Geen renners van jouw team in deze wedstrijd!")

        # 🎯 Lijst met aanbevolen transfers
        st.subheader("🔄 Aangeraden transfers voor zwakke wedstrijden")
        if recommended_transfers:
            transfer_df = pd.DataFrame(
                sorted(recommended_transfers.items(), key=lambda x: x[1], reverse=True),
                columns=["Renner", "Aantal wedstrijden met laag aantal deelnemers van mijn team"]
            )
            st.dataframe(transfer_df.set_index("Renner"))  # ✅ Verwijder index voor nettere weergave
        else:
            st.info("✅ Geen aanbevolen transfers nodig. Je team heeft voldoende dekking!")

        # 🎯 Lijst met aantal deelnames per renner
        st.subheader("📊 Deelnames per renner")
        rider_df = pd.DataFrame(
            sorted(rider_participation.items(), key=lambda x: x[1], reverse=True), 
            columns=["Renner", "Aantal deelnames"]
        )
        st.dataframe(rider_df.set_index("Renner"))  # ✅ Verwijder index voor nettere weergave
    else:
        st.warning("🚨 Selecteer eerst renners om door te gaan!")

# 🎯 Start de Streamlit-app
if __name__ == "__main__":
    asyncio.run(main())