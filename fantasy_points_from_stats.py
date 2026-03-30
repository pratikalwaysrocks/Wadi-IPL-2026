import pandas as pd
from pathlib import Path
from rapidfuzz import process, fuzz
import re
from typing import Optional, Tuple

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

TEAM_CODES = ["CSK", "MI", "RCB", "KKR", "SRH", "RR", "DC", "PBKS", "GT", "LSG"]

# Names that should NEVER be auto-fuzzy-matched to someone else
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

# Optional manual hard-block wrong pairs
BLOCKED_MATCH_PAIRS = {
    ("akshat raghuvanshi", "angkrish raghuvanshi"),
    ("angkrish raghuvanshi", "akshat raghuvanshi"),
    ("jitesh sharma", "brijesh sharma"),
    ("brijesh sharma", "jitesh sharma"),
}


def normalize_name(name: str) -> str:
    name = str(name).strip().lower()
    name = name.replace(".", " ")
    name = re.sub(r"\s+", " ", name)

    # remove bracketed team codes
    name = re.sub(r"\((csk|mi|rcb|kkr|srh|rr|dc|pbks|gt|lsg)\)", "", name)

    # remove standalone team codes
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
    return last_token(a) != "" and last_token(a) == last_token(b)


def same_first_initial(a: str, b: str) -> bool:
    fa = first_token(a)
    fb = first_token(b)
    return bool(fa and fb and fa[0] == fb[0])


def same_first_name(a: str, b: str) -> bool:
    return first_token(a) != "" and first_token(a) == first_token(b)


def token_overlap_ratio(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def is_blocked_pair(a: str, b: str) -> bool:
    a = canonical_name(a)
    b = canonical_name(b)
    return (a, b) in BLOCKED_MATCH_PAIRS


def first_name_similarity(a: str, b: str) -> int:
    return fuzz.ratio(first_token(a), first_token(b))


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

    # for common surnames, require very strong first-name match
    if surname in COMMON_SURNAMES:
        return first_name_similarity(player, candidate) >= 90

    # for rarer surnames, allow strong fuzzy first-name similarity
    return first_name_similarity(player, candidate) >= 85


def ai_style_match(player: str, stats_names: list[str]) -> Tuple[Optional[str], str]:
    player = canonical_name(player)

    # 1. exact
    if player in stats_names:
        return player, "exact/alias"

    # 2. initials/full-name structured exact candidate
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

        if passes_structure_guard(player, candidate):
            overlap = token_overlap_ratio(player, candidate)

            # strongest acceptance only
            if score >= 94:
                return candidate, f"ai_fuzzy_strong:{score}"

            if score >= 90 and overlap >= 0.5:
                return candidate, f"ai_fuzzy:{score}"

        if score >= 75:
            return None, f"possible_mismatch:{score}"

    return None, "no_stats_yet"


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

    # collapse duplicates safely if any source repeats a player
    stats_df = (
        stats_df.groupby("Player", as_index=False)[["Runs", "Wkts"]]
        .max()
    )

    return stats_df


def match_players(players_df, stats_df):
    stats_names = stats_df["Player"].tolist()
    resolved_names = []
    match_notes = []

    for player in players_df["Player"]:
        matched_name, note = ai_style_match(player, stats_names)
        resolved_names.append(matched_name if matched_name is not None else player)
        match_notes.append(note)

    out = players_df.copy()
    out["Matched_Player"] = resolved_names
    out["Match_Type"] = match_notes
    return out


def calculate_points(players_df, stats_df):
    players_df = match_players(players_df, stats_df)

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
        "Player_Original",
        "Team",
        "Role",
        "Matched_Player",
        "Match_Type",
        "Runs",
        "Wkts",
        "Batting_Points",
        "Bowling_Points",
        "Points",
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