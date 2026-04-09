import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent

def run(cmd):
    print("\nRunning:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)
    return result.returncode == 0

def has_staged_changes():
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=BASE_DIR
    )
    return result.returncode != 0

while True:
    print("\n==============================")
    print("Starting automated update cycle")
    print("==============================")

    ok_scrape = run(["python3", "ipl_stats_scraper.py"])
    ok_points = run(["python3", "fantasy_points_from_stats.py"]) if ok_scrape else False

    if ok_scrape and ok_points:
        run(["git", "add", "ipl_stats_2026.xlsx", "IPL_Fantasy_Points.xlsx"])

        if has_staged_changes():
            run(["git", "commit", "-m", "auto update fantasy data"])
            run(["git", "push"])
            print("Updated files pushed to GitHub.")
        else:
            print("No changes detected. Nothing to push.")
    else:
        print("Update failed. Skipping git push this cycle.")

    print("Sleeping for 10 minutes...")
    time.sleep(600)
