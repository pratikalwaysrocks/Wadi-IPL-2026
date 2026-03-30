from pathlib import Path
import subprocess
import sys
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

BASE_DIR = Path(__file__).parent
WORKBOOK = BASE_DIR / "IPL_Fantasy_Points.xlsx"
DASHBOARD = BASE_DIR / "IPL_Fantasy_Dashboard.xlsx"

st.set_page_config(page_title="IPL Fantasy Dashboard", layout="wide")
st_autorefresh(interval=300000, key="ipl_refresh")  # 5 minutes

def load_sheet(sheet_name):
    try:
        return pd.read_excel(WORKBOOK, sheet_name=sheet_name)
    except ValueError:
        # Sheet doesn't exist → return empty dataframe
        return pd.DataFrame()

def run_refresh():
    subprocess.run([sys.executable, str(BASE_DIR / "run_full_system.py")], cwd=BASE_DIR)

st.title("IPL Fantasy Live Dashboard")
col1, col2 = st.columns([3,1])
with col1:
    st.caption("Auto-refresh every 5 minutes")
with col2:
    if st.button("Refresh now"):
        run_refresh()
        st.success("Refresh started. Reload in a few seconds.")

leaderboard = load_sheet("Leaderboard")
players = load_sheet("Player_Points")
stats = load_sheet("Merged_Stats")
no_stats = load_sheet("No_Stats_Yet")
mismatch = load_sheet("Possible_Mismatch")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Teams", len(leaderboard) if not leaderboard.empty else 0)
k2.metric("Tracked Players", len(players) if not players.empty else 0)
k3.metric("Players With Points", int((players["Points"] > 0).sum()) if not players.empty else 0)
k4.metric("Possible Mismatches", len(mismatch) if not mismatch.empty else 0)

if not leaderboard.empty:
    st.subheader("Leaderboard")
    st.bar_chart(leaderboard.set_index("Team")["Points"])
    st.dataframe(leaderboard, use_container_width=True, hide_index=True)

tab1, tab2, tab3, tab4 = st.tabs(["Player Points", "No Stats Yet", "Possible Mismatch", "Merged Stats"])
with tab1:
    st.dataframe(players, use_container_width=True, hide_index=True)
with tab2:
    st.dataframe(no_stats, use_container_width=True, hide_index=True)
with tab3:
    st.dataframe(mismatch, use_container_width=True, hide_index=True)
with tab4:
    st.dataframe(stats, use_container_width=True, hide_index=True)

st.markdown(f"**Workbook file:** `{WORKBOOK.name}`")
if DASHBOARD.exists():
    st.markdown(f"**Excel dashboard file:** `{DASHBOARD.name}`")
