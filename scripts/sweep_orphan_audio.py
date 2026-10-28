"""Deletes reading audio in R2 that no assessment references (see app/sweep.py). Dry run by default.

    python scripts/sweep_orphan_audio.py            # lists what it would delete
    python scripts/sweep_orphan_audio.py --apply    # deletes it

Suggested as a weekly scheduled task in Coolify.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import sweep  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--min-age-hours", type=float, default=24, help="no borrar objetos más nuevos que esto")
    p.add_argument("--apply", action="store_true", help="borra (sin esto, solo lista)")
    a = p.parse_args(argv)
    r = sweep.sweep(a.min_age_hours, a.apply)
    for key in r.orphans:
        print(("borrado " if a.apply else "huérfano ") + key)
    print(f"{r.scanned} objetos revisados · {len(r.orphans)} huérfanos · {r.deleted} borrados"
          + ("" if a.apply else " (simulación: use --apply para borrar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
