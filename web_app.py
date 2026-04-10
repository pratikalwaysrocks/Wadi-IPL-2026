from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    AUTO_REFRESH_AVAILABLE = True
except Exception:
    AUTO_REFRESH_AVAILABLE = False

try:
    import altair as alt
    ALTAIR_AVAILABLE = True
except Exception:
    ALTAIR_AVAILABLE = False


BASE_DIR = Path(__file__).parent
WORKBOOK = BASE_DIR / "IPL_Fantasy_Points.xlsx"
STATS_WORKBOOK = BASE_DIR / "ipl_stats_2026.xlsx"

# Optional supporting files for premium features
HISTORY_FILE = BASE_DIR / "leaderboard_history.csv"
PLAYER_HISTORY_FILE = BASE_DIR / "player_points_history.csv"
STATUS_FILE = BASE_DIR / "update_status.json"
LOG_FILE = BASE_DIR / "auto_update.log"


st.set_page_config(
    page_title="IPL Fantasy Live Dashboard",
    page_icon="🏏",
    layout="wide",
)


# ----------------------------
# Styling
# ----------------------------
st.markdown(
    """
    <style>
        .main > div {
            padding-top: 1rem;
        }
        .metric-card {
            background: linear-gradient(135deg, #121826 0%, #1e293b 100%);
            border: 1px solid rgba(255,255,255,0.08);
            padding: 1rem 1.1rem;
            border-radius: 18px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.18);
            min-height: 110px;
        }
        .metric-label {
            color: #cbd5e1;
            font-size: 0.95rem;
            margin-bottom: 0.35rem;
        }
        .metric-value {
            color: white;
            font-size: 1.75rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .metric-sub {
            color: #94a3b8;
            font-size: 0.88rem;
            margin-top: 0.35rem;
        }
        .section-card {
            background: #0f172a;
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 18px;
            padding: 1rem 1rem 0.6rem 1rem;
            margin-bottom: 1rem;
        }
        .pill-ok {
            display: inline-block;
            padding: 0.18rem 0.6rem;
            border-radius: 999px;
            background: rgba(34,197,94,0.15);
            color: #22c55e;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .pill-warn {
            display: inline-block;
            padding: 0.18rem 0.6rem;
            border-radius: 999px;
            background: rgba(245,158,11,0.15);
            color: #f59e0b;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .pill-bad {
            display: inline-block;
            padding: 0.18rem 0.6rem;
            border-radius: 999px;
            background: rgba(239,68,68,0.15);
            color: #ef4444;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .small-note {
            color: #94a3b8;
            font-size: 0.88rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------
# Helpers
# ----------------------------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt_dt(value) -> str:
    if pd.isna(value) or value is None:
        return "—"
    try:
        ts = pd.to_datetime(value, utc=True)
        return ts.tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST")
    except Exception:
        return str(value)


def status_pill(state: str) -> str:
    state_l = str(state).strip().lower()
    if state_l in {"ok", "healthy", "running", "success", "up"}:
        return '<span class="pill-ok">Healthy</span>'
    if state_l in {"warning", "degraded", "stale"}:
        return '<span class="pill-warn">Warning</span>'
    return '<span class="pill-bad">Issue</span>'


@st.cache_data(ttl=60)
def load_excel_sheet(sheet_name: str) -> pd.DataFrame:
    if not WORKBOOK.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(WORKBOOK, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_stats_sheet(sheet_name: str) -> pd.DataFrame:
    if not STATS_WORKBOOK.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(STATS_WORKBOOK, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_status() -> dict:
    if not STATUS_FILE.exists():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def safe_col(df: pd.DataFrame, col: str, default=None):
    if col in df.columns:
        return df[col]
    return default


def get_latest_history_snapshot(history_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if history_df.empty or "snapshot_time" not in history_df.columns:
        return pd.DataFrame(), pd.DataFrame()

    history_df = history_df.copy()
    history_df["snapshot_time"] = pd.to_datetime(history_df["snapshot_time"], utc=True, errors="coerce")
    history_df = history_df.dropna(subset=["snapshot_time"]).sort_values("snapshot_time")

    unique_times = history_df["snapshot_time"].drop_duplicates().sort_values()
    if len(unique_times) == 0:
        return pd.DataFrame(), pd.DataFrame()

    latest_time = unique_times.iloc[-1]
    latest = history_df[history_df["snapshot_time"] == latest_time].copy()

    previous = pd.DataFrame()
    if len(unique_times) >= 2:
        prev_time = unique_times.iloc[-2]
        previous = history_df[history_df["snapshot_time"] == prev_time].copy()

    return latest, previous


def build_rank_change_df(history_df: pd.DataFrame) -> pd.DataFrame:
    latest, previous = get_latest_history_snapshot(history_df)
    if latest.empty:
        return pd.DataFrame()

    if "Team" not in latest.columns or "Points" not in latest.columns:
        return pd.DataFrame()

    latest = latest[["Team", "Points"]].copy().sort_values("Points", ascending=False).reset_index(drop=True)
    latest["Current_Rank"] = latest.index + 1

    if previous.empty or "Team" not in previous.columns or "Points" not in previous.columns:
        latest["Previous_Rank"] = pd.NA
        latest["Rank_Change"] = pd.NA
        return latest

    previous = previous[["Team", "Points"]].copy().sort_values("Points", ascending=False).reset_index(drop=True)
    previous["Previous_Rank"] = previous.index + 1

    merged = latest.merge(previous[["Team", "Previous_Rank"]], on="Team", how="left")
    merged["Rank_Change"] = merged["Previous_Rank"] - merged["Current_Rank"]
    return merged


def build_player_change_df(player_history_df: pd.DataFrame) -> pd.DataFrame:
    latest, previous = get_latest_history_snapshot(player_history_df)
    if latest.empty or "Player" not in latest.columns:
        return pd.DataFrame()

    cols = [c for c in ["Player", "Team", "Role", "Points", "Runs", "Wkts"] if c in latest.columns]
    latest = latest[cols].copy()

    if previous.empty or "Player" not in previous.columns or "Points" not in previous.columns:
        latest["Previous_Points"] = pd.NA
        latest["Point_Change"] = pd.NA
        latest["New_In_Snapshot"] = True
        return latest

    prev_cols = [c for c in ["Player", "Points"] if c in previous.columns]
    previous = previous[prev_cols].copy().rename(columns={"Points": "Previous_Points"})

    merged = latest.merge(previous, on="Player", how="left")
    merged["Point_Change"] = merged["Points"] - merged["Previous_Points"].fillna(0)
    merged["New_In_Snapshot"] = merged["Previous_Points"].isna()
    return merged


def read_last_log_lines(n: int = 20) -> str:
    if not LOG_FILE.exists():
        return "No log file found."
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "Could not read log file."


# ----------------------------
# Auto refresh
# ----------------------------
with st.sidebar:
    st.header("Controls")

    auto_refresh = st.toggle("Auto refresh", value=True)
    refresh_seconds = st.slider("Refresh interval (seconds)", 30, 300, 60, 30)

    if auto_refresh and AUTO_REFRESH_AVAILABLE:
        st_autorefresh(interval=refresh_seconds * 1000, key="premium_refresh")

    st.markdown("---")
    st.subheader("Filters")

player_points_df = load_excel_sheet("Player_Points")
leaderboard_df = load_excel_sheet("Leaderboard")
merged_stats_df = load_excel_sheet("Merged_Stats")
no_stats_df = load_excel_sheet("No_Stats_Yet")
mismatch_df = load_excel_sheet("Possible_Mismatch")

orange_df = load_stats_sheet("Orange_Cap")
purple_df = load_stats_sheet("Purple_Cap")

history_df = load_csv(HISTORY_FILE)
player_history_df = load_csv(PLAYER_HISTORY_FILE)
status_data = load_status()

if WORKBOOK.exists():
    workbook_mtime = datetime.fromtimestamp(WORKBOOK.stat().st_mtime, tz=timezone.utc)
else:
    workbook_mtime = None


# ----------------------------
# Sidebar filters
# ----------------------------
teams = sorted(player_points_df["Team"].dropna().astype(str).unique().tolist()) if not player_points_df.empty and "Team" in player_points_df.columns else []
roles = sorted(player_points_df["Role"].dropna().astype(str).unique().tolist()) if not player_points_df.empty and "Role" in player_points_df.columns else []

with st.sidebar:
    selected_teams = st.multiselect("Team", teams, default=teams)
    selected_roles = st.multiselect("Role", roles, default=roles)
    min_points = st.number_input("Minimum points", min_value=0, value=0, step=10)
    player_search = st.text_input("Search player")
    match_filter = st.selectbox(
        "Match status",
        ["All", "Matched only", "Possible mismatch", "No stats yet"],
        index=0,
    )

filtered_players = player_points_df.copy()

if not filtered_players.empty:
    if selected_teams and "Team" in filtered_players.columns:
        filtered_players = filtered_players[filtered_players["Team"].isin(selected_teams)]

    if selected_roles and "Role" in filtered_players.columns:
        filtered_players = filtered_players[filtered_players["Role"].isin(selected_roles)]

    if "Points" in filtered_players.columns:
        filtered_players = filtered_players[filtered_players["Points"] >= min_points]

    if player_search and "Player" in filtered_players.columns:
        mask = filtered_players["Player"].astype(str).str.contains(player_search, case=False, na=False)
        filtered_players = filtered_players[mask]

    if match_filter == "Matched only" and "Matched_Player" in filtered_players.columns:
        filtered_players = filtered_players[filtered_players["Matched_Player"].astype(str).str.strip() != ""]
    elif match_filter == "Possible mismatch" and "Match_Type" in filtered_players.columns:
        filtered_players = filtered_players[filtered_players["Match_Type"].astype(str).str.contains("possible_mismatch", case=False, na=False)]
    elif match_filter == "No stats yet" and "Match_Type" in filtered_players.columns:
        filtered_players = filtered_players[filtered_players["Match_Type"].astype(str).eq("no_stats_yet")]


# ----------------------------
# Derived metrics
# ----------------------------
leader_name = "—"
leader_points = "—"
if not leaderboard_df.empty and {"Team", "Points"}.issubset(leaderboard_df.columns):
    top_row = leaderboard_df.sort_values("Points", ascending=False).iloc[0]
    leader_name = str(top_row["Team"])
    leader_points = int(top_row["Points"])

top_player_name = "—"
top_player_points = "—"
if not player_points_df.empty and {"Player", "Points"}.issubset(player_points_df.columns):
    ptop = player_points_df.sort_values("Points", ascending=False).iloc[0]
    top_player_name = str(ptop["Player"])
    top_player_points = int(ptop["Points"])

rank_change_df = build_rank_change_df(history_df)
player_change_df = build_player_change_df(player_history_df)

biggest_riser_team = "—"
biggest_riser_change = "—"
if not rank_change_df.empty and "Rank_Change" in rank_change_df.columns:
    rise_candidates = rank_change_df.dropna(subset=["Rank_Change"]).sort_values("Rank_Change", ascending=False)
    if not rise_candidates.empty:
        rise = rise_candidates.iloc[0]
        biggest_riser_team = str(rise["Team"])
        biggest_riser_change = int(rise["Rank_Change"])

last_scrape_time = status_data.get("last_successful_scrape_time") or (fmt_dt(workbook_mtime) if workbook_mtime else "—")
last_push_time = status_data.get("last_successful_git_push_time", "—")
server_status = status_data.get("server_status", "unknown")
source_status = status_data.get("data_source_status", "unknown")


# ----------------------------
# Header
# ----------------------------
st.title("🏏 IPL Fantasy Premium Live Dashboard")
st.caption("Live leaderboard, player movement, trend analytics, and operational status")

# ----------------------------
# Top premium summary cards
# ----------------------------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Current Leader</div>
            <div class="metric-value">{leader_name}</div>
            <div class="metric-sub">{leader_points} points</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Highest Scoring Player</div>
            <div class="metric-value">{top_player_name}</div>
            <div class="metric-sub">{top_player_points} points</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c3:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Biggest Riser</div>
            <div class="metric-value">{biggest_riser_team}</div>
            <div class="metric-sub">Rank change: {biggest_riser_change}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c4:
    matched_count = 0
    if not player_points_df.empty and "Matched_Player" in player_points_df.columns:
        matched_count = int((player_points_df["Matched_Player"].astype(str).str.strip() != "").sum())

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Matched Players</div>
            <div class="metric-value">{matched_count}</div>
            <div class="metric-sub">No Stats Yet: {0 if no_stats_df.empty else len(no_stats_df)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------
# Ops / health status row
# ----------------------------
s1, s2, s3, s4 = st.columns(4)
with s1:
    st.markdown("**Last Successful Scrape**")
    st.markdown(f"<div class='small-note'>{fmt_dt(last_scrape_time)}</div>", unsafe_allow_html=True)

with s2:
    st.markdown("**Last Successful Git Push**")
    st.markdown(f"<div class='small-note'>{fmt_dt(last_push_time)}</div>", unsafe_allow_html=True)

with s3:
    st.markdown("**Server Status**")
    st.markdown(status_pill(server_status), unsafe_allow_html=True)

with s4:
    st.markdown("**Data Source Status**")
    st.markdown(status_pill(source_status), unsafe_allow_html=True)

st.markdown("---")

# ----------------------------
# Charts section
# ----------------------------
left, right = st.columns((1.05, 0.95))

with left:
    st.subheader("Leaderboard")
    if not leaderboard_df.empty and {"Team", "Points"}.issubset(leaderboard_df.columns):
        chart_df = leaderboard_df.sort_values("Points", ascending=True).copy()

        if ALTAIR_AVAILABLE:
            chart = (
                alt.Chart(chart_df)
                .mark_bar(cornerRadiusTopRight=6, cornerRadiusBottomRight=6)
                .encode(
                    x=alt.X("Points:Q"),
                    y=alt.Y("Team:N", sort="-x"),
                    tooltip=["Team", "Points"],
                )
                .properties(height=420)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.bar_chart(chart_df.set_index("Team")["Points"])
    else:
        st.info("Leaderboard data not available.")

with right:
    st.subheader("Team Points Over Time")
    if not history_df.empty and {"snapshot_time", "Team", "Points"}.issubset(history_df.columns):
        hist = history_df.copy()
        hist["snapshot_time"] = pd.to_datetime(hist["snapshot_time"], utc=True, errors="coerce")
        hist = hist.dropna(subset=["snapshot_time"])

        if selected_teams:
            hist = hist[hist["Team"].isin(selected_teams)]

        if ALTAIR_AVAILABLE and not hist.empty:
            chart = (
                alt.Chart(hist)
                .mark_line(point=True)
                .encode(
                    x=alt.X("snapshot_time:T", title="Snapshot Time"),
                    y=alt.Y("Points:Q"),
                    color=alt.Color("Team:N"),
                    tooltip=["Team", "snapshot_time", "Points"],
                )
                .properties(height=420)
            )
            st.altair_chart(chart, use_container_width=True)
        elif not hist.empty:
            pivot = hist.pivot_table(index="snapshot_time", columns="Team", values="Points", aggfunc="max")
            st.line_chart(pivot)
        else:
            st.info("No historical team data after filters.")
    else:
        st.info("History file not found yet. Add `leaderboard_history.csv` for trend charts.")

# ----------------------------
# Secondary analytics row
# ----------------------------
left2, right2 = st.columns(2)

with left2:
    st.subheader("Rank Movement Over Time")
    if not history_df.empty and {"snapshot_time", "Team", "Points"}.issubset(history_df.columns):
        rank_hist = history_df.copy()
        rank_hist["snapshot_time"] = pd.to_datetime(rank_hist["snapshot_time"], utc=True, errors="coerce")
        rank_hist = rank_hist.dropna(subset=["snapshot_time"]).sort_values(["snapshot_time", "Points"], ascending=[True, False])

        rank_hist["Rank"] = rank_hist.groupby("snapshot_time")["Points"].rank(method="dense", ascending=False)

        if selected_teams:
            rank_hist = rank_hist[rank_hist["Team"].isin(selected_teams)]

        if ALTAIR_AVAILABLE and not rank_hist.empty:
            chart = (
                alt.Chart(rank_hist)
                .mark_line(point=True)
                .encode(
                    x=alt.X("snapshot_time:T", title="Snapshot Time"),
                    y=alt.Y("Rank:Q", scale=alt.Scale(reverse=True)),
                    color=alt.Color("Team:N"),
                    tooltip=["Team", "snapshot_time", "Rank", "Points"],
                )
                .properties(height=350)
            )
            st.altair_chart(chart, use_container_width=True)
        elif not rank_hist.empty:
            pivot = rank_hist.pivot_table(index="snapshot_time", columns="Team", values="Rank", aggfunc="min")
            st.line_chart(pivot)
        else:
            st.info("No rank history available after filters.")
    else:
        st.info("History file not found yet.")

with right2:
    st.subheader("Daily Points Added by Team")
    if not history_df.empty and {"snapshot_time", "Team", "Points"}.issubset(history_df.columns):
        daily = history_df.copy()
        daily["snapshot_time"] = pd.to_datetime(daily["snapshot_time"], utc=True, errors="coerce")
        daily = daily.dropna(subset=["snapshot_time"]).sort_values(["Team", "snapshot_time"])
        daily["Date"] = daily["snapshot_time"].dt.date

        daily = (
            daily.groupby(["Date", "Team"], as_index=False)["Points"]
            .max()
            .sort_values(["Team", "Date"])
        )
        daily["Points_Added"] = daily.groupby("Team")["Points"].diff().fillna(0)

        if selected_teams:
            daily = daily[daily["Team"].isin(selected_teams)]

        if ALTAIR_AVAILABLE and not daily.empty:
            chart = (
                alt.Chart(daily)
                .mark_bar()
                .encode(
                    x=alt.X("Date:T"),
                    y=alt.Y("Points_Added:Q", title="Points Added"),
                    color=alt.Color("Team:N"),
                    tooltip=["Team", "Date", "Points_Added"],
                )
                .properties(height=350)
            )
            st.altair_chart(chart, use_container_width=True)
        elif not daily.empty:
            pivot = daily.pivot_table(index="Date", columns="Team", values="Points_Added", aggfunc="sum")
            st.bar_chart(pivot)
        else:
            st.info("No daily delta data after filters.")
    else:
        st.info("Player/team history file not found yet.")

st.markdown("---")

# ----------------------------
# Change detection section
# ----------------------------
st.subheader("Recent Changes")

ch1, ch2 = st.columns(2)

with ch1:
    st.markdown("**Players whose points changed in the last update**")
    if not player_change_df.empty:
        changed = player_change_df[player_change_df["Point_Change"].fillna(0) != 0].copy()
        if selected_teams and "Team" in changed.columns:
            changed = changed[changed["Team"].isin(selected_teams)]
        if selected_roles and "Role" in changed.columns:
            changed = changed[changed["Role"].isin(selected_roles)]
        changed = changed.sort_values("Point_Change", ascending=False)
        show_cols = [c for c in ["Player", "Team", "Role", "Previous_Points", "Points", "Point_Change"] if c in changed.columns]
        st.dataframe(changed[show_cols], use_container_width=True, height=280)
    else:
        st.info("No player history snapshot found yet.")

with ch2:
    st.markdown("**Teams whose rank changed**")
    if not rank_change_df.empty:
        moved = rank_change_df[rank_change_df["Rank_Change"].fillna(0) != 0].copy()
        moved = moved.sort_values("Rank_Change", ascending=False)
        show_cols = [c for c in ["Team", "Points", "Previous_Rank", "Current_Rank", "Rank_Change"] if c in moved.columns]
        st.dataframe(moved[show_cols], use_container_width=True, height=280)
    else:
        st.info("No previous leaderboard snapshot found.")

ch3, ch4 = st.columns(2)

with ch3:
    st.markdown("**New players appearing in stats**")
    if not player_change_df.empty:
        new_players = player_change_df[player_change_df["New_In_Snapshot"] == True].copy()
        if selected_teams and "Team" in new_players.columns:
            new_players = new_players[new_players["Team"].isin(selected_teams)]
        show_cols = [c for c in ["Player", "Team", "Role", "Points", "Runs", "Wkts"] if c in new_players.columns]
        st.dataframe(new_players[show_cols], use_container_width=True, height=250)
    else:
        st.info("No player history snapshot found.")

with ch4:
    st.markdown("**Players moved out of No_Stats_Yet**")
    if not player_change_df.empty and not no_stats_df.empty and "Player" in no_stats_df.columns:
        current_no_stats = set(no_stats_df["Player"].astype(str).tolist())
        moved_out = player_change_df[
            (~player_change_df["Player"].astype(str).isin(current_no_stats))
            & (player_change_df["Previous_Points"].isna() | (player_change_df["Previous_Points"].fillna(0) == 0))
            & (player_change_df["Points"].fillna(0) > 0)
        ].copy()
        show_cols = [c for c in ["Player", "Team", "Role", "Points", "Runs", "Wkts"] if c in moved_out.columns]
        st.dataframe(moved_out[show_cols], use_container_width=True, height=250)
    else:
        st.info("Need both history and No_Stats_Yet data to calculate this.")

st.markdown("---")

# ----------------------------
# Main data explorer
# ----------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "Player Points",
        "Possible Mismatch",
        "No Stats Yet",
        "Raw Stats",
        "System Log",
    ]
)

with tab1:
    st.subheader("Player Points Explorer")
    if filtered_players.empty:
        st.warning("No player data available after filters.")
    else:
        sort_col = st.selectbox("Sort by", [c for c in filtered_players.columns if c in ["Points", "Runs", "Wkts", "Batting_Points", "Bowling_Points", "Player"]], index=0)
        ascending = st.toggle("Ascending", value=False)
        display_df = filtered_players.sort_values(sort_col, ascending=ascending)
        st.dataframe(display_df, use_container_width=True, height=520)

with tab2:
    st.subheader("Possible Mismatch Review")
    if mismatch_df.empty:
        st.success("No possible mismatches found.")
    else:
        review_df = mismatch_df.copy()
        if selected_teams and "Team" in review_df.columns:
            review_df = review_df[review_df["Team"].isin(selected_teams)]
        if selected_roles and "Role" in review_df.columns:
            review_df = review_df[review_df["Role"].isin(selected_roles)]
        st.dataframe(review_df, use_container_width=True, height=520)

with tab3:
    st.subheader("No Stats Yet")
    if no_stats_df.empty:
        st.success("Every player has stats or a resolved match.")
    else:
        review_df = no_stats_df.copy()
        if selected_teams and "Team" in review_df.columns:
            review_df = review_df[review_df["Team"].isin(selected_teams)]
        if selected_roles and "Role" in review_df.columns:
            review_df = review_df[review_df["Role"].isin(selected_roles)]
        st.dataframe(review_df, use_container_width=True, height=520)

with tab4:
    st.subheader("Raw Source Stats")
    sleft, sright = st.columns(2)
    with sleft:
        st.markdown("**Orange Cap / Batting**")
        if orange_df.empty:
            st.info("Orange_Cap sheet not found.")
        else:
            st.dataframe(orange_df, use_container_width=True, height=420)
    with sright:
        st.markdown("**Purple Cap / Bowling**")
        if purple_df.empty:
            st.info("Purple_Cap sheet not found.")
        else:
            st.dataframe(purple_df, use_container_width=True, height=420)

with tab5:
    st.subheader("System Log")
    st.code(read_last_log_lines(30), language="text")

# ----------------------------
# Footer notes
# ----------------------------
st.markdown("---")
st.caption(
    "Premium mode works best when history snapshots are available. "
    "For full trend and movement analytics, store leaderboard and player snapshots on each update cycle."
)
