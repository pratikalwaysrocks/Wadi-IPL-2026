import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
PYTHON = "/home/ubuntu/Wadi-IPL-2026/venv/bin/python"

WORKBOOK = BASE_DIR / "IPL_Fantasy_Points.xlsx"
LEADERBOARD_HISTORY_FILE = BASE_DIR / "leaderboard_history.csv"
PLAYER_HISTORY_FILE = BASE_DIR / "player_points_history.csv"
STATUS_FILE = BASE_DIR / "update_status.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str]) -> bool:
    print("\nRunning:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)
    return result.returncode == 0


def has_staged_changes() -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=BASE_DIR,
    )
    return result.returncode != 0


def load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_status(update: dict) -> None:
    current = load_status()
    current.update(update)
    STATUS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")


def check_data_source_status() -> str:
    # Basic status. You can make this smarter later.
    return "healthy"


def check_server_status() -> str:
    try:
        socket.gethostname()
        return "running"
    except Exception:
        return "issue"


def append_csv_snapshot(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        return

    out = df.copy()
    out["snapshot_time"] = now_iso()

    if path.exists():
        out.to_csv(path, mode="a", header=False, index=False)
    else:
        out.to_csv(path, index=False)


def update_history_files() -> bool:
    if not WORKBOOK.exists():
        print("Workbook not found. Cannot update history.")
        return False

    try:
        leaderboard_df = pd.read_excel(WORKBOOK, sheet_name="Leaderboard")
        player_points_df = pd.read_excel(WORKBOOK, sheet_name="Player_Points")
    except Exception as exc:
        print(f"Failed to read workbook for history update: {exc}")
        return False

    append_csv_snapshot(leaderboard_df, LEADERBOARD_HISTORY_FILE)
    append_csv_snapshot(player_points_df, PLAYER_HISTORY_FILE)
    return True


def main() -> None:
    cycle_time = now_iso()
    save_status(
        {
            "last_cycle_started": cycle_time,
            "server_status": check_server_status(),
            "data_source_status": "starting",
            "last_cycle_result": "running",
        }
    )

    synced = run(["git", "pull", "--rebase", "origin", "main"])
    if not synced:
        save_status(
            {
                "last_cycle_finished": now_iso(),
                "last_cycle_result": "git_sync_failed",
                "server_status": check_server_status(),
            }
        )
        print("Git sync failed.")
        return

    ok_scrape = run([PYTHON, "ipl_stats_scraper.py"])
    if ok_scrape:
        save_status(
            {
                "last_successful_scrape_time": now_iso(),
                "data_source_status": check_data_source_status(),
            }
        )

    ok_points = run([PYTHON, "fantasy_points_from_stats.py"]) if ok_scrape else False
    ok_history = update_history_files() if ok_scrape and ok_points else False

    if ok_scrape and ok_points and ok_history:
        run(
            [
                "git",
                "add",
                "ipl_stats_2026.xlsx",
                "IPL_Fantasy_Points.xlsx",
                "leaderboard_history.csv",
                "player_points_history.csv",
                "update_status.json",
            ]
        )

        if has_staged_changes():
            committed = run(["git", "commit", "-m", "auto update fantasy data"])
            pushed = run(["git", "push"]) if committed else False

            if pushed:
                save_status(
                    {
                        "last_successful_git_push_time": now_iso(),
                        "last_cycle_finished": now_iso(),
                        "last_cycle_result": "success",
                        "server_status": check_server_status(),
                        "data_source_status": check_data_source_status(),
                    }
                )
                run(["git", "add", "update_status.json"])
                if has_staged_changes():
                    run(["git", "commit", "-m", "update automation status"])
                    run(["git", "push"])
                print("Updated files pushed to GitHub.")
            else:
                save_status(
                    {
                        "last_cycle_finished": now_iso(),
                        "last_cycle_result": "git_push_failed",
                        "server_status": check_server_status(),
                    }
                )
                print("Git push failed.")
        else:
            save_status(
                {
                    "last_cycle_finished": now_iso(),
                    "last_cycle_result": "no_changes",
                    "server_status": check_server_status(),
                    "data_source_status": check_data_source_status(),
                }
            )
            print("No changes detected. Nothing to push.")
    else:
        save_status(
            {
                "last_cycle_finished": now_iso(),
                "last_cycle_result": "update_failed",
                "server_status": check_server_status(),
                "data_source_status": "issue" if not ok_scrape else check_data_source_status(),
            }
        )
        print("Update failed. Skipping git push.")


if __name__ == "__main__":
    main()
