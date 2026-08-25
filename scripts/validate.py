#!/usr/bin/env python3
"""Publish gate for the ADI users dataset.

Nothing reaches the dashboard without passing this. `build_dataset.py` writes
`data.json.candidate`; this script checks it and only then promotes it over
`data.json`. A failed run leaves the previously published dataset in place,
which is the correct failure mode: stale but true beats fresh but wrong.

Four families of check:

  registry     the vault registry is internally consistent
  topic order  VaultCreated really is (owner, vault), sampled against the chain
  monotonic    cumulative facts never go backwards versus what is published
  reconcile    totals agree with independent sources (explorer, contract balance)

The monotonic family is the one that matters most in practice. Every real
failure so far has been silent truncation: a public RPC returning 90 of 159
logs, or a scan aborting mid-range, both of which look like success and produce
a smaller, entirely plausible dataset.

Usage:
  python3 validate.py                 # check the candidate, promote if it passes
  python3 validate.py --no-promote    # check only
  python3 validate.py --dataset X     # check an arbitrary file
"""
import argparse
import json
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adi_rpc import ADI_EXPLORER_API, explorer_stats  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PUBLISHED = os.path.join(ROOT, "data.json")
CANDIDATE = os.path.join(ROOT, "data.json.candidate")
SAMPLE = 40

# Cumulative facts. None of these may ever fall between two published datasets.
MONOTONIC = [
    ("predictstreet", "registered_total", "registered users"),
    ("predictstreet", "distinct_owners", "distinct vault owners"),
    ("chain", "total_txs", "chain transactions"),
    ("chain", "total_distinct_senders", "distinct signers"),
    ("staking", "unique_stakers", "unique stakers"),
]

failures = []
warnings = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def warn(name, detail=""):
    print(f"  [WARN] {name}{'  ' + detail if detail else ''}")
    warnings.append(name)


def explorer(addr):
    out = subprocess.check_output(
        ["curl", "-sS", "--max-time", "25", f"{ADI_EXPLORER_API}/address/{addr}"])
    return json.loads(out)


def get(ds, section, key):
    return (ds.get(section) or {}).get(key)


def check_registry(vaults):
    print("\nregistry invariants")
    owners = {v["owner"] for v in vaults}
    vaddrs = {v["vault"] for v in vaults}
    check("one vault per row is unique", len(vaddrs) == len(vaults),
          f"{len(vaddrs):,} distinct vaults / {len(vaults):,} rows")
    check("owner:vault is 1:1", len(owners) == len(vaults),
          f"{len(owners):,} distinct owners")

    # A vault can itself open a vault. As of 2026-08-10 exactly one address does
    # this (0x7cc9066f…, a vault at block 34,270 that opened another at 34,668),
    # so a hard zero would fail on a known-benign case. Anything above a
    # rounding-error share means the topic order is being misread.
    overlap = owners & vaddrs
    check("owner/vault overlap is negligible",
          len(overlap) <= max(5, len(vaults) * 0.0001),
          f"{len(overlap)} of {len(vaults):,} "
          f"({100 * len(overlap) / max(len(vaults), 1):.4f}%)")
    return owners, vaddrs


def check_topic_order(vaults):
    print("\ntopic order (owner should be an EOA, vault a contract)")
    random.seed(7)
    sample = random.sample(vaults, min(SAMPLE, len(vaults)))
    owner_is_account = vault_is_contract = looked_up = 0
    for v in sample:
        try:
            o = explorer(v["owner"])
            c = explorer(v["vault"])
        except Exception as e:
            print(f"    lookup failed for {v['vault']}: {e}")
            continue
        looked_up += 1
        if o.get("type") == "account":
            owner_is_account += 1
        if c.get("type") == "contract":
            vault_is_contract += 1
    if not looked_up:
        warn("topic order unverified", "explorer unreachable, skipped")
        return
    check("sampled owners are EOAs", owner_is_account >= looked_up * 0.95,
          f"{owner_is_account}/{looked_up}")
    check("sampled vaults are contracts", vault_is_contract >= looked_up * 0.95,
          f"{vault_is_contract}/{looked_up}")


def check_internal(ds, vaults):
    print("\ninternal consistency")
    ps = ds.get("predictstreet") or {}
    check("registered_total matches the registry",
          ps.get("registered_total") == len(vaults),
          f"{ps.get('registered_total')} vs {len(vaults)}")
    series = ps.get("series") or []
    if series:
        check("cumulative registrations end at the registry total",
              series[-1]["registered_cumulative"] == len(vaults),
              f"{series[-1]['registered_cumulative']} vs {len(vaults)}")
        check("MAU is never below DAU on any day",
              all(r["mau"] >= r["dau"] for r in series))
        check("MAU never exceeds registered users",
              all(r["mau"] <= r["registered_cumulative"] for r in series))
        check("cumulative registrations never decrease within the series",
              all(series[i]["registered_cumulative"] >= series[i - 1]["registered_cumulative"]
                  for i in range(1, len(series))))
    st = ds.get("staking")
    if st:
        check("staking series is populated", bool(st.get("series")))
        check("staking cumulative matches unique stakers",
              st["series"][-1]["cumulative_stakers"] == st["unique_stakers"],
              f"{st['series'][-1]['cumulative_stakers']} vs {st['unique_stakers']}")


