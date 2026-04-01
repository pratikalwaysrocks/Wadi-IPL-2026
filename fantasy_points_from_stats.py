import re
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
from rapidfuzz import process, fuzz

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

COMMON_SURNAMES = {
    "singh", "sharma", "khan", "yadav", "kumar", "patel", "shah", "ali"
}

STRICT_NO_FUZZY = {
    "akshat raghuvanshi",
    "angkrish raghuvanshi",
    "jitesh sharma",
    "brijesh sharma",
    "arshdeep singh",
    "abhinandan singh",
    "shahrukh khan",
    "sarfaraz khan",
    "ashutosh sharma",
    "abhishek sharma",
}

BLOCKED_MATCH_PAIRS = {
    ("akshat raghuvanshi", "angkrish raghuvanshi"),
    ("angkrish raghuvanshi", "akshat raghuvanshi"),
    ("jitesh sharma", "brijesh sharma"),
    ("brijesh sharma", "jitesh sharma"),
    ("arshdeep singh", "abhinandan singh"),
    ("abhinandan singh", "arshdeep singh"),
    ("shahrukh khan", "sarfaraz khan"),
    ("sarfaraz khan", "shahrukh khan"),
    ("ashutosh sharma", "abhishek sharma"),
    ("abhishek sharma", "ashutosh sharma"),

    # add these too
    ("rashid khan", "avesh khan"),
    ("avesh khan", "rashid khan"),
    ("ashutosh sharma", "ashok sharma"),
    ("ashok sharma", "ashutosh sharma"),
    ("mohammed shami", "mohammed siraj"),
    ("mohammed siraj", "mohammed shami"),
}


