#!/usr/bin/env python3
"""Index the ADI HODLER staking program.

The staking program does NOT run on ADI Chain: it is deployed on Ethereum
mainnet, and dashboard.adi.foundation talks to it directly over a public
Ethereum RPC. Contract addresses come from that app's own runtime config.

Events on the staking contract (resolved via openchain.xyz, contract unverified):
  Staked(address,uint256,uint256,uint256,uint64)  0xe3b4924b...
  Harvested(address,uint256)                      0x121c5042...
  Claimed(address,address,uint256)                0xf7a40077...
  Accrued(uint256,uint256,uint256)                0x08a1072a...   (no user)
  Funded(uint256,uint64,uint256)                  0x753078f4...   (no user)

Outputs data/staking_events.json:
  {events: [{action, staker, amount, weighted, block, ts, tx}],
   price:  {usd, market_cap_usd, volume_24h_usd, source} | null,
   pool:   {staking_contract_adi_balance},
   pool_cap_adi, reward_pool_adi}
"""
import datetime as dt
import json
import time
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adi_rpc import get_logs, rpc, rpc_batch, topic_to_address  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Public Ethereum endpoints, tried in order. Set ETH_RPC_URL to a paid endpoint
# (Alchemy, Infura, drpc key) to skip the free-tier limits entirely.
#
# Surveyed 2026-08-10 against this contract's log range:
#   gateway.tenderly.co    10,000-block getLogs, no key            <- best
#   rpc.mevblocker.io      10,000-block getLogs, no key
#   eth.drpc.org           ~2,000-block cap, quota runs out fast
#   publicnode / ankr      need a token or API key
#   blastapi / 1rpc / pokt getLogs capped at 10-50 blocks
#   cloudflare-eth         range too large / internal error
#   eth.llamarpc.com       returns non-JSON
#   rpc.flashbots.net      answers 200 with ZERO logs - deliberately excluded,
#                          since a silent empty result is worse than an error
ETH_RPCS = [u for u in [
    os.environ.get("ETH_RPC_URL", "").strip(),
    "https://gateway.tenderly.co/public/mainnet",
    "https://rpc.mevblocker.io",
    "https://eth.drpc.org",
] if u]
ETH_RPC = ETH_RPCS[0]
STAKING = "0xEA6aAd1A44232B6C7f92A4103698D9Faf3aFE241"
ADI_TOKEN = "0x8b1484d57abbe239bb280661377363b03c89caea"

# Programme parameters, read from the staking app's own runtime config.
POOL_CAP_ADI = 3_000_000
REWARD_POOL_ADI = 250_000

# Saved Dune query returning one row per staking log, participant extracted.
# Used when DUNE_API_KEY is set. https://dune.com/queries/8279835
DUNE_QUERY_ID = 8279835

# The program opened 2026-07-20 (first Funded event, block 25,574,748).
# Start a little earlier so deployment is always inside the window.
START_BLOCK = 25_560_000
CHUNK = 10_000

ACTIONS = {
    "0xe3b4924b88bd100a6e0246a2320cfff6dbcbda23dca6170a48a21fcd0d6a1857": "Staked",
    "0x121c5042302bae5fc561fbc64368f297ca60a880878e1e3a7f7e9380377260bf": "Harvested",
    "0xf7a40077ff7a04c7e61f6f26fb13774259ddf1b6bce9ecf26a8276cdd3992683": "Claimed",
    "0x08a1072afb388d5a429e5b35717dca12bcc4c7ac42d97954f9452977280c8268": "Accrued",
    "0x753078f47727e8a400868bf52d67b99a2e42f488bf6e05524e177301d55fd826": "Funded",
}
# Events whose first parameter is the participant address.
USER_EVENTS = {"Staked", "Harvested", "Claimed"}


def staker_of(log):
    """First param of the event: indexed -> topic1, else first 32-byte data word."""
    topics = log.get("topics") or []
    if len(topics) > 1:
        return topic_to_address(topics[1])
    data = log.get("data", "0x")[2:]
    if len(data) >= 64:
        return "0x" + data[24:64].lower()
    return None


def data_words(log):
    """Non-indexed event params as integers, in order."""
    d = log.get("data", "0x")[2:]
    return [int(d[i:i + 64], 16) for i in range(0, len(d) - 63, 64)]


