#!/usr/bin/env python3
"""Run the whole ADI users pipeline end to end.

  1. index_blocks.py        incremental, resumes from the highest block on disk
  2. index_predictstreet.py incremental, resumes from its own checkpoint
  3. index_staking.py       Ethereum mainnet staking events, amounts and price
  4. build_dataset.py       joins everything into data.json.candidate
  5. validate.py            gates the candidate, promotes it to data.json

Every step indexes to the chain's verified head rather than its sealed tip, so
nothing enters the dataset that could still change. Nothing is published unless
step 5 passes: a failed run leaves the previous dataset in place, because stale
but true beats fresh but wrong.

Pass --full to force a complete PredictStreet re-scan, which takes about an
hour and is only needed if the log file is damaged.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = [
    ("blocks + transactions", "index_blocks.py"),
    ("predictstreet events", "index_predictstreet.py"),
    ("staking events", "index_staking.py"),
    ("build candidate dataset", "build_dataset.py"),
    # The gate. build_dataset.py writes data.json.candidate; validate.py checks
    # it and only promotes it over data.json if every check passes. If this step
    # fails the previously published dataset stays exactly where it was.
    ("validate and publish", "validate.py"),
    # Runs after the gate, so only data that passed is ever loaded. Skips
    # itself with a note when DATABASE_URL is unset, since the dashboard reads
    # data.json and does not depend on the database.
    ("load into postgres", "load_db.py"),
]


def main():
    full = "--full" in sys.argv
    t0 = time.time()
    for label, script in STEPS:
        print(f"\n{'=' * 62}\n  {label}  ({script})\n{'=' * 62}", flush=True)
        cmd = [sys.executable, os.path.join(HERE, script)]
        if full and script == "index_predictstreet.py":
            cmd.append("--full")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"\n{script} failed with exit code {r.returncode}.", file=sys.stderr)
            if script == "validate.py":
                print("The published dataset was left unchanged.", file=sys.stderr)
            sys.exit(r.returncode)
    print(f"\nrefresh complete in {(time.time() - t0) / 60:.1f} minutes")


if __name__ == "__main__":
    main()
