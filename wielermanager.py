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

# ── Logo ──────────────────────────────────────────────────────────────────────
def _img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

LOGO_PATH = "data/logo.png"
logo_b64 = _img_to_base64(LOGO_PATH) if os.path.exists(LOGO_PATH) else ""

# ── Prijzen laden uit Datawrapper CSV ────────────────────────────────────────
@st.cache_data(ttl=300)
def load_prijzen_csv():
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
    return pd.DataFrame()

def get_rider_price(rider_name: str) -> str:
    if df_prijzen.empty or "€" not in df_prijzen.columns:
        return ""
    normalized_input = normalize_name(rider_name)
    df = df_prijzen.copy()
    df["Normalized"] = df["Renner"].apply(normalize_name)
    # Exacte match
    row = df[df["Normalized"] == normalized_input]
    # Rotatie-match (voor/achternaam omgewisseld)
    if row.empty:
        words = normalized_input.split()
        for i in range(1, len(words)):
            variant = " ".join(words[i:] + words[:i])
            row = df[df["Normalized"] == variant]
            if not row.empty:
                break
    # Fuzzy fallback
    if row.empty:
        match = process.extractOne(normalized_input, df["Normalized"].tolist())
        if match and match[1] > 80:
            row = df[df["Normalized"] == match[0]]
    if not row.empty:
        try:
            return f" ({int(row.iloc[0]['€'])}M)"
        except Exception:
            return ""
    return ""

# ── PCS URL mapping per koers ─────────────────────────────────────────────────
PCS_URLS = {
    "Omloop Het Nieuwsblad":    "https://www.procyclingstats.com/race/omloop-het-nieuwsblad/2026/startlist",
    "Kuurne-Brussel-Kuurne":    "https://www.procyclingstats.com/race/kuurne-brussel-kuurne/2026/startlist",
    "GP-Samyn":                 "https://www.procyclingstats.com/race/gp-samyn/2026/startlist",
    "Strade Bianche":           "https://www.procyclingstats.com/race/strade-bianche/2026/startlist",
    "Nokere Koerse":            "https://www.procyclingstats.com/race/nokere-koerse/2026/startlist",
    "Bredene Koksijde Classic": "https://www.procyclingstats.com/race/bredene-koksijde-classic/2026/startlist",
    "Milano-Sanremo":           "https://www.procyclingstats.com/race/milano-sanremo/2026/startlist",
    "Classic Brugge-De Panne": "https://www.procyclingstats.com/race/classic-brugge-de-panne/2026/startlist",
    "E3 Harelbeke":             "https://www.procyclingstats.com/race/e3-harelbeke/2026/startlist",
    "Gent-Wevelgem":            "https://www.procyclingstats.com/race/gent-wevelgem/2026/startlist",
    "Dwars door Vlaanderen":    "https://www.procyclingstats.com/race/dwars-door-vlaanderen/2026/startlist",
    "Ronde van Vlaanderen":     "https://www.procyclingstats.com/race/ronde-van-vlaanderen/2026/startlist",
    "Scheldeprijs":             "https://www.procyclingstats.com/race/scheldeprijs/2026/startlist",
    "Paris-Roubaix":            "https://www.procyclingstats.com/race/paris-roubaix/2026/startlist",
    "Ronde van Limburg":        "https://www.procyclingstats.com/race/ronde-van-limburg/2026/startlist",
    "Brabantse Pijl":           "https://www.procyclingstats.com/race/brabantse-pijl/2026/startlist",
    "Amstel Gold Race":         "https://www.procyclingstats.com/race/amstel-gold-race/2026/startlist",
    "La Fleche Wallone":        "https://www.procyclingstats.com/race/la-fleche-wallonne/2026/startlist",
    "Liège-Bastogne-Liège":     "https://www.procyclingstats.com/race/liege-bastogne-liege/2026/startlist",
}

PCS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
    "Referer": "https://www.procyclingstats.com/",
}

# ── Naam hulpfuncties ─────────────────────────────────────────────────────────
def pcs_format(name: str) -> str:
    """
    Zet PCS-formaat "VAN AERT Wout" / "VAN DER POEL Mathieu" om naar
    "Wout Van Aert" / "Mathieu Van Der Poel".
    Alles vóór het eerste woord dat niet volledig hoofdletters is = achternaam.
    """
    if not isinstance(name, str) or not name.strip():
        return ""
    parts = name.strip().split()
    for i, part in enumerate(parts):
        if not part.isupper():
            voornaam = parts[i:]
            achternaam = [p.capitalize() for p in parts[:i]]
            return " ".join(voornaam + achternaam)
    # Alles hoofdletters (geen voornaam?) → capitalize
    return " ".join(p.capitalize() for p in parts)

