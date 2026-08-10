# ADI Active Users

DAU / MAU terminal for the ADI ecosystem, covering three surfaces:

| Surface | Metric | Where it lives |
|---|---|---|
| ADI Chain | daily / monthly active addresses, transactions | ADI Chain (ID 36900) |
| ADI PredictStreet | registered users, DAU, MAU, retention | ADI Chain |
| ADI HODLER staking | participants and value staked | **Ethereum mainnet** |

Built by Surgence Research on the Datum Labs Dashboard SDK.

## The thing to understand before reading any number

The obvious way to measure active addresses is to count distinct transaction
senders per day. On ADI Chain that number is close to meaningless.

PredictStreet produces the large majority of chain activity, and it submits
every user action through a rotating pool of roughly fifteen operator hot
wallets. Sample a thousand consecutive transactions to its contracts and you
get fewer than twenty distinct senders, each with a near-identical transaction
count. The signer count measures how many relayers the operator runs.

The users are one level down. The vault factory emits

```
VaultCreated(uint64, address indexed owner, address indexed vault)
```

once per account: the first indexed topic is the owner's address, the second
is a freshly deployed vault contract. Every subsequent PredictStreet event
references that vault in an indexed topic, so the vault is a durable per-user
identifier and user metrics fall straight out of it. Registered-user counts
from this pipeline are a direct count of `VaultCreated` events, not a proxy.

The size of the gap is measurable, and the pipeline computes it rather than
asserting it: only 0.33% of registered users have ever signed an ADI Chain
transaction from their own address. The vaults are plain contracts rather than
smart accounts, and **not one of them has ever sent a transaction** in the
chain's 1.45M. A daily-active-address chart built from senders would omit
99.67% of the people using the application.

## Headline figures

A snapshot taken 2026-08-10. The dashboard is the live source; these drift and
are not auto-updated.

| | |
|---|---|
| PredictStreet registered users | 131,507 |
| PredictStreet MAU (30d rolling) | 18,354, peak 28,739 on 2026-07-21 |
| PredictStreet DAU | 37 on 2026-08-09, peak 12,666 on 2026-07-09 |
| Activation (MAU / registered) | 14.0% |
| Visible to a signer count | 0.33% (432 of 131,507) |
| Ever did anything after signing up | 21.9% |
| Came back on a later day | 14.3% |
| Still active after 30 days | **0.22%** (288 people) |
| HODLER stakers | 11, holding 277,301 ADI (about $1.91M) |
| Largest staker share | 89.15% |
| Pool utilisation | 9.24% of the 3,000,000 ADI cap |
| ADI Chain transactions | 1,454,888 since genesis 2025-11-25 |
| ADI Chain distinct signers | 4,228 all time, 52 to 195 on a typical day |

Registrations are heavily World Cup shaped: 114,212 new users in July 2026
against roughly 2,200 in August. The rolling 30-day MAU therefore carries July
traffic forward, and the calendar-month figures on the PredictStreet tab are
the cleaner read on current engagement.

One chain-wide anomaly worth knowing about: on 8 and 9 July 2026 roughly 2,950
distinct addresses sent transactions, only 97 of them overlapping across the
two days, and volume peaked at 97,482 transactions. That burst is what makes
the 30-day rolling signer line fall away in early August as those addresses age
out of the window.

## Metric definitions

- **DAU**: distinct actors in a UTC calendar day.
- **MAU**: distinct actors over the trailing 30 days ending on that day.
  Calendar-month figures are reported separately on each tab.
- **Actor**: a user vault for PredictStreet, a staker address for staking, a
  transaction sender for the chain-wide view. The chain-wide one is labelled as
  such throughout, since it counts infrastructure rather than people.
- **Retention**: cohorts are the week a person signed up, and every window is
  measured from each person's own sign-up day. Windows a cohort has not lived
  through yet report `n/a`, never 0%.

## Staking, in ADI and USD

Eleven wallets hold **277,301 ADI**, worth about **$1.91M**. One of them holds
89.15% of it.

| | ADI | USD (approx) |
|---|---:|---:|
| Principal staked | 277,301 | $1.91M |
| Reward pool funded | 250,000 | $1.72M |
| Rewards already claimed | 20,227 | $139k |
| **Contract balance** | **507,075** | **$3.48M** |
| Pool cap | 3,000,000 | $20.6M |

