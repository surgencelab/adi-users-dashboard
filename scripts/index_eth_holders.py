#!/usr/bin/env python3
"""Count ADI ERC-20 holders on Ethereum mainnet.

Balances are reconstructed by summing every Transfer event, which is how an
explorer does it. Two rules matter, both learned by getting them wrong:

  * Sum raw wei as Python ints, never floats. A DOUBLE divided by 1e18 loses
    precision on 18-decimal values and silently mangles small balances.
  * A holder is anyone with a strictly positive balance. Applying a dust
    threshold dropped roughly 10,000 of ~15,000 holders in an earlier attempt
    and produced a count 3x below Etherscan's.

Incremental: balances and the last scanned block are checkpointed, so a repeat
run only scans new blocks.

Outputs data/eth_holders.json.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adi_rpc import get_logs, rpc, rpc_batch, safe_head, topic_to_address  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "eth_holders_state.json")

TOKEN = "0x8b1484d57abbe239bb280661377363b03c89caea"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEPLOY_BLOCK = 23_841_449          # first Upgraded event on the token proxy
ZERO = "0x" + "0" * 40
CHUNK = 20_000
CONFIRMATIONS = 25                 # stay off the unfinalised tip

ETH_RPCS = [u for u in [
    os.environ.get("ETH_RPC_URL", "").strip(),
    "https://gateway.tenderly.co/public/mainnet",
    "https://rpc.mevblocker.io",
] if u]


def eth_call(fn, *a, **kw):
    last = None
    for url in ETH_RPCS:
        try:
            return fn(*a, url=url, **kw)
        except Exception as e:
            last = e
    raise RuntimeError(f"all Ethereum endpoints failed: {last}")


def load_state():
    if os.path.exists(STATE):
        s = json.load(open(STATE))
        return {k: int(v) for k, v in s["balances"].items()}, int(s["scanned_through"])
    return {}, DEPLOY_BLOCK - 1


def main():
    os.makedirs(DATA, exist_ok=True)
    balances, scanned = load_state()
    head = int(eth_call(rpc, "eth_blockNumber", [])[2:] or "0", 16) - CONFIRMATIONS

    if scanned >= head:
        print(f"already scanned through {scanned:,}, head is {head:,}; nothing new")
    else:
        print(f"scanning {scanned + 1:,}..{head:,} "
              f"({head - scanned:,} blocks) for ADI Transfer events", flush=True)
        t0 = time.time()
        seen = 0
        lo = scanned + 1
        while lo <= head:
            hi = min(lo + CHUNK - 1, head)
            logs = eth_call(get_logs, TOKEN, [TRANSFER], lo, hi)
            for lg in logs:
                topics = lg.get("topics") or []
                if len(topics) < 3:
                    continue
                frm = topic_to_address(topics[1])
                to = topic_to_address(topics[2])
                # Exact integer wei. Never float.
                val = int(lg["data"], 16)
                if frm != ZERO:
                    balances[frm] = balances.get(frm, 0) - val
                if to != ZERO:
                    balances[to] = balances.get(to, 0) + val
            seen += len(logs)
            pct = 100 * (hi - scanned) / max(head - scanned, 1)
            print(f"  {lo:,}-{hi:,}  {len(logs):5,} events  "
                  f"(total {seen:,})  {pct:5.1f}%  {(time.time() - t0) / 60:.1f}m",
                  flush=True)
            lo = hi + 1
        json.dump({"scanned_through": head,
                   "balances": {k: str(v) for k, v in balances.items()}},
                  open(STATE, "w"))

    positive = {a: b for a, b in balances.items() if b > 0}

    # Cross-chain overlap. Token amounts must never be added across the two
    # chains, since ADI Chain runs on these same tokens bridged across. Address
    # counts are a different matter: a holding on Ethereum and one on ADI Chain
    # are separate ledger entries even for the same key, so they do combine once
    # the addresses present on both are counted once. Checking the Ethereum
    # holders against ADI Chain gives that intersection directly, and is far
    # cheaper than persisting the whole ADI Chain holder set.
    overlap = 0
    try:
        l2_head = safe_head(verbose=False)
        l2_blk = hex(l2_head)
        addrs = sorted(positive)
        print(f"\nchecking {len(addrs):,} Ethereum holders against ADI Chain", flush=True)
        for i in range(0, len(addrs), 300):
            chunk = addrs[i:i + 300]
            for r in rpc_batch([("eth_getBalance", [a, l2_blk]) for a in chunk]):
                if r and int(r, 16) > 0:
                    overlap += 1
        print(f"  {overlap:,} hold ADI on both chains", flush=True)
    except Exception as e:
        print(f"  overlap check failed ({e}); cross-chain total will be omitted",
              flush=True)
        overlap = None

    total_wei = sum(positive.values())
    vals = sorted(positive.values(), reverse=True)
    n = len(vals)
    one = 10 ** 18

    out = {
        "block": head,
        "holders": n,
        "holders_over_1_adi": sum(1 for v in vals if v >= one),
        "holders_dust": sum(1 for v in vals if v < one),
        "addresses_ever_touched": len(balances),
        "zero_balance_addresses": sum(1 for b in balances.values() if b == 0),
        "total_adi": round(total_wei / 1e18, 4),
        "top10_adi": round(sum(vals[:10]) / 1e18, 4),
        "top10_pct": round(100 * sum(vals[:10]) / total_wei, 3) if total_wei else 0,
        "holders_on_both_chains": overlap,
        "top_holders": [{"address": a, "adi": round(b / 1e18, 4),
                         "pct": round(100 * b / total_wei, 4)}
                        for a, b in sorted(positive.items(), key=lambda kv: -kv[1])[:15]],
    }
    with open(os.path.join(DATA, "eth_holders.json"), "w") as f:
        json.dump(out, f)

    print(f"\nholders {n:,}   total {out['total_adi']:,.0f} ADI")
    print(f"  hold 1 ADI or more : {out['holders_over_1_adi']:,}")
    print(f"  hold dust          : {out['holders_dust']:,}")
    print(f"  once held, now zero: {out['zero_balance_addresses']:,}")
    print(f"  top 10 hold        : {out['top10_pct']:.1f}%")
    print(f"wrote {DATA}/eth_holders.json")


if __name__ == "__main__":
    main()
