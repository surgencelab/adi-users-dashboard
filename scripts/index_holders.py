#!/usr/bin/env python3
"""Count ADI holders and ADI held on ADI Chain.

ADI Chain's gas token is the Ethereum ADI bridged over: the explorer reports
l1Address 0x8b1484d5...caea for the base token at 0x...800A. So ADI on this
chain is a subset of the same 1,000,000,000 supply, not a separate one.

Balances cannot be rebuilt from logs. The base token moves as transaction
`value`, and it emits almost no Transfer events (25 in the chain's history), so
there is no ERC-20-style event trail to sum. The only way to a balance is
eth_getBalance, which means we need a list of addresses to ask about.

That list is every address that has ever appeared as a transaction sender or
recipient, plus the PredictStreet vaults and their owners. An address can only
hold ADI if it received it, and receiving means being the recipient of a
transaction or a bridge deposit, both of which appear in the transaction index.
So the universe is complete up to the block the index covers.

Outputs data/holders.json.
"""
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adi_rpc import rpc_batch, safe_head  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BATCH = 300
TOP_N = 25


def build_universe():
    """Every address that could plausibly hold ADI."""
    universe = set()
    txs = os.path.join(DATA, "txs.jsonl.gz")
    if os.path.exists(txs):
        with gzip.open(txs, "rt") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("f"):
                    universe.add(r["f"])
                if r.get("o"):
                    universe.add(r["o"])
    vaults = os.path.join(DATA, "ps_vaults.json")
    if os.path.exists(vaults):
        for v in json.load(open(vaults)):
            universe.add(v["vault"])
            universe.add(v["owner"])
    return universe


def main():
    os.makedirs(DATA, exist_ok=True)
    universe = sorted(build_universe())
    if not universe:
        sys.exit("no address universe: run index_blocks.py first")

    head = safe_head()
    blk = hex(head)
    print(f"sweeping {len(universe):,} addresses at verified block {head:,}", flush=True)

    balances = {}
    t0 = time.time()
    for i in range(0, len(universe), BATCH):
        chunk = universe[i:i + BATCH]
        for addr, res in zip(chunk, rpc_batch([("eth_getBalance", [a, blk]) for a in chunk])):
            if res:
                v = int(res, 16)
                if v:
                    balances[addr] = v / 1e18
        if i and i % 30000 == 0:
            print(f"  {i:,}/{len(universe):,}  {time.time() - t0:.0f}s", flush=True)

    total = sum(balances.values())
    vals = sorted(balances.values(), reverse=True)
    n = len(vals)

    # Almost every holder carries dust: addresses funded with just enough gas to
    # transact once. Bucketing keeps that visible instead of letting a headline
    # holder count imply a large token-holding base.
    buckets = {"under_1": 0, "1_to_10": 0, "10_to_100": 0, "100_to_1k": 0, "over_1k": 0}
    for v in vals:
        k = ("under_1" if v < 1 else "1_to_10" if v < 10 else "10_to_100" if v < 100
             else "100_to_1k" if v < 1000 else "over_1k")
        buckets[k] += 1

    top = sorted(balances.items(), key=lambda kv: -kv[1])[:TOP_N]
    out = {
        "block": head,
        "addresses_checked": len(universe),
        "holders": n,
        "adi_held": round(total, 6),
        "pct_of_total_supply": round(100 * total / 1_000_000_000, 6),
        "average": round(total / n, 6) if n else 0,
        "median": round(vals[n // 2], 6) if n else 0,
        "max": round(vals[0], 6) if n else 0,
        "top10_adi": round(sum(vals[:10]), 6),
        "top10_pct": round(100 * sum(vals[:10]) / total, 3) if total else 0,
        "buckets": buckets,
        "top_holders": [{"address": a, "adi": round(b, 6),
                         "pct": round(100 * b / total, 4) if total else 0}
                        for a, b in top],
    }
    with open(os.path.join(DATA, "holders.json"), "w") as f:
        json.dump(out, f)

    print(f"\nholders {n:,}   holding {total:,.2f} ADI "
          f"({out['pct_of_total_supply']:.5f}% of the 1B supply)")
    print(f"median {out['median']:,.4f} ADI, {buckets['under_1']:,} hold under 1 ADI")
    print(f"top 10 hold {out['top10_pct']:.1f}% of the ADI on this chain")
    print(f"wrote {DATA}/holders.json in {(time.time() - t0) / 60:.1f} minutes")


if __name__ == "__main__":
    main()