Rewards flow before any lock matures because the lock governs the principal,
not the rewards: the programme config sets both `vestingPeriod` and `cliff` to
one second. The first claim landed 1.1 hours after the first stake.

The advertised ~18% APY assumes a full pool. Emission is fixed at about 1,374
ADI per day regardless of participation, so with the pool 9.24% full the
current stakers are earning far more than the headline rate.

Three checks confirm the decoded amounts: the principals sum to exactly the
pool total the ADI staking app itself displays; the ratio between the event's
first two words lands on the 0.58x / 1.17x / 1.75x lock multipliers the app
offers; and principal plus funded rewards less claimed rewards matches the
contract's token balance to 0.000%.

USD is a spot valuation and moves with the ADI price.

## Run it

A Datum Labs Dashboard SDK build: static HTML with React and Babel from a CDN,
and **no build step**. Serve the directory and open it.

```bash
python3 -m http.server 5190
```

Pages: `index.html`, `predictstreet.html`, `chain.html`, `staking.html`,
`methodology.html`.

```bash
python3 scripts/refresh_all.py   # rebuild the whole dataset
python3 scripts/validate.py      # check without publishing
```

### Deploying

The repo is connected to Vercel, so **a push to `main` deploys**. There is no
build step: the framework preset is Other with no build or install command.

Bump the `?v=` query on `styles.css` and the `.jsx` files whenever you change
them. They are cached hard, and without a bump viewers keep the old copy.

If a deployment is blocked with a complaint about the commit author's email,
the address is almost certainly fine. Vercel struggles to resolve
`users.noreply.github.com` addresses to a GitHub account and blocks when it
cannot match the author to someone with project access. The fix is to link the
authoring GitHub account under Vercel's Login Connections, not to rewrite the
email.

The previous Vite build is kept under `legacy-vite/` and is no longer
maintained.

## Where the data lives

| Tier | What | Size | Where |
|---|---|---|---|
| Raw index | blocks, transactions, PredictStreet logs, staking events | ~107 MB gz | `data/`, git-ignored, cached in CI |
| Analytical | daily grain, ~1M rows | ~140 MB | Neon Postgres |
| Published | `data.json` | ~50 KB | Project root, committed |

`data.json` is committed on purpose. At 50 KB it diffs cleanly, so the git
history doubles as an audit trail of every metric change.

Postgres holds the **daily grain, not the raw event log**. The raw 15M rows
answer no question anyone actually asks; the rollups answer all of them in
about 1M rows. Everything upserts on a natural key, so a repeated load is a
no-op. The dashboard reads `data.json` and never touches the database, so it
keeps working if Neon is unreachable.

Tables: `blocks`, `chain_daily`, `chain_sender_daily`, `chain_sender_totals`,
`ps_vaults`, `ps_activity_daily`, `staking_events`, `metric_snapshots`.

## Keeping it fresh and correct

**Freshness**

- `.github/workflows/refresh-data.yml` runs daily at 06:20 UTC, after the
  previous UTC day has closed, and takes a manual trigger.
- Both ADI indexers are incremental and resume from where they stopped. A daily
  run takes about **2 minutes** against two hours for a cold backfill. CI caches
  `data/` so the incremental path applies.
- The topbar carries a graded freshness badge rather than a bare timestamp:
  green under 26h, amber under 72h, red beyond. The ADI price is graded
  separately, since it can rot while every on-chain figure stays correct.

**Accuracy**

- **Nothing publishes unless it validates.** `build_dataset.py` writes
  `data.json.candidate`; `validate.py` promotes it only if every check passes.
  A failed run leaves the previous dataset in place: stale but true beats fresh
  but wrong.
- **Only verified blocks are indexed.** ADI is a ZK rollup whose sealed head
  runs 12 to 14 blocks ahead of what is proven on L1. `refresh_all.py` resolves
  the verified head once and pins every indexer to it, so all steps cover an
  identical range and nothing enters the dataset that could still change.
- **Monotonic guards.** Registered users, distinct owners, transactions,
  signers and stakers can never fall between publishes. This is the check that
  matters most: every real failure so far has been silent truncation, such as a
  public RPC returning 90 of 159 logs while reporting success.
- **Reconciliation.** Chain totals against the explorer's own counter, and
  staking principal plus funded rewards less claimed against the contract's
  token balance.
- **Schema version** on `data.json` so a stale page cannot render an
  incompatible dataset.

## Pipeline

`scripts/refresh_all.py` runs six steps in order:

