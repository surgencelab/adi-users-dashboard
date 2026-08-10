import type { Dataset } from '../data/types';
import { Panel } from '../components/Panel';

export function Methodology({ d }: { d: Dataset }) {
  const c = d.meta.contracts;
  const ps = d.predictstreet;
  return (
    <div className="prose">
      <Panel title="What counts as a user">
        <h3>The problem with signer counts</h3>
        <p>
          The obvious way to measure active addresses on an EVM chain is to
          count distinct transaction senders per day. On ADI Chain that number
          is close to meaningless. PredictStreet, which produces the large
          majority of chain activity, submits every user action through a
          rotating pool of roughly fifteen operator hot wallets. Sampling a
          thousand consecutive transactions to its contracts returns fewer than
          twenty distinct senders, each with a near-identical transaction count.
          Counting signers measures how many relayers the operator runs.
        </p>
        {ps && (
          <p>
            The size of the gap is measurable rather than rhetorical. Of{' '}
            <b>{ps.distinct_owners.toLocaleString('en-US')}</b> registered users,
            only <b>{ps.owners_that_self_signed.toLocaleString('en-US')}</b> have
            ever signed an ADI Chain transaction from their own address —{' '}
            <b>{ps.signer_visible_pct}%</b>. The vaults themselves are plain
            contracts rather than smart accounts, and{' '}
            {ps.vaults_that_sent_txs === 0
              ? 'not one has ever sent a transaction'
              : `${ps.vaults_that_sent_txs.toLocaleString('en-US')} have sent one`}
            . So a daily-active-address chart built from senders would omit
            roughly {(100 - ps.signer_visible_pct).toFixed(0)}% of the people
            using the application.
          </p>
        )}

        <h3>Where the users actually are</h3>
        <p>
          One level down, each account gets its own contract. The factory at{' '}
          <code>{c.predictstreet_vault_factory}</code> emits{' '}
          <code>VaultCreated(uint64, address indexed owner, address indexed vault)</code>{' '}
          once per account: the first indexed topic is the owner's address, the
          second is a freshly deployed vault. Every subsequent PredictStreet
          event references that vault in an indexed topic. So the vault is a
          durable per-user identifier, and user metrics fall straight out of it:
        </p>
        <ul>
          <li>
            <b>Registered users</b> — cumulative count of distinct{' '}
            <code>VaultCreated</code> events. This is a direct count, not a
            proxy or an estimate.
          </li>
          <li>
            <b>DAU</b> — distinct vaults referenced by any non-registration
            event in a UTC calendar day.
          </li>
          <li>
            <b>MAU</b> — distinct vaults over the trailing{' '}
            {d.meta.rolling_window_days} days ending on that day. Calendar-month
            figures are reported separately on the PredictStreet tab.
          </li>
        </ul>
        <p>
          Attribution is deliberately ABI-agnostic. None of the PredictStreet
          contracts are verified, so rather than guessing each event's parameter
          layout, the indexer treats any indexed topic matching a known vault as
          evidence that the user acted. That is robust to contract upgrades and
          to events we have not identified by name.
        </p>

        <h3>Known limits</h3>
        <ul>
          <li>
            An account that registers but never trades still counts as
            registered. The gap between registered users and MAU is the
            activation rate, shown on the Overview tab.
          </li>
          <li>
            Off-chain sessions leave no trace. Someone who browses markets
            without settling anything on chain is invisible here. These figures
            are a floor on engagement, not a web-analytics substitute.
          </li>
          <li>
            Counts are per address, not per person. A user with several wallets
            is counted several times; a custodial account shared by two people
            is counted once.
          </li>
          <li>
            Users who registered before the contracts we index were deployed, or
            through a path that emits no <code>VaultCreated</code>, would be
            missed. We found no evidence of either.
          </li>
        </ul>
      </Panel>

      <Panel title="Sources">
        <h3>ADI Chain</h3>
        <ul>
          <li>JSON-RPC <code>{d.meta.adi_rpc}</code>, chain ID {d.meta.adi_chain_id}, a ZK Stack L2.</li>
          <li>Every block from genesis is pulled with full transaction bodies; sender and recipient are kept, calldata discarded.</li>
          <li>Explorer for cross-checks: <code>{d.meta.adi_explorer}</code>.</li>
          <li>ADI Chain is not indexed by Dune, so there is no third-party dataset to fall back on; this pipeline builds its own index.</li>
        </ul>

        <h3>PredictStreet</h3>
        <ul>
          <li>Settlement <code>{c.predictstreet_settlement}</code></li>
          <li>Vault factory <code>{c.predictstreet_vault_factory}</code></li>
          <li>Both deployed 2026-05-30; the app went live 2026-06-08.</li>
        </ul>

        <h3>ADI HODLER staking</h3>
        <ul>
          <li>Staking <code>{c.staking_ethereum}</code> on Ethereum mainnet.</li>
          <li>ADI token <code>{c.adi_token_ethereum}</code>.</li>
          <li>
            Contract addresses were read from the runtime configuration served by
            dashboard.adi.foundation. Event names came from openchain.xyz, since
            the contract is unverified. Participant counts were computed twice —
            once by direct RPC log scan, once independently in Dune against{' '}
            <code>ethereum.logs</code> — and the two agree.
          </li>
        </ul>
      </Panel>

      <Panel title="Refresh">
        <p>
          <code>python3 scripts/refresh_all.py</code> re-runs the whole pipeline.
          The block scan is incremental: it resumes from the highest block
          already on disk, so routine refreshes only pull new blocks.
        </p>
        <p className="mono-dim">
          Dataset generated {d.generated_at.replace('T', ' ').slice(0, 19)}Z.
        </p>
      </Panel>
    </div>
  );
}
