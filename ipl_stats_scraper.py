import re
from io import StringIO
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
OUTPUT_XLSX = BASE_DIR / "ipl_stats_2026.xlsx"
MYKHEL_URL = "https://www.mykhel.com/cricket/ipl-stats-s4/"


def clean_text(value):
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_text(c) for c in df.columns]
    return df


def dismiss_cookies(page):
    for text in ["Accept", "I Agree", "Continue", "Got it"]:
        try:
            page.get_by_text(text, exact=False).first.click(timeout=2000)
            page.wait_for_timeout(1000)
            return
        except Exception:
            pass


def click_tab(page, tab_name: str) -> bool:
    # try multiple selectors
    selectors = [
        lambda: page.get_by_role("tab", name=tab_name),
        lambda: page.get_by_role("button", name=tab_name),
        lambda: page.get_by_text(tab_name, exact=True),
        lambda: page.get_by_text(tab_name, exact=False),
    ]

    for selector in selectors:
        try:
            loc = selector()
            if loc.count() > 0:
                loc.last.click(timeout=5000, force=True)
                page.wait_for_timeout(3000)
                return True
        except Exception:
            pass

    # JS fallback
    try:
        clicked = page.evaluate(
            """
            (tabName) => {
                const nodes = Array.from(document.querySelectorAll('a, button, div, span, li'));
                const target = nodes.find(el => {
                    if (el.offsetParent === null) return false;
                    const txt = (el.textContent || '').trim().toLowerCase();
                    return txt === tabName.toLowerCase() || txt.includes(tabName.toLowerCase());
                });
                if (target) {
                    target.click();
                    return true;
                }
                return false;
            }
            """,
            tab_name,
        )
        if clicked:
            page.wait_for_timeout(3000)
            return True
    except Exception:
        pass

    return False


def extract_tables_from_html(html: str) -> list[pd.DataFrame]:
    try:
        tables = pd.read_html(StringIO(html))
        return [clean_columns(df) for df in tables]
    except Exception:
        return []


def choose_batting_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    best = None
    best_rows = -1

    for df in tables:
        cols = [str(c).lower() for c in df.columns]
        joined = " ".join(cols)

        if "player" in joined and "runs" in joined and ("matches" in joined or "mat" in joined):
            if len(df) > best_rows:
                best = df
                best_rows = len(df)

    return best


def choose_bowling_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    best = None
    best_rows = -1

    for df in tables:
        cols = [str(c).lower() for c in df.columns]
        joined = " ".join(cols)

        bowling_signals = ["wkts", "wickets", "balls", "5wkts", "5 wickets", "five wickets"]
        if "player" in joined and any(sig in joined for sig in bowling_signals):
            if len(df) > best_rows:
                best = df
                best_rows = len(df)

    return best


def normalize_player_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # normalize common player column name
    for col in df.columns:
        if str(col).strip().lower() == "player":
            df = df.rename(columns={col: "Player"})
            break

    if "Player" in df.columns:
        df["Player"] = (
            df["Player"]
            .astype(str)
            .str.replace(r"\s*\([A-Z]+\)\s*$", "", regex=True)
            .str.strip()
        )

    return df


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
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

        # --- Batting (default view) ---
        batting_html = page.content()
        batting_tables = extract_tables_from_html(batting_html)
        print(f"Tables found on batting view: {len(batting_tables)}")

        orange_df = choose_batting_table(batting_tables)
        if orange_df is not None:
            orange_df = normalize_player_column(orange_df)

        # --- Bowling ---
        clicked = click_tab(page, "Bowling")
        print(f"Bowling tab clicked: {clicked}")

        page.wait_for_timeout(4000)
        bowling_html = page.content()
        bowling_tables = extract_tables_from_html(bowling_html)
        print(f"Tables found on bowling view: {len(bowling_tables)}")

        purple_df = choose_bowling_table(bowling_tables)
        if purple_df is not None:
            purple_df = normalize_player_column(purple_df)

        # retry once if needed
        if purple_df is None:
            print("Bowling table not found on first try, retrying...")
            click_tab(page, "Bowling")
            page.wait_for_timeout(4000)
            bowling_html = page.content()
            bowling_tables = extract_tables_from_html(bowling_html)
            print(f"Tables found on bowling retry: {len(bowling_tables)}")
            purple_df = choose_bowling_table(bowling_tables)
            if purple_df is not None:
                purple_df = normalize_player_column(purple_df)

        browser.close()

    if orange_df is None or orange_df.empty:
        raise ValueError("Could not parse batting stats from MyKhel page HTML.")

    if purple_df is None or purple_df.empty:
        raise ValueError("Could not parse bowling stats from MyKhel page HTML.")

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