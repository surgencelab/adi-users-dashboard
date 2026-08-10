#!/usr/bin/env python3
"""Postgres (Neon) connection and schema for the ADI users dataset.

What goes in Postgres, and what deliberately does not.

The raw index is ~15M rows of event log. Loading all of it would need a paid
tier and would buy nothing: no question anyone asks is answered by an
individual transaction row. What the questions need is the daily grain, so
that is what lives here:

    blocks               825k   block -> time, the join key for everything else
    chain_daily            ~260  per-day transaction and address counts
    chain_sender_daily     ~15k  (day, sender) for rolling distinct counts
    chain_sender_totals    ~4k   all-time totals per sender
    ps_vaults             131k   one row per PredictStreet user
    ps_activity_daily      ~54k  (day, vault) with an action count
    staking_events         ~160  every staking event, small enough to keep raw
    metric_snapshots         1/run  headline figures, for change tracking

That is about 1M rows and roughly 100 MB, which fits Neon's free tier. The raw
gzipped JSONL stays on disk and in the CI cache as the re-derivation source;
Postgres is the queryable layer, not the archive.

Everything upserts on a natural key, so re-running a load is a no-op rather
than a duplicate.
"""
import os
import sys

DDL = """
CREATE TABLE IF NOT EXISTS blocks (
    number      BIGINT PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL,
    tx_count    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS blocks_ts_idx ON blocks (ts);

CREATE TABLE IF NOT EXISTS chain_daily (
    day                  DATE PRIMARY KEY,
    txs                  BIGINT NOT NULL,
    blocks               BIGINT NOT NULL,
    distinct_senders     INTEGER NOT NULL,
    distinct_recipients  INTEGER NOT NULL,
    partial              BOOLEAN NOT NULL DEFAULT FALSE
);

-- One row per (day, sender). Rolling distinct counts over any window are a
-- single query against this, which is why the raw transactions are not loaded.
CREATE TABLE IF NOT EXISTS chain_sender_daily (
    day      DATE NOT NULL,
    sender   TEXT NOT NULL,
    txs      INTEGER NOT NULL,
    PRIMARY KEY (day, sender)
);
CREATE INDEX IF NOT EXISTS chain_sender_daily_sender_idx ON chain_sender_daily (sender);

CREATE TABLE IF NOT EXISTS chain_sender_totals (
    sender   TEXT PRIMARY KEY,
    txs      BIGINT NOT NULL
);

-- The PredictStreet user table. `vault` is the per-user contract the factory
-- deploys; `owner` is the person's own address. One row per user.
CREATE TABLE IF NOT EXISTS ps_vaults (
    vault          TEXT PRIMARY KEY,
    owner          TEXT NOT NULL,
    created_block  BIGINT NOT NULL,
    created_day    DATE
);
CREATE INDEX IF NOT EXISTS ps_vaults_owner_idx ON ps_vaults (owner);
CREATE INDEX IF NOT EXISTS ps_vaults_created_day_idx ON ps_vaults (created_day);

-- (day, vault) with an action count. DAU, MAU and retention cohorts all come
-- out of this joined against ps_vaults.created_day.
CREATE TABLE IF NOT EXISTS ps_activity_daily (
    day      DATE NOT NULL,
    vault    TEXT NOT NULL,
    actions  INTEGER NOT NULL,
    PRIMARY KEY (day, vault)
);
CREATE INDEX IF NOT EXISTS ps_activity_daily_vault_idx ON ps_activity_daily (vault);

-- `staker` is '' rather than NULL for the events that have no participant
-- (Accrued, Funded), because a NULL column cannot take part in a primary key.
CREATE TABLE IF NOT EXISTS staking_events (
    tx        TEXT NOT NULL,
    block     BIGINT NOT NULL,
    action    TEXT NOT NULL,
    staker    TEXT NOT NULL DEFAULT '',
    amount    NUMERIC,
    weighted  NUMERIC,
    ts        TIMESTAMPTZ,
    PRIMARY KEY (tx, action, block, staker)
);
CREATE INDEX IF NOT EXISTS staking_events_staker_idx ON staking_events (staker);

-- One row per successful publish. Gives a queryable history of the headline
-- figures, alongside the git history of data.json.
CREATE TABLE IF NOT EXISTS metric_snapshots (
    generated_at            TIMESTAMPTZ PRIMARY KEY,
    schema_version          INTEGER,
    ps_registered           BIGINT,
    ps_dau                  BIGINT,
    ps_mau                  BIGINT,
    ps_signer_visible_pct   NUMERIC,
    chain_txs               BIGINT,
    chain_distinct_senders  BIGINT,
    staking_participants    INTEGER,
    staking_adi             NUMERIC,
    staking_usd             NUMERIC,
    adi_price_usd           NUMERIC
);
"""


def connect():
    """psycopg connection from DATABASE_URL. Exits with guidance if unset."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "  Neon: create a project at https://neon.tech, copy the pooled\n"
            "  connection string, then either export it or add it to .env:\n"
            "    DATABASE_URL=postgresql://user:pass@host/db?sslmode=require"
        )
    try:
        import psycopg
    except ImportError:
        sys.exit("psycopg is not installed. Run: python3 -m pip install 'psycopg[binary]'")
    return psycopg.connect(url, autocommit=False)


def load_dotenv(path=None):
    """Minimal .env reader so DATABASE_URL can live beside the project.

    Deliberately does not overwrite an already-set variable, so CI secrets win
    over whatever happens to be on a developer's disk.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = path or os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


if __name__ == "__main__":
    load_dotenv()
    conn = connect()
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name,
                   (xpath('/row/c/text()',
                     query_to_xml('SELECT COUNT(*) c FROM ' || quote_ident(table_name),
                                  false, true, '')))[1]::text::bigint AS rows
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        print("schema ready:")
        for name, rows in cur.fetchall():
            print(f"  {name:24s} {rows:>10,} rows")
    conn.close()