| Script | What it does |
|---|---|
| `index_blocks.py` | Every ADI Chain block with full transaction bodies. Incremental. Calldata discarded, only sender and recipient kept. |
| `index_predictstreet.py` | Streams logs from the two PredictStreet contracts, builds the vault registry, attributes all other events to vaults. Incremental via a checkpoint. |
| `index_staking.py` | Ethereum staking events, amounts and the ADI spot price. Prefers Dune when `DUNE_API_KEY` is set. |
| `build_dataset.py` | Joins everything into `data.json.candidate`, including retention cohorts. |
| `validate.py` | The publish gate. Registry invariants, topic order sampled against the chain, monotonic guards, reconciliation. Promotes only on a full pass. |
| `load_db.py` | Loads the daily grain into Postgres. Skips itself when `DATABASE_URL` is unset. |

Add `--full` to force a complete PredictStreet re-scan, only needed if the log
file is damaged.

### Environment

None required. All optional, all in `.env` (git-ignored, see `.env.example`):

- `DATABASE_URL`: Neon Postgres. Without it the pipeline still produces
  `data.json` and the dashboard works.
- `ETH_RPC_URL`: a paid Ethereum endpoint, to avoid free-tier rate limits.
- `DUNE_API_KEY`: pulls staking events from Dune instead of public RPC.
- `ADI_RPC_URL`: overrides the ADI Chain RPC.

Free Ethereum RPCs are the weak link. Surveyed 2026-08-10 against the staking
contract's log range: `gateway.tenderly.co` and `rpc.mevblocker.io` both handle
10,000-block `eth_getLogs` with no key and are the defaults; `eth.drpc.org`
caps near 2,000 blocks and exhausts its quota quickly; `publicnode` and `ankr`
want a token; `blastapi`, `1rpc` and `pokt` cap at 10 to 50 blocks;
`cloudflare-eth` rejects the range; `llamarpc` returns non-JSON.
`rpc.flashbots.net` answers `200` with **zero logs**, which is why it is
explicitly excluded: a silent empty result is worse than an error.

## Contracts

| What | Address | Chain |
|---|---|---|
| PredictStreet settlement | `0x79ACbb874dd01044FA38a89c1478E60FaAB40D00` | ADI |
| PredictStreet vault factory | `0xc16B8b190064451c2FeEb2e77c4B2aC4c7009552` | ADI |
| HODLER staking | `0xEA6aAd1A44232B6C7f92A4103698D9Faf3aFE241` | Ethereum |
| ADI token (ERC-20) | `0x8b1484d57abbe239bb280661377363b03c89caea` | Ethereum |

Staking addresses were read from the runtime configuration served by
dashboard.adi.foundation. None of the PredictStreet contracts are verified, so
event names come from openchain.xyz where they resolve, and attribution is
deliberately ABI-agnostic: any indexed topic matching a known vault counts as
that user acting. That survives contract upgrades and unnamed events.

## Endpoints

- RPC `https://rpc.adifoundation.ai`, chain ID 36900, a ZK Stack L2, genesis
  2025-11-25. `eth_getLogs` accepts 100,000-block ranges capped at 20,000
  results; JSON-RPC batching works well at 200 to 500 calls.
- Explorer `https://explorer.adifoundation.ai`, API
  `https://explorer-api.adifoundation.ai`. Paginated endpoints cap at 10,000
  items, which is why this pipeline indexes from RPC instead.

ADI Chain is not indexed by Dune, so there is no third-party dataset to fall
back on for the chain and PredictStreet metrics. The Ethereum staking figures
are cross-checked against Dune and the two agree exactly.

## Known limits

- An account that registers but never trades still counts as registered. The
  gap between registered users and MAU is the activation rate.
- Off-chain sessions leave no trace. Someone browsing markets without settling
  on chain is invisible here. These are a floor on engagement, not a substitute
  for web analytics.
- Counts are per address, not per person. Someone with several wallets is
  counted several times.
- USD figures are a spot valuation, not a mark to market of each deposit at the
  time it was made.

## Local deviations from the SDK

Both are scoped to this dashboard and are **not** upstreamed. The SDK keeps its
own behaviour.

- `charts.jsx` makes the chart watermark overridable via
  `window.CHART_WATERMARK`, set to `SURGENCE RESEARCH` here. The SDK keeps
  `DATUM LABS · DEMO`.
- The branded boot splash and nav splash are removed. The SDK keeps them as its
  canonical transition state.