def normalize_name(name) -> str:
    """Verwijder accenten, speciale tekens, lowercase."""
    if name is None:
        return ""
    try:
        if name != name:  # NaN check
            return ""
    except Exception:
        pass
    if not isinstance(name, str):
        name = str(name)

    replacements = {
        "Æ": "AE", "æ": "ae", "Ø": "O", "ø": "o",
        "Å": "A", "å": "a", "Č": "C", "č": "c",
        "Š": "S", "š": "s", "Đ": "D", "đ": "d",
        "Ž": "Z", "ž": "z", "Ć": "C", "ć": "c",
    }
    for special, replacement in replacements.items():
        name = name.replace(special, replacement)

    name = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("utf-8")
    name = re.sub(r"[^a-zA-Z\s-]", "", name)
    return name.strip().lower()

def all_name_variants(name: str) -> list:
    """
    Geeft alle cyclische rotaties van de naam terug als genormaliseerde strings.
    "Wout Van Aert" → {"wout van aert", "van aert wout", "aert wout van"}
    Zo matchen we ongeacht de volgorde die PCS of de gebruiker gebruikt.
    """
    norm = normalize_name(name)
    words = norm.split()
    if len(words) <= 1:
        return [norm]
    variants = set()
    for i in range(len(words)):
        variants.add(" ".join(words[i:] + words[:i]))
    return list(variants)

def names_match(name_a: str, name_b: str) -> bool:
    """True als twee namen dezelfde persoon zijn (ongeacht volgorde van naamdelen)."""
    variants_a = set(all_name_variants(name_a))
    variants_b = set(all_name_variants(name_b))
    return bool(variants_a & variants_b)

# ── PCS scraping ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800)
def get_startlist_from_pcs(race_name: str) -> list:
    """Scrapt startlijst van PCS. Probeert startlist én results pagina."""
    base_url = PCS_URLS.get(race_name)
    if not base_url:
        return []

    # Probeer startlist-pagina én results-pagina (voor al gereden koersen)
    urls_to_try = [
        base_url,
        base_url.replace("/startlist", ""),
        base_url.replace("/startlist", "/result"),
    ]

    for url in urls_to_try:
        try:
            r = req.get(url, headers=PCS_HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            # Probeer meerdere selectors
            raw_names = [a.text.strip() for a in soup.select("ul.startlist_v4 li a[href*='rider/']")]
            if not raw_names:
                raw_names = [a.text.strip() for a in soup.select("a[href*='/rider/']") if a.text.strip() and a.text.strip()[0].isupper()]
            if raw_names:
                return [pcs_format(n) for n in raw_names if n.strip()]
        except Exception:
            continue
    return []

@st.cache_data(ttl=1800)
def get_all_pcs_riders() -> list:
    """Haalt alle unieke renners op uit alle PCS startlijsten."""
    all_riders = set()
    for race_name in PCS_URLS:
        riders = get_startlist_from_pcs(race_name)
        all_riders.update(riders)
    return sorted(all_riders)

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
    ("Omloop Het Nieuwsblad",    "2026-02-28 11:15", "World Tour"),
    ("Kuurne-Brussel-Kuurne",    "2026-03-01 12:25", "Niet-World Tour"),
    ("GP-Samyn",                 "2026-03-03 12:35", "Niet-World Tour"),
    ("Strade Bianche",           "2026-03-07 11:45", "World Tour"),
    ("Nokere Koerse",            "2026-03-18 12:55", "Niet-World Tour"),
    ("Bredene Koksijde Classic", "2026-03-20 12:21", "Niet-World Tour"),
    ("Milano-Sanremo",           "2026-03-21 10:00", "Monument"),
    ("Classic Brugge-De Panne", "2026-03-25 11:40", "World Tour"),
    ("E3 Harelbeke",             "2026-03-27 12:52", "World Tour"),
    ("Gent-Wevelgem",            "2026-03-29 10:00", "World Tour"),
    ("Dwars door Vlaanderen",    "2026-04-01 12:09", "World Tour"),
    ("Ronde van Vlaanderen",     "2026-04-05 10:00", "Monument"),
    ("Scheldeprijs",             "2026-04-08 13:08", "Niet-World Tour"),
    ("Paris-Roubaix",            "2026-04-12 10:00", "Monument"),
    ("Ronde van Limburg",        "2026-04-15 13:00", "Niet-World Tour"),
    ("Brabantse Pijl",           "2026-04-17 13:32", "Niet-World Tour"),
    ("Amstel Gold Race",         "2026-04-19 11:13", "World Tour"),
    ("La Fleche Wallone",        "2026-04-22 11:50", "World Tour"),
    ("Liège-Bastogne-Liège",     "2026-04-26 10:00", "Monument"),
]