def amounts_of(log, action):
    """Principal and lock-boosted amounts, in whole ADI.

    Staked(address indexed user, uint256 amount, uint256 weighted, uint256, uint64):
    word 0 is the principal and word 1 the lock-boosted figure. Verified two
    ways - the principals sum to 277,301.32 ADI, which is exactly the pool total
    dashboard.adi.foundation shows, and word1/word0 lands on the 0.58x / 1.17x /
    1.75x multipliers the staking UI offers for 30 / 90 / 180 day locks.

    Harvested(address, uint256) and Claimed(address, address, uint256) carry a
    single reward amount in their last word.
    """
    w = data_words(log)
    if action == "Staked" and len(w) >= 2:
        return w[0] / 1e18, w[1] / 1e18
    if action in ("Harvested", "Claimed") and w:
        return w[-1] / 1e18, None
    return None, None


def across_endpoints(fn, what, attempts=6):
    """Run fn(url) against each endpoint in turn until one succeeds.

    Free endpoints answer with a rate-limit error long before they answer with
    bad data, so back off generously rather than giving up: an aborted run is
    recoverable, a quietly truncated one is not.
    """
    errors = []
    for attempt in range(attempts):
        for url in ETH_RPCS:
            try:
                return fn(url)
            except Exception as e:
                errors.append(f"{url}: {e}")
        wait = min(60, 3 * 2 ** attempt)
        print(f"    …{what}: all endpoints failed, retrying in {wait}s "
              f"(attempt {attempt + 1}/{attempts})", flush=True)
        time.sleep(wait)
    raise SystemExit(f"{what} failed on every endpoint:\n  " + "\n  ".join(errors[-6:]))


