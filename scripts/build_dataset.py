#!/usr/bin/env python3
"""Join the raw indexes into public/data.json for the dashboard.

Reads from data/:
  blocks.jsonl.gz        chain blocks + tx counts
  txs.jsonl.gz           every transaction's (from, to)
  ps_vaults.json         PredictStreet vault registry (owner <-> vault)
  ps_activity.jsonl.gz   per-vault activity, keyed by block
  staking_events.json    ADI HODLER staking events on Ethereum

Metric definitions, applied consistently across all three surfaces:

  DAU  distinct actors in a UTC calendar day
  MAU  distinct actors over the trailing 30 days ending that day (rolling).
       Calendar-month figures are emitted separately as `monthly`.

"Actor" differs by surface, and that difference is the whole point of this
dashboard:

  chain (signer)  distinct transaction senders. On ADI Chain this is a
                  misleading number: PredictStreet relays every user action
                  through a small rotating pool of operator wallets, so the
                  signer count measures infrastructure, not people.
  predictstreet   distinct user vaults. Every account gets its own vault
                  contract, so this is the true user-level count.
  staking         distinct staker addresses on Ethereum mainnet.
"""
import argparse
import collections
import datetime as dt
import gzip
import json
import os

SCHEMA_VERSION = 1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
# The dashboard is a set of static pages served from the project root, so the
# dataset sits beside them rather than under a build directory.
PUBLIC = ROOT

ROLLING_WINDOW = 30


def read_jsonl_gz(path):
    """Yield rows from a gzipped JSONL file, tolerating a truncated tail.

    The block indexer appends as it runs, so a build launched mid-scan sees an
    unfinished gzip member. Rather than fail, stop cleanly at the last complete
    record — a partial build is still useful for smoke-testing the UI.
    """
    try:
        with gzip.open(path, "rt") as f:
            while True:
                try:
                    line = f.readline()
                except (EOFError, OSError, gzip.BadGzipFile):
                    return
                if not line:
                    return
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return


def day_of(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).date().isoformat()


