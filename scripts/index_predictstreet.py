#!/usr/bin/env python3
"""Index PredictStreet user activity on ADI Chain.

PredictStreet routes every user transaction through a rotating pool of ~15
operator hot wallets, so the transaction signer is NOT the user. The user
identity lives one level down: the factory emits

    VaultCreated(uint64, address indexed owner, address indexed vault)

giving every account its own vault contract. Every other PredictStreet event
references that vault address in an indexed topic. So:

    registered users = distinct VaultCreated owners (cumulative)
    active users     = distinct vaults referenced by non-registration events

This runs in two passes so it never holds the full log set in memory (the
settlement contract alone emits millions of logs):

  pass 1  stream every log to data/ps_logs.jsonl.gz, keeping only
          {block, topic0, address-shaped topics, contract}
  pass 2  read that file back, build the vault registry from VaultCreated,
          then re-read it to emit per-vault activity

Block timestamps are NOT resolved here. They are joined later from
data/blocks.jsonl.gz (produced by index_blocks.py), which is the single source
of truth for block -> time.

Outputs under data/:
  ps_logs.jsonl.gz   {"n": block, "s": topic0, "a": [addr,...], "c": contract}
  ps_vaults.json     [{owner, vault, block}]
  ps_activity.jsonl.gz  {"v": vault, "n": block, "s": sig10, "c": contract}
"""
import argparse
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adi_rpc import (get_logs, is_address_topic, safe_head,  # noqa: E402
                     topic_to_address)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LOGS = os.path.join(DATA, "ps_logs.jsonl.gz")
CHECKPOINT = os.path.join(DATA, "ps_checkpoint.json")

# Both deployed 2026-05-30 by 0x4f3D4eAAAC0f212B8b97a040Ac19196169C20BEd.
CONTRACTS = {
    "settlement": "0x79ACbb874dd01044FA38a89c1478E60FaAB40D00",
    "vault_factory": "0xc16B8b190064451c2FeEb2e77c4B2aC4c7009552",
}
VAULT_CREATED = "0xda3c20c15cdb6a31c5f62d008719badf21aa7476b4ea2af3a36ab59dc075610b"

# Chain genesis is 2025-11-25; the PredictStreet contracts appear at ~32,194.
START_BLOCK = 32_000
CHUNK = 25_000


def read_checkpoint():
    """Highest block already scanned into ps_logs.jsonl.gz, or None."""
    try:
        with open(CHECKPOINT) as f:
            return int(json.load(f)["scanned_through"])
    except Exception:
        return None


def write_checkpoint(block):
    with open(CHECKPOINT, "w") as f:
        json.dump({"scanned_through": block}, f)


def scan(head, start=None, append=False):
    """Pass 1: stream PredictStreet logs to disk in compact form.

    Incremental by default: resumes from the checkpoint so a routine refresh
    scans minutes of new blocks rather than re-walking 6.9M logs. Both contracts
    advance together and the checkpoint is written only after both complete, so
    a crash mid-scan re-does the whole window rather than leaving a gap.
    """
    t0 = time.time()
    total = 0
    first = START_BLOCK if start is None else start
    with gzip.open(LOGS, "at" if append else "wt") as f:
        for name, addr in CONTRACTS.items():
            print(f"\n[{name}] {addr}", flush=True)
            lo = first
            got = 0
            while lo <= head:
                hi = min(lo + CHUNK - 1, head)
                logs = get_logs(addr, None, lo, hi)
                for lg in logs:
                    topics = lg.get("topics") or []
                    if not topics:
                        continue
                    # Topic order is preserved: VaultCreated encodes
                    # (owner, vault) positionally and we rely on that below.
                    addrs = []
                    for t in topics[1:]:
                        if is_address_topic(t):
                            a = topic_to_address(t)
                            if a not in addrs:
                                addrs.append(a)
                    f.write(json.dumps({
                        "n": int(lg["blockNumber"], 16),
                        "s": topics[0][:10],
                        "a": addrs,
                        "c": name,
                    }) + "\n")
                got += len(logs)
                total += len(logs)
                pct = 100 * (hi - first) / max(head - first, 1)
                print(f"  {lo:,}-{hi:,}: {len(logs):6,}  "
                      f"(contract {got:,} / all {total:,})  {pct:5.1f}%  "
                      f"{(time.time() - t0) / 60:.1f}m", flush=True)
                lo = hi + 1
    write_checkpoint(head)
    print(f"\npass 1 done: {total:,} logs in {(time.time() - t0) / 60:.1f} minutes",
          flush=True)


def build():
    """Pass 2: vault registry, then per-vault activity."""
    sig10 = VAULT_CREATED[:10]

    # VaultCreated carries two address topics in a fixed order: topic1 is the
    # owner EOA, topic2 is the freshly deployed vault contract. Pass 1 preserved
    # that order, so a[0]/a[1] map straight onto owner/vault.
    print("building vault registry...", flush=True)
    vaults, seen = [], set()
    with gzip.open(LOGS, "rt") as f:
        for line in f:
            r = json.loads(line)
            if r["s"] != sig10 or len(r["a"]) < 2:
                continue
            owner, vault = r["a"][0], r["a"][1]
            if vault in seen:
                continue
            seen.add(vault)
            vaults.append({"owner": owner, "vault": vault, "block": r["n"]})
    vaults.sort(key=lambda r: r["block"])

    with open(os.path.join(DATA, "ps_vaults.json"), "w") as f:
        json.dump(vaults, f)
    vault_set = {v["vault"] for v in vaults}
    owners = {v["owner"] for v in vaults}
    print(f"registrations: {len(vaults):,} vaults, {len(owners):,} distinct owners",
          flush=True)

    n_act = 0
    n_logs = 0
    with gzip.open(LOGS, "rt") as fin, \
         gzip.open(os.path.join(DATA, "ps_activity.jsonl.gz"), "wt") as fout:
        for line in fin:
            r = json.loads(line)
            n_logs += 1
            if r["s"] == sig10:
                continue
            for a in r["a"]:
                if a in vault_set:
                    fout.write(json.dumps({
                        "v": a, "n": r["n"], "s": r["s"], "c": r["c"]}) + "\n")
                    n_act += 1
    print(f"scanned {n_logs:,} logs -> {n_act:,} vault activity records", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scan", action="store_true",
                    help="reuse an existing ps_logs.jsonl.gz")
    ap.add_argument("--full", action="store_true",
                    help="ignore the checkpoint and re-scan from the beginning")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    head = safe_head()

    if not args.skip_scan:
        ckpt = None if args.full else read_checkpoint()
        have_logs = os.path.exists(LOGS)
        if ckpt is not None and have_logs and ckpt < head:
            print(f"incremental: scanning {ckpt + 1:,}..{head:,} "
                  f"({head - ckpt:,} blocks)", flush=True)
            scan(head, start=ckpt + 1, append=True)
        elif ckpt is not None and have_logs and ckpt >= head:
            print(f"already scanned through {ckpt:,}, verified head is {head:,}; "
                  f"nothing new", flush=True)
        else:
            print(f"full scan: {START_BLOCK:,}..{head:,}", flush=True)
            scan(head)
    build()
    print(f"\nwrote {DATA}/ps_vaults.json and {DATA}/ps_activity.jsonl.gz")


if __name__ == "__main__":
    main()