def check_monotonic(ds, baseline):
    print("\nmonotonic guards (versus the published dataset)")
    if not baseline:
        warn("no published dataset to compare against", "first run")
        return
    for section, key, label in MONOTONIC:
        new, old = get(ds, section, key), get(baseline, section, key)
        if new is None or old is None:
            warn(f"{label} missing on one side", f"new={new} old={old}")
            continue
        check(f"{label} did not go backwards", new >= old,
              f"{old:,} -> {new:,}")


def check_reconciliation(ds):
    print("\nreconciliation against independent sources")

    # Chain transactions against the explorer's own counter. Ours is a subset:
    # we stop at the verified head while the explorer counts to the sealed tip,
    # so ours must be no greater, and close.
    stats = explorer_stats()
    ours = get(ds, "chain", "total_txs")
    if stats and ours is not None:
        theirs = int(stats.get("totalTransactions", 0))
        check("chain tx total does not exceed the explorer's",
              ours <= theirs, f"ours {ours:,} vs explorer {theirs:,}")
        drift = (theirs - ours) / max(theirs, 1)
        check("chain tx total is within 1% of the explorer's",
              drift <= 0.01, f"{100 * drift:.3f}% behind")
    else:
        warn("explorer stats unavailable", "skipped chain reconciliation")

    # Staking: principal + funded rewards - claimed should equal the contract's
    # token balance. This is what proves the decoded event amounts are right.
    st = ds.get("staking") or {}
    bal = st.get("contract_balance_adi")
    if bal is not None:
        # total_staked_adi is already net of withdrawals, so the identity is
        # principal remaining + rewards funded - rewards claimed = balance.
        expected = ((st.get("total_staked_adi") or 0)
                    + (st.get("reward_pool_adi") or 0)
                    - (st.get("rewards_claimed_adi") or 0))
        drift = abs(expected - bal) / max(bal, 1)
        check("staking balance reconciles with decoded events",
              drift < 0.01,
              f"expected {expected:,.2f} vs on-chain {bal:,.2f} "
              f"({100 * drift:.3f}% drift)")
    else:
        warn("contract balance unavailable", "skipped staking reconciliation")

    # A stale price silently mis-states every USD figure while the on-chain
    # numbers stay fresh, so treat a missing price as a warning, not a pass.
    if st and not (st.get("price") or {}).get("usd"):
        warn("no ADI price in dataset", "USD figures will read n/a")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=None,
                    help="dataset to check (default: the candidate, else published)")
    ap.add_argument("--baseline", default=PUBLISHED,
                    help="published dataset to compare against for monotonic checks")
    ap.add_argument("--no-promote", action="store_true",
                    help="check only, do not promote the candidate")
    args = ap.parse_args()

    target = args.dataset or (CANDIDATE if os.path.exists(CANDIDATE) else PUBLISHED)
    if not os.path.exists(target):
        sys.exit(f"nothing to validate: {target} does not exist")
    ds = json.load(open(target))
    baseline = None
    if os.path.exists(args.baseline) and os.path.abspath(args.baseline) != os.path.abspath(target):
        baseline = json.load(open(args.baseline))

    print(f"validating {os.path.basename(target)}"
          + (f" against {os.path.basename(args.baseline)}" if baseline else ""))

    vault_path = os.path.join(DATA, "ps_vaults.json")
    if os.path.exists(vault_path):
        vaults = json.load(open(vault_path))
        print(f"vault registry: {len(vaults):,} rows")
        check_registry(vaults)
        check_topic_order(vaults)
        check_internal(ds, vaults)
    else:
        warn("vault registry missing", "skipped registry and topic-order checks")

    check_monotonic(ds, baseline)
    check_reconciliation(ds)

    print()
    if warnings:
        print(f"{len(warnings)} warning(s): {', '.join(warnings)}")
    if failures:
        print(f"{len(failures)} check(s) FAILED: {', '.join(failures)}")
        print("candidate NOT promoted; the published dataset is unchanged")
        sys.exit(1)

    print("all checks passed")
    if not args.no_promote and os.path.abspath(target) == os.path.abspath(CANDIDATE):
        os.replace(CANDIDATE, PUBLISHED)
        print(f"promoted candidate to {os.path.basename(PUBLISHED)}")


if __name__ == "__main__":
    main()
