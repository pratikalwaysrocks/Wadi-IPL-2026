import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent


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


def main() -> None:
    while True:
        print("\n==============================")
        print("Starting automated update cycle")
        print("==============================")

        PYTHON = str(BASE_DIR / "venv" / "bin" / "python")

        ok_scrape = run([PYTHON, "ipl_stats_scraper.py"])
        ok_points = run([PYTHON, "fantasy_points_from_stats.py"]) if ok_scrape else False

        if ok_scrape and ok_points:
            run(["git", "add", "ipl_stats_2026.xlsx", "IPL_Fantasy_Points.xlsx"])

            if has_staged_changes():
                committed = run(["git", "commit", "-m", "auto update fantasy data"])

                if committed:
                    rebased = run(["git", "pull", "--rebase", "origin", "main"])
                    pushed = run(["git", "push"]) if rebased else False
                else:
                    pushed = False

                if pushed:
                    print("Updated files pushed to GitHub.")
                else:
                    print("Git sync/push failed.")
            else:
                print("No changes detected. Nothing to push.")
        else:
            print("Update failed. Skipping git push this cycle.")

        print("Sleeping for 10 minutes...")
        time.sleep(600)


if __name__ == "__main__":
    main()