# ── Prijzen laden ─────────────────────────────────────────────────────────────
df_prijzen = load_prijzen_csv()

# ── Renners laden bij opstarten vanuit PCS ────────────────────────────────────
if "all_riders" not in st.session_state:
    with st.spinner("Renners laden vanuit ProCyclingStats..."):
        st.session_state.all_riders = get_all_pcs_riders()

# ── Helpers ───────────────────────────────────────────────────────────────────
def fetch_data(selected_riders):
    results = []
    rider_participation = {rider: 0 for rider in selected_riders}
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    weak_races = {}
    cet = pytz.timezone("Europe/Brussels")
    now = datetime.now(pytz.utc).astimezone(cet).replace(tzinfo=None)

    for race_name, race_date, category in races:
        race_datetime = datetime.strptime(race_date, "%Y-%m-%d %H:%M")
        startlist = get_startlist_from_pcs(race_name)

        if not startlist:
            renners_count = "⚠️ Geen data"
            team_riders = []
        else:
            team_riders = [s for s in selected_riders if any(names_match(s, starter) for starter in startlist)]
            renners_count = len(team_riders)
            for rider in team_riders:
                if race_datetime > now:
                    rider_participation[rider] += 1
                rider_schedule[rider][race_name] = "✅"
            if race_datetime > now and renners_count <= 9:
                weak_races[race_name] = startlist

        results.append({"Wedstrijd": race_name, "Datum": race_date, "Categorie": category, "Aantal renners": str(renners_count)})

    recommended_transfers = {}
    for race, race_riders in weak_races.items():
        for rider in race_riders:
            if not any(names_match(rider, s) for s in selected_riders):
                recommended_transfers[rider] = recommended_transfers.get(rider, 0) + 1

    return results, rider_participation, rider_schedule, recommended_transfers

def fetch_rider_schedule(selected_riders):
    rider_schedule = {rider: {race[0]: "❌" for race in races} for rider in selected_riders}
    for race_name, _, _ in races:
        startlist = get_startlist_from_pcs(race_name)
        for rider in selected_riders:
            if any(names_match(rider, starter) for starter in startlist):
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

