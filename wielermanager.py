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

            results.append({
                "Wedstrijd": race_name,
                "Datum": race_date,
                "Categorie": category,
                "Aantal renners": str(renners_count)
            })

    return results, rider_participation, rider_schedule

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
        results, rider_participation, rider_schedule = await fetch_data(selected_riders)

        # ✅ Maak dataframe en zorg voor correcte index
        df = pd.DataFrame(results)
        df.index = df.index + 1  # ✅ Start bij 1 i.p.v. 0
        st.dataframe(df)

        # 🎯 Keuzemenu om per wedstrijd de renners uit jouw team te tonen
        wedstrijd_optie = st.selectbox("Selecteer een wedstrijd om jouw renners te zien:", [r["Wedstrijd"] for r in results])
        geselecteerde_wedstrijd = next((r for r in results if r["Wedstrijd"] == wedstrijd_optie), None)

        if geselecteerde_wedstrijd:
            # ✅ Scrape opnieuw de startlijst voor deze wedstrijd
            async with aiohttp.ClientSession() as session:
                startlist = await get_startlist(session, wedstrijd_optie)

            # ✅ Bepaal welke renners uit het geselecteerde team meedoen
            team_riders = [rider for rider in selected_riders if rider in startlist]

            st.subheader(f"🏁 Jouw renners in {wedstrijd_optie}:")
            if team_riders:
                st.success("\n".join([f"✅ **{rider}**" for rider in team_riders]))  # Onder elkaar
            else:
                st.warning("🚨 Geen renners van jouw team in deze wedstrijd!")

        # 🎯 Overzicht van welke renners waar starten (schema)
        st.subheader("📅 Overzicht: Welke renners starten in welke wedstrijd?")
        schedule_df = pd.DataFrame.from_dict(rider_schedule, orient="index")
        st.dataframe(schedule_df.sort_index())  # ✅ Sorteer alfabetisch op renner

        # 🎯 Lijst met aantal deelnames per renner
        st.subheader("📊 Deelnames per renner")

        # ✅ Dataframe zonder indexkolom
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