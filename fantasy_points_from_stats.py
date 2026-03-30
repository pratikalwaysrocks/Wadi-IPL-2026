import pandas as pd
from pathlib import Path
from rapidfuzz import process, fuzz
import re

BASE_DIR = Path(__file__).parent
STATS_FILE = BASE_DIR / "ipl_stats_2026.xlsx"
PLAYERS_FILE = BASE_DIR / "players.csv"
OUTPUT_FILE = BASE_DIR / "IPL_Fantasy_Points.xlsx"

ALIASES = {
    "ms dhoni": "mahendra singh dhoni",
    "m s dhoni": "mahendra singh dhoni",
    "dhoni": "mahendra singh dhoni",
    "gill": "shubman gill",
    "siraj": "mohammed siraj",
    "shami": "mohammed shami",
    "kishan": "ishan kishan",
    "jadeja": "ravindra jadeja",
    "narine": "sunil narine",
    "brevis": "dewald brevis",
}

TEAM_CODES = ["CSK", "MI", "RCB", "KKR", "SRH", "RR", "DC", "PBKS", "GT", "LSG"]

def normalize_name(name):
    name = str(name).strip().lower()
    name = name.replace(".", " ")
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\((csk|mi|rcb|kkr|srh|rr|dc|pbks|gt|lsg)\)", "", name)
    name = re.sub(r"\b(csk|mi|rcb|kkr|srh|rr|dc|pbks|gt|lsg)\b", "", name)
    name = re.sub(r"[-|/]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def canonical_name(name):
    name = normalize_name(name)
    return ALIASES.get(name, name)

def load_players():
    df = pd.read_csv(PLAYERS_FILE)
    df.columns = df.columns.str.strip()

    required = {"Player", "Team", "Role"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"players.csv is missing columns: {missing}")

    df["Player_Original"] = df["Player"].astype(str).str.strip()
    df["Player"] = df["Player"].apply(canonical_name)
    df["Team"] = df["Team"].astype(str).str.strip()
    df["Role"] = df["Role"].astype(str).str.strip().str.upper()

    valid_roles = {"BAT", "BOWL", "AR"}
    bad_roles = df.loc[~df["Role"].isin(valid_roles), "Role"].unique()
    if len(bad_roles) > 0:
        raise ValueError(f"Invalid Role values found: {list(bad_roles)}")

    return df

def load_stats():
    orange = pd.read_excel(STATS_FILE, sheet_name="Orange_Cap")
    purple = pd.read_excel(STATS_FILE, sheet_name="Purple_Cap")

    orange.columns = orange.columns.str.strip()
    purple.columns = purple.columns.str.strip()

    orange_df = orange[["Player", "Runs"]].copy()
    purple_df = purple[["Player", "Wkts"]].copy()

    orange_df["Player"] = orange_df["Player"].apply(canonical_name)
    purple_df["Player"] = purple_df["Player"].apply(canonical_name)

    orange_df["Runs"] = pd.to_numeric(orange_df["Runs"], errors="coerce").fillna(0).astype(int)
    purple_df["Wkts"] = pd.to_numeric(purple_df["Wkts"], errors="coerce").fillna(0).astype(int)

    stats_df = pd.merge(orange_df, purple_df, on="Player", how="outer").fillna(0)
    stats_df["Runs"] = stats_df["Runs"].astype(int)
    stats_df["Wkts"] = stats_df["Wkts"].astype(int)
    return stats_df

def fuzzy_match_players(players_df, stats_df, threshold=80):
    stats_names = stats_df["Player"].tolist()
    resolved_names = []
    match_notes = []

    for player in players_df["Player"]:
        if player in stats_names:
            resolved_names.append(player)
            match_notes.append("exact/alias")
            continue

        match = process.extractOne(player, stats_names, scorer=fuzz.ratio)

        if match and match[1] >= threshold:
            resolved_names.append(match[0])
            match_notes.append(f"fuzzy:{match[1]}")
        else:
            resolved_names.append(player)
            if match and match[1] >= 60:
                match_notes.append(f"possible_mismatch:{match[1]}")
            else:
                match_notes.append("no_stats_yet")

    players_df = players_df.copy()
    players_df["Matched_Player"] = resolved_names
    players_df["Match_Type"] = match_notes
    return players_df

def calculate_points(players_df, stats_df):
    players_df = fuzzy_match_players(players_df, stats_df)

    merged = pd.merge(
        players_df,
        stats_df,
        left_on="Matched_Player",
        right_on="Player",
        how="left",
        suffixes=("_Team", "_Stats")
    ).fillna(0)

    merged["Runs"] = pd.to_numeric(merged["Runs"], errors="coerce").fillna(0).astype(int)
    merged["Wkts"] = pd.to_numeric(merged["Wkts"], errors="coerce").fillna(0).astype(int)

    merged["Batting_Points"] = 0
    merged["Bowling_Points"] = 0

    merged.loc[merged["Role"] == "BAT", "Batting_Points"] = merged["Runs"]
    merged.loc[merged["Role"] == "BOWL", "Bowling_Points"] = merged["Wkts"] * 20

    merged.loc[merged["Role"] == "AR", "Batting_Points"] = merged["Runs"]
    merged.loc[merged["Role"] == "AR", "Bowling_Points"] = merged["Wkts"] * 20

    merged["Points"] = merged["Batting_Points"] + merged["Bowling_Points"]

    final_df = merged[[
        "Player_Original", "Team", "Role", "Matched_Player", "Match_Type",
        "Runs", "Wkts", "Batting_Points", "Bowling_Points", "Points"
    ]].copy()
    final_df = final_df.rename(columns={"Player_Original": "Player"})
    return final_df

def build_leaderboard(points_df):
    leaderboard = (
        points_df.groupby("Team", as_index=False)["Points"]
        .sum()
        .sort_values("Points", ascending=False)
        .reset_index(drop=True)
    )
    leaderboard.index = leaderboard.index + 1
    leaderboard.insert(0, "Rank", leaderboard.index)
    return leaderboard

def main():
    players_df = load_players()
    stats_df = load_stats()
    points_df = calculate_points(players_df, stats_df)
    leaderboard_df = build_leaderboard(points_df)

    no_stats_df = points_df[points_df["Match_Type"] == "no_stats_yet"].copy()
    mismatch_df = points_df[points_df["Match_Type"].astype(str).str.contains("possible_mismatch")].copy()

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        points_df.to_excel(writer, sheet_name="Player_Points", index=False)
        leaderboard_df.to_excel(writer, sheet_name="Leaderboard", index=False)
        stats_df.to_excel(writer, sheet_name="Merged_Stats", index=False)
        no_stats_df.to_excel(writer, sheet_name="No_Stats_Yet", index=False)
        mismatch_df.to_excel(writer, sheet_name="Possible_Mismatch", index=False)

    print(f"Saved: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