def extract_riders_from_paste(text: str, all_riders: list) -> tuple:
    """Haalt rennersnamen uit ruwe geplakte tekst van de wielermanager-site."""
    kandidaten = re.split(r"[,\n]", text)
    kandidaten = [k.strip() for k in kandidaten if k.strip()]

    def is_likely_rider(s: str) -> bool:
        if re.match(r"^€", s): return False
        if re.match(r"^\d+[\./,]?\d*$", s): return False
        if len(s) < 4 or len(s) > 40: return False
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
            "budget", "beheer", "ploeg", "opstelling", "renners", "resterend",
            "geselecteerde", "minicompetitie", "transfers", "klassement",
            "statistieken", "spelregels", "prijzen", "overzicht",
        ]
        s_lower = s.lower()
        if any(tw in s_lower for tw in team_woorden): return False
        if " – " in s or " - " in s: return False
        return True

    kandidaten_gefilterd = [k for k in kandidaten if is_likely_rider(k)]

    # Voorbereken: voor elke bekende renner de gesplitste voornaam/achternaam
    # We beschouwen het LAATSTE woord als doorslaggevend achternaam-deel,
    # maar voor namen met tussenvoegsel (van, de, der...) nemen we alles
    # behalve het allereerste woord als "achternaam-blok".
    TUSSENVOEGSELS = {"van", "de", "der", "den", "du", "le", "la", "di", "del", "von"}

    def split_name(norm: str):
        """Geeft (voornaam_eerste_letter, achternaam_blok) terug."""
        words = norm.split()
        if not words:
            return "", ""
        # Zoek het eerste woord dat GEEN tussenvoegsel is en niet het enige woord
        for i, w in enumerate(words):
            if w not in TUSSENVOEGSELS:
                # Dit is de voornaam (of begin van voornaam)
                voornaam_letter = w[0] if w else ""
                achternaam = " ".join(words[i+1:]) if i + 1 < len(words) else ""
                return voornaam_letter, achternaam
        # Alles is tussenvoegsel (onwaarschijnlijk)
        return words[0][0], " ".join(words[1:])

    def find_best_match_strict(input_name):
        norm_input = normalize_name(input_name)
        words_input = norm_input.split()

        # Probeer alle rotaties van de invoer (voor/achternaam kunnen omgewisseld zijn)
        rotaties = []
        for i in range(len(words_input)):
            rotaties.append(words_input[i:] + words_input[:i])

        for original in all_riders:
            norm_original = normalize_name(original)
            words_orig = norm_original.split()

            for rot in rotaties:
                # Probeer: rot[0] = voornaam, rot[1:] = achternaam
                if len(rot) < 2:
                    continue
                voornaam_letter = rot[0][0] if rot[0] else ""
                achternaam_input = " ".join(rot[1:])

                # Achternaam van de bekende renner bepalen
                _, achternaam_orig = split_name(norm_original)

                if not achternaam_input or not achternaam_orig:
                    continue

                # Achternaam moet exact overeenkomen
                if achternaam_input != achternaam_orig:
                    continue

                # Eerste letter voornaam moet kloppen
                voornaam_letter_orig, _ = split_name(norm_original)
                if voornaam_letter and voornaam_letter_orig and voornaam_letter != voornaam_letter_orig:
                    continue

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
    schedule_met_prijzen = {r + get_rider_price(r): v for r, v in rider_schedule.items()}
    schedule_df = pd.DataFrame.from_dict(schedule_met_prijzen, orient="index")
    st.dataframe(schedule_df)

    st.subheader("🔍 Vergelijk mogelijke transfers")
    available_transfers = [r for r in st.session_state.all_riders if r not in selected_riders]
    transfer_riders = st.multiselect("Voer renners in om hun wedstrijdschema te vergelijken:", available_transfers)
    if transfer_riders:
        with st.spinner("Bezig met ophalen van schema's..."):
            transfer_schedule = fetch_rider_schedule(transfer_riders)
        st.subheader("📅 Wedstrijdschema van mogelijke transfers")
        st.dataframe(pd.DataFrame.from_dict(transfer_schedule, orient="index").sort_index())

    st.subheader("🔄 Voorgestelde transfers voor zwak bezette toekomstige wedstrijden")
    rec_df = pd.DataFrame(
        sorted(recommended_transfers.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal wedstrijden met laag aantal deelnemers"]
    )
    rec_df["Renner"] = rec_df["Renner"].apply(lambda r: r + get_rider_price(r))
    st.dataframe(rec_df.set_index("Renner"))

    st.subheader("🏁 Jouw startlijst per wedstrijd")
    next_race = get_next_race()
    wedstrijd_optie = st.selectbox(
        "Selecteer een wedstrijd:",
        [race[0] for race in races],
        index=[race[0] for race in races].index(next_race)
    )
    if wedstrijd_optie:
        startlist = get_startlist_from_pcs(wedstrijd_optie)
        team_riders = [r for r in selected_riders if any(names_match(r, s) for s in startlist)]
        st.subheader(f"🏁 Jouw renners in {wedstrijd_optie}:")
        if team_riders:
            for rider in sorted(team_riders, key=lambda r: normalize_name(r).split()[-1]):
                st.success(f"✅ **{rider}{get_rider_price(rider)}**")
        else:
            st.warning("🚨 Geen renners van jouw team in deze wedstrijd!")

    st.subheader("📊 Toekomstige deelnames per renner")
    part_df = pd.DataFrame(
        sorted(rider_participation.items(), key=lambda x: x[1], reverse=True),
        columns=["Renner", "Aantal toekomstige deelnames"]
    )
    part_df["Renner"] = part_df["Renner"].apply(lambda r: r + get_rider_price(r))
    st.dataframe(part_df.set_index("Renner"))

    next_race, days, hours, minutes = countdown_to_next_race()
    if next_race:
        st.markdown("---")
        st.subheader(f"⏳ Nog **{days} dagen, {hours} uur en {minutes} minuten** tot **{next_race}**!")
