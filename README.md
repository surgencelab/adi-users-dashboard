# ADI Active Users

DAU / MAU terminal for the ADI ecosystem, covering three surfaces:

| Surface | Metric | Where it lives |
|---|---|---|
| ADI Chain | daily / monthly active addresses, transactions | ADI Chain (ID 36900) |
| ADI PredictStreet | registered users, DAU, MAU | ADI Chain |
| ADI HODLER staking | staking participants | **Ethereum mainnet** |

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

A snapshot taken 2026-08-10. The dashboard is the live source; these drift and are
not auto-updated.

| | |
|---|---|
| PredictStreet registered users | 131,501 |
| PredictStreet MAU (30d rolling) | 18,354, peak 28,739 on 2026-07-21 |
| PredictStreet DAU | 37 on 2026-08-09, peak 12,666 on 2026-07-09 |
| Activation (MAU / registered) | 14.0% |
| Visible to a signer count | 0.33% (432 of 131,501) |
| HODLER stakers | 11, holding 277,301 ADI ($1,910,606) |
| Largest staker share | 89.15% |
| ADI Chain transactions | 1,454,602 since genesis 2025-11-25 |
| ADI Chain distinct signers | 4,228 all time |
| ADI price used | $6.89 |