def normalize_name(name: str) -> str:
    name = str(name).strip().lower()
    name = name.replace(".", " ")
    name = re.sub(r"\s+", " ", name)

    # remove bracketed IPL team codes like "(MI)"
    name = re.sub(r"\((csk|mi|rcb|kkr|srh|rr|dc|pbks|gt|lsg)\)", "", name)

    # remove standalone IPL team codes
    name = re.sub(r"\b(csk|mi|rcb|kkr|srh|rr|dc|pbks|gt|lsg)\b", "", name)

    # normalize separators
    name = re.sub(r"[-|/]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def canonical_name(name: str) -> str:
    name = normalize_name(name)
    return ALIASES.get(name, name)


def tokenize(name: str) -> list[str]:
    return [t for t in canonical_name(name).split() if t]


def first_token(name: str) -> str:
    parts = tokenize(name)
    return parts[0] if parts else ""


def last_token(name: str) -> str:
    parts = tokenize(name)
    return parts[-1] if parts else ""


def initials(name: str) -> str:
    parts = tokenize(name)
    return "".join(p[0] for p in parts if p)


def same_last_name(a: str, b: str) -> bool:
    return bool(last_token(a)) and last_token(a) == last_token(b)


def same_first_name(a: str, b: str) -> bool:
    return bool(first_token(a)) and first_token(a) == first_token(b)


def token_overlap_ratio(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def first_name_similarity(a: str, b: str) -> int:
    return fuzz.ratio(first_token(a), first_token(b))


def is_blocked_pair(a: str, b: str) -> bool:
    a = canonical_name(a)
    b = canonical_name(b)
    return (a, b) in BLOCKED_MATCH_PAIRS


def passes_structure_guard(player: str, candidate: str) -> bool:
    player = canonical_name(player)
    candidate = canonical_name(candidate)

    if is_blocked_pair(player, candidate):
        return False

    # surname must match
    if not same_last_name(player, candidate):
        return False

    # protected names: only exact match allowed
    if player in STRICT_NO_FUZZY or candidate in STRICT_NO_FUZZY:
        return player == candidate

    player_first = first_token(player)
    candidate_first = first_token(candidate)
    surname = last_token(player)

    # safest path: full first name exact
    if player_first == candidate_first:
        return True

    # common surnames need very strong first-name similarity
    if surname in COMMON_SURNAMES:
        return first_name_similarity(player, candidate) >= 90

    # rarer surnames can allow slightly softer similarity
    return first_name_similarity(player, candidate) >= 85


def ai_style_match(player: str, stats_names: list[str]) -> Tuple[Optional[str], str]:
    player = canonical_name(player)

    # 1. exact / alias
    if player in stats_names:
        return player, "exact/alias"

    # 2. structured initials/full-name match
    player_initials = initials(player)
    strong_candidates = []
    for s in stats_names:
        if same_last_name(player, s):
            if initials(s) == player_initials or same_first_name(player, s):
                strong_candidates.append(s)

    if len(strong_candidates) == 1 and passes_structure_guard(player, strong_candidates[0]):
        return strong_candidates[0], "ai_structured"

    # 3. guarded fuzzy
    match = process.extractOne(player, stats_names, scorer=fuzz.ratio)
    if match:
        candidate, score, _ = match

        # If the candidate is structurally unsafe, do NOT even show it as mismatch
        if not passes_structure_guard(player, candidate):
            return None, "no_stats_yet"

        overlap = token_overlap_ratio(player, candidate)

        if score >= 94:
            return candidate, f"ai_fuzzy_strong:{score}"

        if score >= 90 and overlap >= 0.5:
            return candidate, f"ai_fuzzy:{score}"

        if score >= 80:
            return None, f"possible_mismatch:{score}"

    return None, "no_stats_yet"


def load_players() -> pd.DataFrame:
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


def find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    cols_lower = {str(col).strip().lower(): col for col in df.columns}

    for candidate in candidates:
        candidate_lower = candidate.strip().lower()
        if candidate_lower in cols_lower:
            return cols_lower[candidate_lower]

    for col in df.columns:
        col_lower = str(col).strip().lower()
        for candidate in candidates:
            if candidate.strip().lower() in col_lower:
                return col

    raise KeyError(
        f"Could not find any of these columns: {candidates}. "
        f"Available columns: {list(df.columns)}"
    )


def load_stats() -> pd.DataFrame:
    orange = pd.read_excel(STATS_FILE, sheet_name="Orange_Cap")
    purple = pd.read_excel(STATS_FILE, sheet_name="Purple_Cap")

    orange.columns = orange.columns.str.strip()
    purple.columns = purple.columns.str.strip()

    orange_player_col = find_column(orange, ["Player"])
    orange_runs_col = find_column(orange, ["Runs", "Run", "Most Runs", "RUNS"])

    purple_player_col = find_column(purple, ["Player"])
    purple_wkts_col = find_column(purple, ["Wkts", "Wickets", "WKTS", "Most Wickets"])

    orange_df = orange[[orange_player_col, orange_runs_col]].copy()
    purple_df = purple[[purple_player_col, purple_wkts_col]].copy()

    orange_df.columns = ["Player", "Runs"]
    purple_df.columns = ["Player", "Wkts"]

    orange_df["Player"] = orange_df["Player"].apply(canonical_name)
    purple_df["Player"] = purple_df["Player"].apply(canonical_name)

    orange_df["Runs"] = pd.to_numeric(orange_df["Runs"], errors="coerce").fillna(0).astype(int)
    purple_df["Wkts"] = pd.to_numeric(purple_df["Wkts"], errors="coerce").fillna(0).astype(int)

    stats_df = pd.merge(orange_df, purple_df, on="Player", how="outer").fillna(0)
    stats_df["Runs"] = stats_df["Runs"].astype(int)
    stats_df["Wkts"] = stats_df["Wkts"].astype(int)

    # collapse duplicates safely
    stats_df = (
        stats_df.groupby("Player", as_index=False)[["Runs", "Wkts"]]
        .max()
    )

    return stats_df


def match_players(players_df: pd.DataFrame, stats_df: pd.DataFrame) -> pd.DataFrame:
    stats_names = stats_df["Player"].tolist()

    resolved_names = []
    suggested_names = []
    match_notes = []

    for player in players_df["Player"]:
        matched_name, note = ai_style_match(player, stats_names)

        if matched_name is not None:
            resolved_names.append(matched_name)
            suggested_names.append("")
            match_notes.append(note)
        else:
            resolved_names.append("")
            suggestion = process.extractOne(player, stats_names, scorer=fuzz.ratio)
            suggested_names.append(suggestion[0] if suggestion else "")
            match_notes.append(note)

    out = players_df.copy()
    out["Matched_Player"] = resolved_names
    out["Suggested_Match"] = suggested_names
    out["Match_Type"] = match_notes
    return out


def calculate_points(players_df: pd.DataFrame, stats_df: pd.DataFrame) -> pd.DataFrame:
    players_df = match_players(players_df, stats_df)

    merged = pd.merge(
        players_df,
        stats_df,
        left_on="Matched_Player",
        right_on="Player",
        how="left",
        suffixes=("_Team", "_Stats"),
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

    final_df = merged[
        [
            "Player_Original",
            "Team",
            "Role",
            "Matched_Player",
            "Suggested_Match",
            "Match_Type",
            "Runs",
            "Wkts",
            "Batting_Points",
            "Bowling_Points",
            "Points",
        ]
    ].copy()

    final_df = final_df.rename(columns={"Player_Original": "Player"})
    return final_df


def build_leaderboard(points_df: pd.DataFrame) -> pd.DataFrame:
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
    mismatch_df = points_df[
        points_df["Match_Type"].astype(str).str.contains("possible_mismatch", na=False)
    ].copy()
    ai_matches_df = points_df[
        points_df["Match_Type"].astype(str).str.contains("ai_", na=False)
    ].copy()

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        points_df.to_excel(writer, sheet_name="Player_Points", index=False)
        leaderboard_df.to_excel(writer, sheet_name="Leaderboard", index=False)
        stats_df.to_excel(writer, sheet_name="Merged_Stats", index=False)
        no_stats_df.to_excel(writer, sheet_name="No_Stats_Yet", index=False)
        mismatch_df.to_excel(writer, sheet_name="Possible_Mismatch", index=False)
        ai_matches_df.to_excel(writer, sheet_name="AI_Matches", index=False)

    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()