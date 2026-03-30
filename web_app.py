from pathlib import Path
import os
import datetime
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

BASE_DIR = Path(__file__).parent
WORKBOOK = BASE_DIR / "IPL_Fantasy_Points.xlsx"
DASHBOARD = BASE_DIR / "IPL_Fantasy_Dashboard.xlsx"

st.set_page_config(page_title="IPL Fantasy Dashboard", layout="wide")
st_autorefresh(interval=300000, key="ipl_refresh")  # 5 minutes


@st.cache_data(ttl=300)
def load_sheet(sheet_name):
    try:
        return pd.read_excel(WORKBOOK, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


def format_timestamp(path: Path) -> str:
    if not path.exists():
        return "Not available"
    ts = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def safe_points_count(df: pd.DataFrame) -> int:
    if df.empty or "Points" not in df.columns:
        return 0
    return int((pd.to_numeric(df["Points"], errors="coerce").fillna(0) > 0).sum())


def apply_filters(df: pd.DataFrame, selected_team: str, search_text: str) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    if selected_team != "All Teams" and "Team" in out.columns:
        out = out[out["Team"] == selected_team]

    if search_text:
        mask = pd.Series(False, index=out.index)
        for col in ["Player", "Matched_Player", "Team", "Role", "Match_Type"]:
            if col in out.columns:
                mask = mask | out[col].astype(str).str.contains(search_text, case=False, na=False)
        out = out[mask]

    return out


st.title("🏏 IPL Fantasy Live Dashboard")

top_left, top_right = st.columns([3, 1])
with top_left:
    st.caption("Auto-refresh every 5 minutes")
with top_right:
    st.caption(f"Last updated: {format_timestamp(WORKBOOK)}")

leaderboard = load_sheet("Leaderboard")
players = load_sheet("Player_Points")
stats = load_sheet("Merged_Stats")
no_stats = load_sheet("No_Stats_Yet")
mismatch = load_sheet("Possible_Mismatch")
ai_matches = load_sheet("AI_Matches")

all_teams = ["All Teams"]
if not players.empty and "Team" in players.columns:
    all_teams += sorted(players["Team"].dropna().astype(str).unique().tolist())

filter_col1, filter_col2 = st.columns([1, 2])
with filter_col1:
    selected_team = st.selectbox("Filter by Team", all_teams)
with filter_col2:
    search_text = st.text_input("Search Player / Match Type / Team")

filtered_players = apply_filters(players, selected_team, search_text)
filtered_no_stats = apply_filters(no_stats, selected_team, search_text)
filtered_mismatch = apply_filters(mismatch, selected_team, search_text)
filtered_ai = apply_filters(ai_matches, selected_team, search_text)

leader_name = "-"
leader_points = 0
if not leaderboard.empty and "Team" in leaderboard.columns and "Points" in leaderboard.columns:
    top_row = leaderboard.iloc[0]
    leader_name = str(top_row["Team"])
    leader_points = int(top_row["Points"])

top_player = "-"
top_player_points = 0
if not players.empty and "Player" in players.columns and "Points" in players.columns:
    temp = players.copy()
    temp["Points"] = pd.to_numeric(temp["Points"], errors="coerce").fillna(0)
    if not temp.empty:
        top_player_row = temp.sort_values("Points", ascending=False).iloc[0]
        top_player = str(top_player_row["Player"])
        top_player_points = int(top_player_row["Points"])

k1, k2, k3, k4 = st.columns(4)
k1.metric("👑 Leading Team", leader_name, leader_points if leader_points else None)
k2.metric("📊 Tracked Players", len(players) if not players.empty else 0)
k3.metric("🔥 Players With Points", safe_points_count(players))
k4.metric("🤖 AI Matches", len(ai_matches) if not ai_matches.empty else 0)

k5, k6, k7, k8 = st.columns(4)
k5.metric("⭐ Top Player", top_player, top_player_points if top_player_points else None)
k6.metric("⚠️ Possible Mismatch", len(mismatch) if not mismatch.empty else 0)
k7.metric("⏳ No Stats Yet", len(no_stats) if not no_stats.empty else 0)
k8.metric("🏆 Teams", len(leaderboard) if not leaderboard.empty else 0)

if not leaderboard.empty and "Team" in leaderboard.columns and "Points" in leaderboard.columns:
    st.subheader("Leaderboard")
    chart_df = leaderboard.copy()
    chart_df["Points"] = pd.to_numeric(chart_df["Points"], errors="coerce").fillna(0)
    st.bar_chart(chart_df.set_index("Team")["Points"])
    st.dataframe(leaderboard, use_container_width=True, hide_index=True)

tabs = st.tabs([
    "Player Points",
    "AI Matches",
    "Possible Mismatch",
    "No Stats Yet",
    "Merged Stats"
])

with tabs[0]:
    st.subheader("Player Points")
    if filtered_players.empty:
        st.info("No player data found for this filter.")
    else:
        st.dataframe(filtered_players, use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader("AI Matches")
    st.caption("Players matched by structured / AI-style guarded matching logic.")
    if filtered_ai.empty:
        st.success("No AI-matched rows found.")
    else:
        st.dataframe(filtered_ai, use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Possible Mismatch")
    st.caption("These rows need manual review. They were not accepted as safe matches.")
    if filtered_mismatch.empty:
        st.success("No possible mismatches found.")
    else:
        st.dataframe(filtered_mismatch, use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("No Stats Yet")
    st.caption("These players have not appeared in the source stats yet, or have no runs/wickets recorded there.")
    if filtered_no_stats.empty:
        st.info("No players in No Stats Yet for this filter.")
    else:
        st.dataframe(filtered_no_stats, use_container_width=True, hide_index=True)

with tabs[4]:
    st.subheader("Merged Stats")
    filtered_stats = stats.copy()
    if selected_team != "All Teams" and not players.empty and "Player" in players.columns and "Team" in players.columns:
        valid_players = players.loc[players["Team"] == selected_team, "Matched_Player"] if "Matched_Player" in players.columns else players.loc[players["Team"] == selected_team, "Player"]
        if "Player" in filtered_stats.columns:
            filtered_stats = filtered_stats[filtered_stats["Player"].isin(valid_players.astype(str).tolist())]

    if search_text and "Player" in filtered_stats.columns:
        filtered_stats = filtered_stats[
            filtered_stats["Player"].astype(str).str.contains(search_text, case=False, na=False)
        ]

    if filtered_stats.empty:
        st.info("No merged stats found for this filter.")
    else:
        st.dataframe(filtered_stats, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown(f"**Workbook file:** `{WORKBOOK.name}`")
if DASHBOARD.exists():
    st.markdown(f"**Excel dashboard file:** `{DASHBOARD.name}`")