def from_dune():
    """Preferred path when DUNE_API_KEY is set: pull the saved Dune query.

    Ethereum mainnet is fully indexed by Dune, so this avoids free-RPC rate
    limits entirely. Query 8279835 returns one row per staking log with the
    participant already extracted. Returns None when unavailable so the caller
    falls back to the RPC scan.
    """
    key = os.environ.get("DUNE_API_KEY", "").strip()
    if not key:
        return None
    import urllib.error
    import urllib.request

    url = (f"https://api.dune.com/api/v1/query/{DUNE_QUERY_ID}/results"
           f"?limit=10000")
    req = urllib.request.Request(url, headers={"X-Dune-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"Dune fetch failed ({e}); falling back to RPC scan", flush=True)
        return None

    rows = payload.get("result", {}).get("rows")
    if not rows:
        print("Dune returned no rows; falling back to RPC scan", flush=True)
        return None
    out = []
    for r in rows:
        tx = r.get("tx") or ""
        out.append({
            "action": r["action"],
            "staker": r.get("staker"),
            "block": int(r["block"]),
            "ts": int(r["ts"]),
            "tx": tx if tx.startswith("0x") else f"0x{tx.lower()}",
        })
    print(f"loaded {len(out):,} staking events from Dune query {DUNE_QUERY_ID}",
          flush=True)
    return out


def main():
    os.makedirs(DATA, exist_ok=True)

    rows = from_dune()
    if rows is not None:
        write_rows(rows, price=fetch_price())
        return

    head = int(across_endpoints(
        lambda u: rpc("eth_blockNumber", [], url=u), "eth_blockNumber"), 16)
    print(f"ethereum head = {head:,}; scanning {START_BLOCK:,}..{head:,}", flush=True)

    logs = []
    lo = START_BLOCK
    while lo <= head:
        hi = min(lo + CHUNK - 1, head)
        got = across_endpoints(
            lambda u, a=lo, b=hi: get_logs(STAKING, None, a, b, url=u),
            f"eth_getLogs {lo}-{hi}")
        if got:
            logs.extend(got)
            print(f"  {lo:,}-{hi:,}: {len(got):4,}  (running {len(logs):,})", flush=True)
        lo = hi + 1

    print(f"\ntotal staking logs: {len(logs):,}", flush=True)

    # Public Ethereum RPCs cap batch size well below ADI's node; 100-call
    # batches come back as a list of nulls rather than an error, so keep the
    # batches small and retry anything still missing one call at a time.
    blocks = sorted({int(lg["blockNumber"], 16) for lg in logs})
    ts = {}
    B = 20
    for i in range(0, len(blocks), B):
        batch = blocks[i:i + B]
        calls = [("eth_getBlockByNumber", [hex(n), False]) for n in batch]
        try:
            results = across_endpoints(
                lambda u, c=calls: rpc_batch(c, url=u), "eth_getBlockByNumber batch")
        except SystemExit:
            results = [None] * len(batch)
        for n, blk in zip(batch, results):
            if blk:
                ts[n] = int(blk["timestamp"], 16)

    for n in [b for b in blocks if b not in ts]:
        blk = across_endpoints(
            lambda u, m=n: rpc("eth_getBlockByNumber", [hex(m), False], url=u),
            f"eth_getBlockByNumber {n}")
        if blk:
            ts[n] = int(blk["timestamp"], 16)

    still = [n for n in blocks if n not in ts]
    if still:
        raise SystemExit(
            f"could not resolve timestamps for {len(still)}/{len(blocks)} blocks; "
            f"refusing to write a dataset with unusable dates")
    print(f"resolved {len(ts):,} block timestamps", flush=True)

    rows = []
    for lg in logs:
        sig = (lg.get("topics") or [None])[0]
        action = ACTIONS.get(sig, sig)
        bn = int(lg["blockNumber"], 16)
        amount, weighted = amounts_of(lg, action)
        rows.append({
            "action": action,
            "staker": staker_of(lg) if action in USER_EVENTS else None,
            "amount": amount,
            "weighted": weighted,
            "block": bn,
            "ts": ts.get(bn),
            "tx": lg["transactionHash"],
        })
    write_rows(rows, price=fetch_price())


def fetch_price():
    """Spot ADI price in USD, keyed off the ERC-20 contract so we cannot pick up
    a same-ticker impostor. Returns None if unavailable; USD figures are then
    simply omitted rather than guessed."""
    url = ("https://api.coingecko.com/api/v3/simple/token_price/ethereum"
           f"?contract_addresses={ADI_TOKEN}"
           "&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true")
    try:
        out = subprocess.check_output(["curl", "-sS", "--max-time", "25", url])
        d = json.loads(out).get(ADI_TOKEN.lower(), {})
        if not d.get("usd"):
            return None
        print(f"ADI price ${d['usd']} (CoinGecko, by contract)", flush=True)
        return {
            "usd": d["usd"],
            "market_cap_usd": d.get("usd_market_cap"),
            "volume_24h_usd": d.get("usd_24h_vol"),
            "source": "CoinGecko simple/token_price by contract",
            # Stamped separately from the dataset: the price can go stale while
            # every on-chain figure stays fresh, and that would quietly mis-state
            # every USD number on the page.
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
        }
    except Exception as e:
        print(f"price lookup failed ({e}); USD figures will be omitted", flush=True)
        return None


def read_pool_state():
    """Live pool figures straight from chain, as an independent cross-check on
    the amounts decoded from events."""
    try:
        bal = rpc("eth_call", [{
            "to": ADI_TOKEN,
            "data": "0x70a08231" + "0" * 24 + STAKING[2:].lower(),
        }, "latest"], url=ETH_RPC)
        return {"staking_contract_adi_balance": int(bal, 16) / 1e18}
    except Exception as e:
        print(f"pool state read failed ({e})", flush=True)
        return {}


def write_rows(rows, price=None):
    rows.sort(key=lambda r: (r["block"], r["tx"]))
    payload = {
        "events": rows,
        "price": price,
        "pool": read_pool_state(),
        "pool_cap_adi": POOL_CAP_ADI,
        "reward_pool_adi": REWARD_POOL_ADI,
    }
    with open(os.path.join(DATA, "staking_events.json"), "w") as f:
        json.dump(payload, f)

    stakers = {r["staker"] for r in rows if r["action"] == "Staked" and r["staker"]}
    participants = {r["staker"] for r in rows if r["staker"]}
    staked = sum(r["amount"] or 0 for r in rows if r["action"] == "Staked")
    print(f"unique stakers: {len(stakers)}   "
          f"unique participants (any action): {len(participants)}")
    print(f"total staked: {staked:,.2f} ADI"
          + (f"  =  ${staked * price['usd']:,.0f}" if price else ""))
    by_action = {}
    for r in rows:
        by_action[r["action"]] = by_action.get(r["action"], 0) + 1
    print("events:", by_action)
    print(f"wrote {DATA}/staking_events.json")


if __name__ == "__main__":
    main()
