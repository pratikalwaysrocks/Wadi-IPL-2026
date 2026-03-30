import re
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
OUTPUT_XLSX = BASE_DIR / "ipl_stats_2026.xlsx"
MYKHEL_URL = "https://www.mykhel.com/cricket/ipl-stats-s4/"


def clean_player_name(name: str) -> str:
    name = str(name).strip()
    name = re.sub(r"\s*\([A-Z]+\)\s*$", "", name)  # remove trailing team code like (MI)
    name = re.sub(r"^\[\d+\]\s*", "", name)        # remove leading link refs if any
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def normalize_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


def find_block_after_header(lines: list[str], header_keywords: list[str], stop_keywords: list[str]) -> list[str]:
    start_idx = None

    for i, line in enumerate(lines):
        lower = line.lower()
        if all(k.lower() in lower for k in header_keywords):
            start_idx = i + 1
            break

    if start_idx is None:
        return []

    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        lower = lines[i].lower()
        if any(stop.lower() in lower for stop in stop_keywords):
            end_idx = i
            break

    return lines[start_idx:end_idx]


def next_useful_line(lines: list[str], idx: int) -> tuple[int, str]:
    while idx < len(lines):
        line = lines[idx].strip()
        lower = line.lower()

        if not line:
            idx += 1
            continue

        if "image:" in lower:
            idx += 1
            continue

        if "player head" in lower:
            idx += 1
            continue

        if "pos player" in lower:
            idx += 1
            continue

        return idx, line

    return idx, ""


def parse_batting_section(lines: list[str]) -> pd.DataFrame:
    rows = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line.isdigit():
            i += 1
            continue

        pos = int(line)

        j, player_line = next_useful_line(lines, i + 1)
        if not player_line:
            break

        player = clean_player_name(player_line)

        k, stats_line = next_useful_line(lines, j + 1)
        if not stats_line:
            break

        parts = stats_line.split()
        # MATCHES INN RUNS SR 4s 6s
        if len(parts) < 6:
            i = k + 1
            continue

        matches, inns, runs, sr, fours, sixes = parts[:6]

        rows.append({
            "POS": pos,
            "Player": player,
            "Matches": matches,
            "Inns": inns,
            "Runs": runs,
            "SR": sr,
            "4s": fours,
            "6s": sixes,
        })

        i = k + 1

    df = pd.DataFrame(rows)
    if not df.empty:
        df["POS"] = pd.to_numeric(df["POS"], errors="coerce")
        df["Matches"] = pd.to_numeric(df["Matches"], errors="coerce")
        df["Inns"] = pd.to_numeric(df["Inns"], errors="coerce")
        df["Runs"] = pd.to_numeric(df["Runs"], errors="coerce")
        df["SR"] = pd.to_numeric(df["SR"].replace("-", None), errors="coerce")
        df["4s"] = pd.to_numeric(df["4s"].replace("-", 0), errors="coerce").fillna(0).astype(int)
        df["6s"] = pd.to_numeric(df["6s"].replace("-", 0), errors="coerce").fillna(0).astype(int)
    return df


def parse_bowling_section(lines: list[str]) -> pd.DataFrame:
    rows = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line.isdigit():
            i += 1
            continue

        pos = int(line)

        j, player_line = next_useful_line(lines, i + 1)
        if not player_line:
            break

        player = clean_player_name(player_line)

        k, stats_line = next_useful_line(lines, j + 1)
        if not stats_line:
            break

        parts = stats_line.split()
        # MATCHES INN BALLS WKTS 5Wkts
        if len(parts) < 5:
            i = k + 1
            continue

        matches, inns, balls, wkts, five_wkts = parts[:5]

        rows.append({
            "POS": pos,
            "Player": player,
            "Matches": matches,
            "Inns": inns,
            "Balls": balls,
            "Wkts": wkts,
            "5Wkts": five_wkts,
        })

        i = k + 1

    df = pd.DataFrame(rows)
    if not df.empty:
        df["POS"] = pd.to_numeric(df["POS"], errors="coerce")
        df["Matches"] = pd.to_numeric(df["Matches"], errors="coerce")
        df["Inns"] = pd.to_numeric(df["Inns"], errors="coerce")
        df["Balls"] = pd.to_numeric(df["Balls"], errors="coerce")
        df["Wkts"] = pd.to_numeric(df["Wkts"], errors="coerce")
        df["5Wkts"] = pd.to_numeric(df["5Wkts"].replace("-", 0), errors="coerce").fillna(0).astype(int)
    return df


def dismiss_cookies(page):
    for text in ["Accept", "I Agree", "Continue", "Got it"]:
        try:
            page.get_by_text(text, exact=False).first.click(timeout=2000)
            page.wait_for_timeout(1000)
            return
        except Exception:
            pass


def get_body_lines(page) -> list[str]:
    text = page.locator("body").inner_text()
    return normalize_lines(text)


def click_bowling_tab(page):
    # Try text click first
    try:
        page.get_by_text("Bowling", exact=True).last.click(timeout=5000)
        page.wait_for_timeout(3000)
        return
    except Exception:
        pass

    # JS fallback
    page.evaluate("""
        () => {
            const nodes = Array.from(document.querySelectorAll('a, button, span, div'));
            const target = nodes.find(el =>
                el.offsetParent !== null &&
                (el.textContent || '').trim().toLowerCase() === 'bowling'
            );
            if (target) target.click();
        }
    """)
    page.wait_for_timeout(3000)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 2200},
            locale="en-US",
        )
        page = context.new_page()

        print("Fetching MyKhel IPL stats page in browser...")
        page.goto(MYKHEL_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        dismiss_cookies(page)

        # Batting block from default view
        batting_lines_all = get_body_lines(page)
        batting_lines = find_block_after_header(
            batting_lines_all,
            header_keywords=["POS", "PLAYER", "MATCHES", "INN", "RUNS", "SR", "4s", "6s"],
            stop_keywords=[
                "Most Wickets",
                "Best Average",
                "Most Five-Wicket",
                "Best Economy",
                "Team Runs Scored",
            ],
        )

        print(f"Batting block lines: {len(batting_lines)}")

        # Switch to Bowling and read page again
        click_bowling_tab(page)
        bowling_lines_all = get_body_lines(page)
        bowling_lines = find_block_after_header(
            bowling_lines_all,
            header_keywords=["POS", "PLAYER", "MATCHES", "INN", "BALLS", "WKTS", "5Wkts"],
            stop_keywords=[
                "Best Average",
                "Most Five-Wicket",
                "Best Economy",
                "Team Runs Scored",
                "Player Comparison",
            ],
        )

        print(f"Bowling block lines: {len(bowling_lines)}")

        orange_df = parse_batting_section(batting_lines)
        purple_df = parse_bowling_section(bowling_lines)

        browser.close()

    if orange_df.empty:
        raise ValueError("Could not parse batting stats from MyKhel page text.")
    if purple_df.empty:
        raise ValueError("Could not parse bowling stats from MyKhel page text.")

    print(f"Orange rows: {len(orange_df)}")
    print("Orange columns:", list(orange_df.columns))
    print(f"Purple rows: {len(purple_df)}")
    print("Purple columns:", list(purple_df.columns))

    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        orange_df.to_excel(writer, sheet_name="Orange_Cap", index=False)
        purple_df.to_excel(writer, sheet_name="Purple_Cap", index=False)

    print(f"Saved: {OUTPUT_XLSX}")
    print("Sheets: Orange_Cap, Purple_Cap")


if __name__ == "__main__":
    main()