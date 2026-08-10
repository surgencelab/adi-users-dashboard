#!/usr/bin/env python3
"""Resumable full-history block + transaction scan of ADI Chain.

Writes two gzipped JSONL files under data/:
  blocks.jsonl.gz  {"n": block, "t": unix_ts, "c": tx_count}
  txs.jsonl.gz     {"n": block, "t": unix_ts, "f": from, "o": to}

Resumes from whatever is already on disk, so it is safe to re-run to catch up
to the chain head. Transaction `input` data is discarded: we only need the
sender/recipient pair to derive active addresses.

Usage:
  python3 index_blocks.py            # backfill to head
  python3 index_blocks.py --from 0   # force restart
"""
import argparse
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adi_rpc import rpc_batch, safe_head  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BLOCKS = os.path.join(DATA, "blocks.jsonl.gz")
TXS = os.path.join(DATA, "txs.jsonl.gz")
BATCH = 200


def last_indexed():
    """Highest block already written, or -1."""
    if not os.path.exists(BLOCKS):
        return -1
    high = -1
    with gzip.open(BLOCKS, "rt") as f:
        for line in f:
            try:
                n = json.loads(line)["n"]
            except Exception:
                continue
            if n > high:
                high = n
    return high


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    # Index to the verified head, never the sealed tip: unproven blocks can
    # still change, and a dataset that silently rewrites history is worse than
    # one that lags by a few minutes.
    head = args.end if args.end is not None else safe_head()

    if args.start is not None:
        start = args.start
        mode = "wt" if args.start == 0 else "at"
    else:
        start = last_indexed() + 1
        mode = "at"

    if start > head:
        print(f"nothing to do: indexed through {start - 1}, head is {head}")
        return

    print(f"indexing blocks {start}..{head} ({head - start + 1:,} blocks), "
          f"batch={args.batch}", flush=True)

    t0 = time.time()
    n_tx = 0
    with gzip.open(BLOCKS, mode) as fb, gzip.open(TXS, mode) as ft:
        cur = start
        while cur <= head:
            hi = min(cur + args.batch - 1, head)
            calls = [("eth_getBlockByNumber", [hex(n), True]) for n in range(cur, hi + 1)]
            results = rpc_batch(calls)

            missing = [n for n, r in zip(range(cur, hi + 1), results) if r is None]
            if missing:
                # retry the gaps one at a time rather than losing the range
                for n in missing:
                    r = rpc_batch([("eth_getBlockByNumber", [hex(n), True])])[0]
                    results[n - cur] = r

            for blk in results:
                if blk is None:
                    continue
                n = int(blk["number"], 16)
                t = int(blk["timestamp"], 16)
                txs = blk.get("transactions") or []
                fb.write(json.dumps({"n": n, "t": t, "c": len(txs)}) + "\n")
                for tx in txs:
                    ft.write(json.dumps({
                        "n": n, "t": t,
                        "f": (tx.get("from") or "").lower(),
                        "o": (tx.get("to") or "").lower(),
                    }) + "\n")
                    n_tx += 1

            done = hi - start + 1
            total = head - start + 1
            rate = done / max(time.time() - t0, 1e-6)
            eta = (total - done) / max(rate, 1e-6)
            print(f"  {hi:,}/{head:,}  ({100 * done / total:5.1f}%)  "
                  f"{n_tx:,} txs  {rate:,.0f} blk/s  eta {eta / 60:,.1f}m",
                  flush=True)
            cur = hi + 1

    print(f"done: {n_tx:,} transactions in {(time.time() - t0) / 60:.1f} minutes")


if __name__ == "__main__":
    main()