def month_of(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m")


def date_range(first, last):
    d0 = dt.date.fromisoformat(first)
    d1 = dt.date.fromisoformat(last)
    out = []
    while d0 <= d1:
        out.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    return out


def rolling_unique(daily_sets, days, window=ROLLING_WINDOW):
    """Trailing-window distinct count for each day in `days`."""
    out = {}
    for i, d in enumerate(days):
        lo = max(0, i - window + 1)
        acc = set()
        for j in range(lo, i + 1):
            acc |= daily_sets.get(days[j], set())
        out[d] = len(acc)
    return out


def load_block_times():
    """block number -> unix timestamp."""
    ts = {}
    for r in read_jsonl_gz(os.path.join(DATA, "blocks.jsonl.gz")):
        ts[r["n"]] = r["t"]
    return ts


def partial_day(block_ts):
    """The UTC day the index stops inside, if it stops mid-day.

    The last day of any refresh is almost always incomplete, and an incomplete
    day looks exactly like a collapse in DAU. Flag it so the UI can label it
    and headline figures can fall back to the last complete day.
    """
    if not block_ts:
        return None
    last = max(block_ts.values())
    end_of_day = dt.datetime.fromtimestamp(last, dt.UTC).replace(
        hour=23, minute=59, second=59).timestamp()
    return day_of(last) if last < end_of_day else None


def build_chain(block_ts):
    """Chain-wide activity: tx counts, blocks, and distinct signers per day."""
    daily_senders = collections.defaultdict(set)
    daily_tx = collections.Counter()
    daily_recipients = collections.defaultdict(set)
    sender_total = collections.Counter()

    for r in read_jsonl_gz(os.path.join(DATA, "txs.jsonl.gz")):
        d = day_of(r["t"])
        daily_senders[d].add(r["f"])
        daily_tx[d] += 1
        if r["o"]:
            daily_recipients[d].add(r["o"])
        sender_total[r["f"]] += 1

    daily_blocks = collections.Counter()
    for n, t in block_ts.items():
        daily_blocks[day_of(t)] += 1

    days = date_range(min(daily_tx), max(daily_tx))
    mau = rolling_unique(daily_senders, days)

    series = [{
        "date": d,
        "txs": daily_tx.get(d, 0),
        "blocks": daily_blocks.get(d, 0),
        "dau_signers": len(daily_senders.get(d, set())),
        "mau_signers": mau.get(d, 0),
        "distinct_recipients": len(daily_recipients.get(d, set())),
    } for d in days]

    monthly = collections.defaultdict(set)
    monthly_tx = collections.Counter()
    for d, s in daily_senders.items():
        monthly[d[:7]] |= s
    for d, c in daily_tx.items():
        monthly_tx[d[:7]] += c

    return {
        "series": series,
        "monthly": [{"month": m, "mau_signers": len(s), "txs": monthly_tx[m]}
                    for m, s in sorted(monthly.items())],
        "top_senders": [{"address": a, "txs": c}
                        for a, c in sender_total.most_common(25)],
        "total_txs": sum(daily_tx.values()),
        "total_distinct_senders": len(sender_total),
    }, set(sender_total)


def build_predictstreet(block_ts, chain_senders):
    vault_path = os.path.join(DATA, "ps_vaults.json")
    act_path = os.path.join(DATA, "ps_activity.jsonl.gz")
    if not (os.path.exists(vault_path) and os.path.exists(act_path)):
        print("  (predictstreet index not present, skipping)", flush=True)
        return None
    vaults = json.load(open(vault_path))
    vault_owner = {v["vault"]: v["owner"] for v in vaults}

    # registrations per day
    reg_daily = collections.Counter()
    vault_created_day = {}
    undated = 0
    for v in vaults:
        t = block_ts.get(v["block"])
        if t:
            d = dt.datetime.fromtimestamp(t, dt.UTC).date()
            reg_daily[d.isoformat()] += 1
            vault_created_day[v["vault"]] = d
        else:
            undated += 1
    if undated:
        # Means the PredictStreet scan reached blocks the block scan did not,
        # so these registrations would vanish from the daily series while still
        # counting in the registry. refresh_all.py pins both indexers to one
        # head to prevent it; say so loudly if it happens anyway.
        print(f"  WARNING: {undated} vault(s) have no block timestamp and are "
              f"missing from the daily series. The indexers covered different "
              f"block ranges; re-run via refresh_all.py.", flush=True)

    # activity per day, deduped to the vault (one row per user per day)
    act_daily = collections.defaultdict(set)
    act_events = collections.Counter()
    event_mix = collections.Counter()
    vault_active_days = collections.defaultdict(set)
    for r in read_jsonl_gz(act_path):
        t = block_ts.get(r["n"])
        if not t:
            continue
        d = dt.datetime.fromtimestamp(t, dt.UTC).date()
        act_daily[d.isoformat()].add(r["v"])
        act_events[d.isoformat()] += 1
        event_mix[r["s"]] += 1
        vault_active_days[r["v"]].add(d)

    if not reg_daily and not act_daily:
        return None

    first = min(list(reg_daily) + list(act_daily))
    last = max(list(reg_daily) + list(act_daily))
    days = date_range(first, last)
    mau = rolling_unique(act_daily, days)

    cum = 0
    series = []
    for d in days:
        cum += reg_daily.get(d, 0)
        series.append({
            "date": d,
            "new_users": reg_daily.get(d, 0),
            "registered_cumulative": cum,
            "dau": len(act_daily.get(d, set())),
            "mau": mau.get(d, 0),
            "actions": act_events.get(d, 0),
        })

    monthly_act = collections.defaultdict(set)
    monthly_reg = collections.Counter()
    for d, s in act_daily.items():
        monthly_act[d[:7]] |= s
    for d, c in reg_daily.items():
        monthly_reg[d[:7]] += c
    months = sorted(set(monthly_act) | set(monthly_reg))

    # How much of the user base would a naive signer count actually see?
    # Vaults are plain contracts, not smart accounts, so they never send
    # transactions; only an owner who signs directly ever shows up as a sender.
    owners = set(vault_owner.values())
    self_signed = owners & chain_senders
    vaults_as_senders = set(vault_owner) & chain_senders

    return {
        "series": series,
        "monthly": [{"month": m,
                     "mau": len(monthly_act.get(m, set())),
                     "new_users": monthly_reg.get(m, 0)} for m in months],
        "registered_total": len(vaults),
        "distinct_owners": len(owners),
        "owners_that_self_signed": len(self_signed),
        "vaults_that_sent_txs": len(vaults_as_senders),
        "signer_visible_pct": round(100 * len(self_signed) / max(len(owners), 1), 2),
        "event_mix": [{"sig": s, "count": c} for s, c in event_mix.most_common()],
        "retention": build_retention(
            vault_created_day, vault_active_days,
            max(vault_created_day.values()) if vault_created_day else dt.date.today()),
    }


def build_retention(vault_created_day, vault_active_days, today):
    """Cohort retention by sign-up week.

    Answers the question the headline numbers provoke: of the people who signed
    up, how many came back? Cohorts are ISO weeks of the sign-up day, and every
    window is measured from each user's own sign-up day, not from the week.

    Windows a cohort has not lived through yet are reported as null rather than
    zero. A cohort that signed up three days ago has not failed its 8-to-30 day
    window, it simply has not reached it, and showing 0% there would read as
    catastrophic churn when it is an artefact of the calendar.
    """
    cohorts = collections.defaultdict(lambda: {
        "signed_up": 0, "ever": 0, "returned": 0, "d1_7": 0, "d8_30": 0, "d31_plus": 0})

    for vault, created in vault_created_day.items():
        wk = (created - dt.timedelta(days=created.weekday())).isoformat()
        c = cohorts[wk]
        c["signed_up"] += 1
        days = vault_active_days.get(vault)
        if not days:
            continue
        c["ever"] += 1
        later = [d for d in days if d > created]
        if later:
            c["returned"] += 1
        if any(1 <= (d - created).days <= 7 for d in later):
            c["d1_7"] += 1
        if any(8 <= (d - created).days <= 30 for d in later):
            c["d8_30"] += 1
        if any((d - created).days > 30 for d in later):
            c["d31_plus"] += 1

    def pct(n, d):
        return round(100 * n / d, 2) if d else None

    out = []
    for wk in sorted(cohorts):
        c = cohorts[wk]
        wk_date = dt.date.fromisoformat(wk)
        # A cohort's youngest member signed up on the last day of that week.
        age = (today - min(wk_date + dt.timedelta(days=6), today)).days
        n = c["signed_up"]
        out.append({
            "week": wk,
            "signed_up": n,
            "ever_active": c["ever"],
            "ever_active_pct": pct(c["ever"], n),
            "returned": c["returned"],
            "returned_pct": pct(c["returned"], n),
            "d1_7_pct": pct(c["d1_7"], n),
            "d8_30_pct": pct(c["d8_30"], n) if age >= 30 else None,
            "d31_plus_pct": pct(c["d31_plus"], n) if age >= 31 else None,
            "days_elapsed": age,
        })

    total = sum(c["signed_up"] for c in cohorts.values())
    return {
        "cohorts": out,
        "total_signed_up": total,
        "ever_active": sum(c["ever"] for c in cohorts.values()),
        "ever_active_pct": pct(sum(c["ever"] for c in cohorts.values()), total),
        "returned": sum(c["returned"] for c in cohorts.values()),
        "returned_pct": pct(sum(c["returned"] for c in cohorts.values()), total),
        "still_active_30d": sum(c["d31_plus"] for c in cohorts.values()),
        "still_active_30d_pct": pct(sum(c["d31_plus"] for c in cohorts.values()), total),
    }


def build_staking():
    path = os.path.join(DATA, "staking_events.json")
    if not os.path.exists(path):
        return None
    payload = json.load(open(path))
    rows = payload["events"] if isinstance(payload, dict) else payload
    price = (payload.get("price") or {}) if isinstance(payload, dict) else {}
    pool = (payload.get("pool") or {}) if isinstance(payload, dict) else {}
    cap = payload.get("pool_cap_adi") if isinstance(payload, dict) else None
    reward_pool = payload.get("reward_pool_adi") if isinstance(payload, dict) else None
    usd = price.get("usd")

    first_stake = {}
    daily_active = collections.defaultdict(set)
    daily_staked = collections.Counter()
    by_staker = collections.defaultdict(
        lambda: {"staked": 0.0, "weighted": 0.0, "harvested": 0.0,
                 "claimed": 0.0, "stake_events": 0})
    counts = collections.Counter()
    for r in rows:
        counts[r["action"]] += 1
        staker = r.get("staker")
        if not staker or not r.get("ts"):
            continue
        d = day_of(r["ts"])
        daily_active[d].add(staker)
        amt = r.get("amount") or 0.0
        if r["action"] == "Staked":
            first_stake.setdefault(staker, d)
            if d < first_stake[staker]:
                first_stake[staker] = d
            daily_staked[d] += amt
            by_staker[staker]["staked"] += amt
            by_staker[staker]["weighted"] += r.get("weighted") or 0.0
            by_staker[staker]["stake_events"] += 1
        elif r["action"] == "Harvested":
            by_staker[staker]["harvested"] += amt
        elif r["action"] == "Claimed":
            by_staker[staker]["claimed"] += amt

    if not daily_active:
        return None
    days = date_range(min(daily_active), max(daily_active))
    mau = rolling_unique(daily_active, days)

    new_by_day = collections.Counter(first_stake.values())
    cum = 0
    cum_adi = 0.0
    series = []
    for d in days:
        cum += new_by_day.get(d, 0)
        cum_adi += daily_staked.get(d, 0.0)
        series.append({
            "date": d,
            "new_stakers": new_by_day.get(d, 0),
            "cumulative_stakers": cum,
            "dau": len(daily_active.get(d, set())),
            "mau": mau.get(d, 0),
            "staked_adi": round(daily_staked.get(d, 0.0), 4),
            "cumulative_staked_adi": round(cum_adi, 4),
            "cumulative_staked_usd": round(cum_adi * usd, 2) if usd else None,
        })

    total_staked = sum(v["staked"] for v in by_staker.values())
    leaderboard = sorted(
        ({"address": a,
          "staked_adi": round(v["staked"], 4),
          "staked_usd": round(v["staked"] * usd, 2) if usd else None,
          "weighted_adi": round(v["weighted"], 4),
          "boost": round(v["weighted"] / v["staked"], 3) if v["staked"] else None,
          "share_pct": round(100 * v["staked"] / total_staked, 2) if total_staked else 0,
          "rewards_claimed_adi": round(v["claimed"], 6),
          "stake_events": v["stake_events"],
          "first_stake": first_stake.get(a)}
         for a, v in by_staker.items() if v["staked"] > 0),
        key=lambda r: -r["staked_adi"])

    claimed_total = sum(v["claimed"] for v in by_staker.values())

    return {
        "series": series,
        "unique_stakers": len(first_stake),
        "event_counts": dict(counts),
        "price": price or None,
        "total_staked_adi": round(total_staked, 4),
        "total_staked_usd": round(total_staked * usd, 2) if usd else None,
        "pool_cap_adi": cap,
        "pool_cap_usd": round(cap * usd, 2) if (usd and cap) else None,
        "pool_fill_pct": round(100 * total_staked / cap, 2) if cap else None,
        "reward_pool_adi": reward_pool,
        "reward_pool_usd": round(reward_pool * usd, 2) if (usd and reward_pool) else None,
        "rewards_claimed_adi": round(claimed_total, 6),
        "rewards_claimed_usd": round(claimed_total * usd, 2) if usd else None,
        "avg_stake_adi": round(total_staked / max(len(first_stake), 1), 4),
        "median_stake_adi": round(
            sorted(r["staked_adi"] for r in leaderboard)[len(leaderboard) // 2], 4)
            if leaderboard else None,
        "top_staker_share_pct": leaderboard[0]["share_pct"] if leaderboard else None,
        "contract_balance_adi": round(pool.get("staking_contract_adi_balance"), 4)
            if pool.get("staking_contract_adi_balance") is not None else None,
        "leaderboard": leaderboard,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PUBLIC, "data.json.candidate"),
                    help="where to write the dataset (default: a candidate file "
                         "that validate.py promotes)")
    args = ap.parse_args()

    os.makedirs(PUBLIC, exist_ok=True)
    print("loading block timestamps...", flush=True)
    block_ts = load_block_times()
    print(f"  {len(block_ts):,} blocks", flush=True)

    print("building chain series...", flush=True)
    chain, chain_senders = build_chain(block_ts)
    print("building predictstreet series...", flush=True)
    ps = build_predictstreet(block_ts, chain_senders)
    print("building staking series...", flush=True)
    staking = build_staking()

    # ADI Chain holders, from the balance sweep. Optional: absent until
    # index_holders.py has run, and the dashboard degrades to n/a without it.
    holders = None
    hp = os.path.join(DATA, "holders.json")
    if os.path.exists(hp):
        holders = json.load(open(hp))
        chain["holders"] = holders

    # Ethereum ERC-20 holders. Deliberately kept beside the ADI Chain figure
    # rather than added to it: ADI Chain's native token is this same token
    # bridged, so the L2 balance is a subset of the L1 supply, not extra supply.
    ehp = os.path.join(DATA, "eth_holders.json")
    if os.path.exists(ehp):
        eth = json.load(open(ehp))
        if holders:
            eth["bridged_to_adi_chain"] = holders.get("adi_held")
            eth["bridged_pct"] = round(
                100 * (holders.get("adi_held") or 0) / eth["total_adi"], 5) \
                if eth.get("total_adi") else None
        # Distinct addresses holding ADI anywhere. Addresses combine, tokens
        # do not: the same key on two chains is two ledger entries, but the
        # tokens behind them are one bridged supply.
        ov = eth.get("holders_on_both_chains")
        if holders and ov is not None:
            eth["cross_chain"] = {
                "ethereum_only": eth["holders"] - ov,
                "both_chains": ov,
                "adi_chain_only": holders["holders"] - ov,
                "distinct_addresses": eth["holders"] + holders["holders"] - ov,
            }
        chain["ethereum_token"] = eth

    incomplete = partial_day(block_ts)
    if incomplete:
        for section in (chain, ps):
            for row in (section or {}).get("series", []):
                if row["date"] == incomplete:
                    row["partial"] = True
        print(f"  note: {incomplete} is an incomplete UTC day (flagged)")

    out = {
        # Bumped when the shape changes in a way the pages must know about, so
        # a stale page cannot silently render an incompatible dataset.
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "partial_day": incomplete,
        "chain": chain,
        "predictstreet": ps,
        "staking": staking,
        "meta": {
            "adi_chain_id": 36900,
            "adi_rpc": "https://rpc.adifoundation.ai",
            "adi_explorer": "https://explorer.adifoundation.ai",
            "rolling_window_days": ROLLING_WINDOW,
            "contracts": {
                "predictstreet_settlement":
                    "0x79ACbb874dd01044FA38a89c1478E60FaAB40D00",
                "predictstreet_vault_factory":
                    "0xc16B8b190064451c2FeEb2e77c4B2aC4c7009552",
                "staking_ethereum":
                    "0xEA6aAd1A44232B6C7f92A4103698D9Faf3aFE241",
                "adi_token_ethereum":
                    "0x8b1484d57abbe239bb280661377363b03c89caea",
            },
        },
    }
    path = args.out
    with open(path, "w") as f:
        json.dump(out, f)
    print(f"\nwrote {os.path.basename(path)} "
          f"({os.path.getsize(path) / 1024:.0f} KB)")

    if ps:
        last = ps["series"][-1]
        print(f"  predictstreet: {ps['registered_total']:,} registered, "
              f"DAU {last['dau']:,}, MAU {last['mau']:,}")
        print(f"  a signer count would see {ps['owners_that_self_signed']:,} of "
              f"{ps['distinct_owners']:,} users ({ps['signer_visible_pct']}%)")
    if staking:
        print(f"  staking: {staking['unique_stakers']} unique stakers")
    print(f"  chain: {chain['total_txs']:,} txs, "
          f"{chain['total_distinct_senders']:,} distinct signers all-time")


if __name__ == "__main__":
    main()
