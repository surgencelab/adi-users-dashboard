#!/usr/bin/env python3
"""Shared JSON-RPC helpers for ADI Chain (chainId 36900) and Ethereum mainnet.

Uses curl via subprocess rather than urllib: the macOS system Python has no
usable CA bundle for these hosts, and curl already has one.
"""
import json
import os
import subprocess
import time

ADI_RPC = os.environ.get("ADI_RPC_URL", "https://rpc.adifoundation.ai")
ADI_EXPLORER_API = "https://explorer-api.adifoundation.ai"
ADI_CHAIN_ID = 36900

# Node-enforced limits, discovered empirically:
#   eth_getLogs -> "query exceeds max block range 100000"
#   eth_getLogs -> "query exceeds max results 20000, retry with the range A-B"
MAX_LOG_RANGE = 100_000
MAX_LOG_RESULTS = 20_000


class RpcError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def _post(url, payload, timeout, retries=4):
    body = json.dumps(payload)
    last = None
    for attempt in range(retries):
        try:
            out = subprocess.check_output(
                ["curl", "-sS", "--max-time", str(timeout), "-X", "POST", url,
                 "-H", "content-type: application/json",
                 "--data-binary", "@-"],
                input=body.encode(), stderr=subprocess.PIPE)
            return json.loads(out)
        except Exception as e:  # network blip, timeout, truncated body
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"POST {url} failed after {retries} attempts: {last}")


def rpc(method, params, url=ADI_RPC, timeout=120):
    """Single JSON-RPC call. Raises RpcError on a node-level error."""
    r = _post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout)
    if isinstance(r, dict) and "error" in r:
        err = r["error"]
        raise RpcError(err.get("code"), err.get("message", str(err)))
    return r["result"]


def rpc_batch(calls, url=ADI_RPC, timeout=180):
    """calls = [(method, params), ...] -> results in the same order.

    A per-call error yields None in that slot rather than failing the batch.
    """
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
               for i, (m, p) in enumerate(calls)]
    r = _post(url, payload, timeout)
    if isinstance(r, dict):  # node returned a single error object for the batch
        raise RpcError(r.get("error", {}).get("code"), str(r.get("error")))
    by_id = {x.get("id"): x for x in r}
    return [by_id.get(i, {}).get("result") for i in range(len(calls))]


def block_number(url=ADI_RPC):
    """Sealed head. Includes blocks that are not yet proven on L1."""
    return int(rpc("eth_blockNumber", [], url=url), 16)


# Blocks to hold back from the sealed head when the verified head is unknown.
# The observed sealed-to-verified gap on ADI runs to a few dozen blocks.
FALLBACK_CONFIRMATIONS = 200


def explorer_stats():
    """{lastSealedBlock, lastVerifiedBlock, totalTransactions} or None."""
    try:
        out = subprocess.check_output(
            ["curl", "-sS", "--max-time", "25", f"{ADI_EXPLORER_API}/stats"],
            stderr=subprocess.DEVNULL)
        d = json.loads(out)
        if "lastSealedBlock" in d:
            return d
    except Exception:
        pass
    return None


def safe_head(url=ADI_RPC, verbose=True):
    """Highest block safe to index: the last block proven on L1.

    ADI is a ZK Stack rollup, so `eth_blockNumber` returns the sealed head,
    which runs ahead of what has actually been verified. Indexing to the sealed
    tip means the newest rows can still change underneath us. The node does not
    expose the `zks_` finality methods, so the verified head comes from the
    explorer, with a confirmation buffer as the fallback.
    """
    stats = explorer_stats()
    sealed = block_number(url=url)
    if stats and stats.get("lastVerifiedBlock"):
        verified = int(stats["lastVerifiedBlock"])
        if verbose:
            print(f"head: sealed {sealed:,}, verified {verified:,} "
                  f"(indexing to verified, {sealed - verified} block gap held back)",
                  flush=True)
        return min(verified, sealed)
    head = max(0, sealed - FALLBACK_CONFIRMATIONS)
    if verbose:
        print(f"head: sealed {sealed:,}, verified head unavailable, "
              f"holding back {FALLBACK_CONFIRMATIONS} blocks -> {head:,}", flush=True)
    return head


def get_logs(address, topics, from_block, to_block, url=ADI_RPC, _depth=0):
    """eth_getLogs that splits its own range when the node caps the result set.

    `address` may be a single address or a list. `topics` follows the standard
    eth_getLogs shape and may be None.
    """
    flt = {"fromBlock": hex(from_block), "toBlock": hex(to_block)}
    if address:
        flt["address"] = address
    if topics:
        flt["topics"] = topics
    try:
        return rpc("eth_getLogs", [flt], url=url, timeout=180)
    except RpcError as e:
        msg = str(e)
        splittable = "max results" in msg or "max block range" in msg
        if splittable and to_block > from_block and _depth < 20:
            mid = (from_block + to_block) // 2
            return (get_logs(address, topics, from_block, mid, url, _depth + 1) +
                    get_logs(address, topics, mid + 1, to_block, url, _depth + 1))
        raise


def is_address_topic(topic):
    """True if a 32-byte topic is a left-padded, non-zero 20-byte address."""
    return (isinstance(topic, str) and len(topic) == 66
            and topic[2:26] == "0" * 24 and topic[26:] != "0" * 40)


def topic_to_address(topic):
    return "0x" + topic[26:].lower()
