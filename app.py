 
import streamlit as st
import pandas as pd
import zipfile
import time
from seleniumbase import Driver

st.set_page_config(page_title="Understat Scraper", layout="wide")
st.title("Understat Scraper")

# -------------------------
# LEAGUE / SEASON
# -------------------------
league_map = {
    "EPL": "EPL",
    "La Liga": "La_liga",
    "Serie A": "Serie_A",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue_1",
    "RFPL": "RFPL"
}

league_name = st.selectbox("Select League", list(league_map.keys()))
season = st.selectbox("Select Season", [str(y) for y in range(2014, 2027)])

league = league_map[league_name]
url = f"https://understat.com/league/{league}/{season}"

st.write("League URL:", url)


# =====================================
# GET MATCH IDS 
# =====================================
def get_match_ids(driver, url):

    driver.get(url)
    time.sleep(4)

    js = r"""
    return (function () {
        try {

            let matches = window.datesData || datesData;

            if (!matches) return null;

            // decode if string
            if (typeof matches === "string") {

                let data = matches;

                try {
                    matches = JSON.parse(data);
                } catch (e) {
                    data = data.replace(/-/g, "+").replace(/_/g, "/");
                    while (data.length % 4) data += "=";
                    matches = JSON.parse(atob(data));
                }
            }

            if (!Array.isArray(matches)) return null;

            const ids = matches.map(m => m.id).filter(Boolean);

            return {
                firstId: ids[0],
                lastId: ids[ids.length - 1],
                ids: ids
            };

        } catch (e) {
            return null;
        }
    })();
    """

    return driver.execute_script(js)


# =====================================
# SCRAPE MATCH  
# =====================================
def scrape_match(driver, match_id):

    driver.get(f"https://understat.com/match/{match_id}")

# wait for JS objects
shots = None
info = None

for _ in range(15):

    try:
        shots = driver.execute_script("""
            return typeof shotsData !== 'undefined'
            ? shotsData
            : null;
        """)

        info = driver.execute_script("""
            return typeof match_info !== 'undefined'
            ? match_info
            : null;
        """)

        if shots and info:
            break

    except:
        pass

    time.sleep(1)

if not shots or not info:
    return None

    h_team = info.get("team_h")
    a_team = info.get("team_a")
    h_team_id = info.get("h")
    a_team_id = info.get("a")
    date = info.get("date")
    league = info.get("league")
    season = info.get("season")

    rows = []

    # -----------------------------
    # FLATTEN SHOTS
    # -----------------------------
    events = []

    for side in ["h", "a"]:
        for s in shots.get(side, []):

            try:
                minute = int(str(s.get("minute", 0)).split("+")[0])
            except:
                minute = 0

            try:
                xg = float(s.get("xG", 0))
            except:
                xg = 0.0

            events.append({
                "type": "shot",
                "minute": minute,
                "side": side,
                "player": s.get("player"),
                "result": s.get("result"),
                "xG": xg,
                "X": s.get("X"),
                "Y": s.get("Y"),
                "player_id": s.get("player_id")
            })

    # -----------------------------
    # CARD EVENTS 
    # -----------------------------
    cards = driver.execute_script("""
        let out = [];
        document.querySelectorAll('.timeline-item').forEach(el => {

            let timeEl = el.querySelector('.timeline-time span');
            if (!timeEl) return;

            let min = parseInt(timeEl.innerText.replace("'", "").split('+')[0]);

            let type = null;
            if (el.querySelector('.yellow-card')) type = "Yellow";
            if (el.querySelector('.red-card')) type = "Red";

            if (!type) return;

            let side = el.classList.contains("timeline-item-right") ? "a" : "h";

            out.push({
                type: "card",
                minute: min,
                side: side,
                card: type
            });
        });
        return out;
    """)

    for c in cards:
        events.append(c)

    # -----------------------------
    # SORT EVENTS 
    # -----------------------------
    events.sort(key=lambda x: int(x.get("minute", 0)))

    # -----------------------------
    # STATE VARIABLES
    # -----------------------------
    h_score = a_score = 0
    h_xg = a_xg = 0.0

    h_yellow = h_red = 0
    a_yellow = a_red = 0

    for e in events:

        if e["type"] == "shot":

            if e["side"] == "h":
                h_xg += e["xG"]
            else:
                a_xg += e["xG"]

            if e["result"] == "Goal":
                if e["side"] == "h":
                    h_score += 1
                else:
                    a_score += 1

        elif e["type"] == "card":

            if e["card"] == "Yellow":
                if e["side"] == "h":
                    h_yellow += 1
                else:
                    a_yellow += 1

            if e["card"] == "Red":
                if e["side"] == "h":
                    h_red += 1
                else:
                    a_red += 1

        # -----------------------------
        # BUILD ROW ONLY FOR SHOTS
        # -----------------------------
        if e["type"] == "shot":

            rows.append({
                "match_id": match_id,
                "league": league,
                "season": season,
                "date": date,
                "minute": e["minute"],
                "player": e["player"],
                "side": e["side"],
                "result": e["result"],
                "xG": e["xG"],
                "Home_Score": h_score,
                "Away_Score": a_score,
                "Home_Cum_xG": round(h_xg, 4),
                "Away_Cum_xG": round(a_xg, 4),
                "Home_Yellow_Cards": h_yellow,
                "Home_Red_Cards": h_red,
                "Away_Yellow_Cards": a_yellow,
                "Away_Red_Cards": a_red,
                "X": e["X"],
                "Y": e["Y"],
                "h_team": h_team,
                "a_team": a_team,
                "h_team_id": h_team_id,
                "a_team_id": a_team_id,
                "player_id": e["player_id"]
            })

    return pd.DataFrame(rows)


# =====================================
# MAIN BUTTON
# =====================================
if st.button("Scrape"):

    driver = Driver(
        browser="chrome",
        headless=True
    )

    all_files = []

    try:
        result = get_match_ids(driver, url)

        if not result:
            st.error("Could not extract match IDs")
            st.stop()

        first_id = int(result["firstId"])
        last_id = int(result["lastId"])

        st.success("Match IDs extracted")
        # st.write("First ID:", first_id)
        # st.write("Last ID:", last_id)

        step = 1 if last_id >= first_id else -1
        match_ids = list(range(first_id, last_id + step, step))

        progress = st.progress(0)

        for i, mid in enumerate(match_ids):

            df = scrape_match(driver, mid)

            if df is not None and not df.empty:
                fname = f"match_{mid}.csv"
                df.to_csv(fname, index=False)
                all_files.append(fname)

            progress.progress((i + 1) / len(match_ids))

        zip_name = f"{league}_{season}.zip"

        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as z:
            for f in all_files:
                z.write(f)

        with open(zip_name, "rb") as f:
            st.download_button(
                "Download ZIP",
                f,
                file_name=zip_name,
                mime="application/zip"
            )

    finally:
        driver.quit()
