#!/usr/bin/env python3
"""Load the ADI users dataset into Postgres (Neon).

Reads the local raw index, rolls it up to the daily grain, and upserts. Every
statement is idempotent on a natural key, so running this twice changes
nothing and a partial run can simply be repeated.

Runs after validate.py has published, so only data that passed the gate is
ever loaded. Skipped silently when DATABASE_URL is unset, which keeps the
pipeline working for anyone without database access.

Usage:
  python3 load_db.py            # load everything
  python3 load_db.py --since 2026-07-01   # only reload days from this date
"""
import argparse
import collections
import datetime as dt
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connect, ensure_schema, load_dotenv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BATCH = 5000


def read_jsonl_gz(path):
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, EOFError, OSError):
        return


def day_of(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).date()


def upsert(cur, sql, rows, label):
    """Batched executemany with progress. `sql` must carry its own ON CONFLICT."""
    if not rows:
        print(f"  {label:24s} nothing to load")
        return
    t0 = time.time()
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, rows[i:i + BATCH])
    print(f"  {label:24s} {len(rows):>10,} rows  {time.time() - t0:5.1f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None,
                    help="only load days on or after this ISO date")
    args = ap.parse_args()
    since = dt.date.fromisoformat(args.since) if args.since else None

    load_dotenv()
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL not set, skipping database load "
              "(the dashboard does not need it)")
        return

    conn = connect()
    ensure_schema(conn)
    print("schema ready\n")

    # ---- blocks -----------------------------------------------------------
    block_ts = {}
    blocks = []
    for r in read_jsonl_gz(os.path.join(DATA, "blocks.jsonl.gz")):
        block_ts[r["n"]] = r["t"]
        d = day_of(r["t"])
        if since and d < since:
            continue
        blocks.append((r["n"], dt.datetime.fromtimestamp(r["t"], dt.UTC), r["c"]))

    with conn.cursor() as cur:
        upsert(cur, """
            INSERT INTO blocks (number, ts, tx_count) VALUES (%s, %s, %s)
            ON CONFLICT (number) DO UPDATE
              SET ts = EXCLUDED.ts, tx_count = EXCLUDED.tx_count
        """, blocks, "blocks")
        conn.commit()

        # ---- chain aggregates --------------------------------------------
        sender_daily = collections.Counter()
        sender_total = collections.Counter()
        daily_tx = collections.Counter()
        daily_recip = collections.defaultdict(set)
        daily_send = collections.defaultdict(set)
        for r in read_jsonl_gz(os.path.join(DATA, "txs.jsonl.gz")):
            d = day_of(r["t"])
            sender_total[r["f"]] += 1
            if since and d < since:
                continue
            sender_daily[(d, r["f"])] += 1
            daily_tx[d] += 1
            daily_send[d].add(r["f"])
            if r["o"]:
                daily_recip[d].add(r["o"])

        daily_blocks = collections.Counter()
        for n, t in block_ts.items():
            daily_blocks[day_of(t)] += 1

        ds = json.load(open(os.path.join(ROOT, "data.json")))
        partial = ds.get("partial_day")

        upsert(cur, """
            INSERT INTO chain_daily
              (day, txs, blocks, distinct_senders, distinct_recipients, partial)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (day) DO UPDATE SET
              txs = EXCLUDED.txs, blocks = EXCLUDED.blocks,
              distinct_senders = EXCLUDED.distinct_senders,
              distinct_recipients = EXCLUDED.distinct_recipients,
              partial = EXCLUDED.partial
        """, [(d, daily_tx[d], daily_blocks.get(d, 0), len(daily_send[d]),
               len(daily_recip[d]), partial == d.isoformat())
              for d in sorted(daily_tx)], "chain_daily")

        upsert(cur, """
            INSERT INTO chain_sender_daily (day, sender, txs) VALUES (%s, %s, %s)
            ON CONFLICT (day, sender) DO UPDATE SET txs = EXCLUDED.txs
        """, [(d, s, n) for (d, s), n in sender_daily.items()], "chain_sender_daily")

        upsert(cur, """
            INSERT INTO chain_sender_totals (sender, txs) VALUES (%s, %s)
            ON CONFLICT (sender) DO UPDATE SET txs = EXCLUDED.txs
        """, list(sender_total.items()), "chain_sender_totals")
        conn.commit()

        # ---- PredictStreet -----------------------------------------------
        vaults = json.load(open(os.path.join(DATA, "ps_vaults.json")))
        upsert(cur, """
            INSERT INTO ps_vaults (vault, owner, created_block, created_day)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (vault) DO UPDATE SET
              owner = EXCLUDED.owner,
              created_block = EXCLUDED.created_block,
              created_day = EXCLUDED.created_day
        """, [(v["vault"], v["owner"], v["block"],
               day_of(block_ts[v["block"]]) if v["block"] in block_ts else None)
              for v in vaults], "ps_vaults")

        act = collections.Counter()
        for r in read_jsonl_gz(os.path.join(DATA, "ps_activity.jsonl.gz")):
            t = block_ts.get(r["n"])
            if t is None:
                continue
            d = day_of(t)
            if since and d < since:
                continue
            act[(d, r["v"])] += 1
        upsert(cur, """
            INSERT INTO ps_activity_daily (day, vault, actions) VALUES (%s, %s, %s)
            ON CONFLICT (day, vault) DO UPDATE SET actions = EXCLUDED.actions
        """, [(d, v, n) for (d, v), n in act.items()], "ps_activity_daily")
        conn.commit()

        # ---- staking ------------------------------------------------------
        sp = os.path.join(DATA, "staking_events.json")
        if os.path.exists(sp):
            payload = json.load(open(sp))
            events = payload["events"] if isinstance(payload, dict) else payload
            upsert(cur, """
                INSERT INTO staking_events
                  (tx, block, action, staker, amount, weighted, ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tx, action, block, staker) DO UPDATE SET
                  amount = EXCLUDED.amount, weighted = EXCLUDED.weighted,
                  ts = EXCLUDED.ts
            """, [(e["tx"], e["block"], e["action"], e.get("staker") or "",
                   e.get("amount"), e.get("weighted"),
                   dt.datetime.fromtimestamp(e["ts"], dt.UTC) if e.get("ts") else None)
                  for e in events], "staking_events")

        # ---- snapshot -----------------------------------------------------
        ps, st, ch = (ds.get("predictstreet") or {}, ds.get("staking") or {},
                      ds.get("chain") or {})
        series = ps.get("series") or [{}]
        last = next((r for r in reversed(series) if not r.get("partial")), series[-1])
        cur.execute("""
            INSERT INTO metric_snapshots
              (generated_at, schema_version, ps_registered, ps_dau, ps_mau,
               ps_signer_visible_pct, chain_txs, chain_distinct_senders,
               staking_participants, staking_adi, staking_usd, adi_price_usd)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (generated_at) DO NOTHING
        """, (ds.get("generated_at"), ds.get("schema_version"),
              ps.get("registered_total"), last.get("dau"), last.get("mau"),
              ps.get("signer_visible_pct"), ch.get("total_txs"),
              ch.get("total_distinct_senders"), st.get("unique_stakers"),
              st.get("total_staked_adi"), st.get("total_staked_usd"),
              (st.get("price") or {}).get("usd")))
        print(f"  {'metric_snapshots':24s} {'1':>10} row")
        conn.commit()

    print("\nload complete")
    conn.close()


if __name__ == "__main__":
    main()
