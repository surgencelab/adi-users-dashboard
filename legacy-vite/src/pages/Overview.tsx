import type { Dataset } from '../data/types';
import { lastComplete } from '../data/types';
import { Panel, Stat } from '../components/Panel';
import { Chart } from '../components/Chart';
import { fmtNum, fmtPct } from '../lib/format';

export function Overview({ d, onGo }: { d: Dataset; onGo: (t: string) => void }) {
  const ps = d.predictstreet;
  const st = d.staking;
  const chain = d.chain;

  // Headlines read from the last COMPLETE day: a refresh usually lands mid-day,
  // and a half-day of data looks identical to a collapse in DAU.
  const psLast = ps ? lastComplete(ps.series) : undefined;
  const chainLast = lastComplete(chain.series);
  const stLast = st?.series[st.series.length - 1];
  const asOf = psLast?.date ?? chainLast?.date;

  const recent = ps ? ps.series.slice(-30) : [];
  const peakDau = recent.length ? Math.max(...recent.map((r) => r.dau)) : 0;
  const stickiness = psLast && psLast.mau > 0 ? (psLast.dau / psLast.mau) * 100 : null;
  const activation = ps && psLast
    ? (psLast.mau / ps.registered_total) * 100
    : null;

  return (
    <>
      <div className="callout">
        <b>Counting transaction signers would miss almost everyone.</b>{' '}
        {ps ? (
          <>
            PredictStreet relays user actions through a small pool of operator
            wallets, and its per-user vaults never send transactions themselves.
            Of {fmtNum(ps.distinct_owners)} registered users, only{' '}
            {fmtNum(ps.owners_that_self_signed)} have ever signed a transaction
            directly — {fmtPct(ps.signer_visible_pct, 2)}. The other{' '}
            {fmtPct(100 - ps.signer_visible_pct, 2)} are invisible to a signer
            count but fully visible at the vault level.
          </>
        ) : (
          <>
            PredictStreet relays user actions through a small pool of operator
            wallets, so ADI Chain's transaction-signer count measures
            infrastructure rather than people.
          </>
        )}{' '}
        <a
          style={{ color: 'var(--accent)', cursor: 'pointer' }}
          onClick={() => onGo('Method')}
        >
          How this is measured →
        </a>
      </div>

      <div className="stat-row">
        <Stat
          label="PredictStreet registered"
          value={fmtNum(ps?.registered_total ?? 0)}
          sub="cumulative user vaults created"
          accent
        />
        <Stat
          label="PredictStreet MAU"
          value={fmtNum(psLast?.mau ?? 0)}
          sub={`trailing ${d.meta.rolling_window_days}d unique vaults`}
        />
        <Stat
          label="PredictStreet DAU"
          value={fmtNum(psLast?.dau ?? 0)}
          sub={`peak ${fmtNum(peakDau)} in last 30d`}
        />
        <Stat
          label="Staking participants"
          value={fmtNum(st?.unique_stakers ?? 0)}
          sub="unique stakers, Ethereum mainnet"
        />
        <Stat
          label="Chain signers"
          value={fmtNum(chainLast?.dau_signers ?? 0)}
          sub="operator wallets, not users"
        />
      </div>

      {asOf && (
        <p className="panel-note" style={{ margin: '-8px 0 14px' }}>
          Daily figures as of {asOf} (last complete UTC day)
          {d.partial_day ? `; ${d.partial_day} is still in progress` : ''}.
        </p>
      )}

      <div className="stat-row">
        <Stat
          label="Activation rate"
          value={activation === null ? '–' : fmtPct(activation)}
          sub="MAU ÷ registered users"
        />
        <Stat
          label="Stickiness"
          value={stickiness === null ? '–' : fmtPct(stickiness)}
          sub="DAU ÷ MAU"
        />
        <Stat
          label="Chain transactions"
          value={fmtNum(chain.total_txs)}
          sub="all-time on ADI Chain"
        />
        <Stat
          label="Distinct signers all-time"
          value={fmtNum(chain.total_distinct_senders)}
          sub="every address that ever sent a tx"
        />
      </div>

      {ps && (
        <Panel
          title="PredictStreet — registered users vs active users"
          note="cumulative registrations (right axis) against daily and rolling-30d actives"
          flush
        >
          <Chart
            data={ps.series}
            xKey="date"
            height={280}
            series={[
              { key: 'registered_cumulative', label: 'Registered (cum.)', color: 'var(--accent)', right: true },
              { key: 'mau', label: 'MAU (30d)', color: 'var(--accent-blue)' },
              { key: 'dau', label: 'DAU', color: 'var(--accent-green)' },
            ]}
          />
        </Panel>
      )}

      <div className="chart-grid">
        {ps && (
          <Panel title="New registrations per day" note="VaultCreated events" flush>
            <Chart
              data={ps.series}
              xKey="date"
              height={230}
              series={[{ key: 'new_users', label: 'New users', color: 'var(--accent)', bars: true }]}
            />
          </Panel>
        )}
        <Panel
          title="ADI Chain throughput"
          note="transactions per day against distinct signers"
          flush
        >
          <Chart
            data={chain.series}
            xKey="date"
            height={230}
            series={[
              { key: 'txs', label: 'Transactions', color: 'var(--accent-purple)', bars: true },
              { key: 'dau_signers', label: 'Distinct signers', color: 'var(--accent-cyan)', right: true },
            ]}
          />
        </Panel>
      </div>

      {st && stLast && (
        <Panel
          title="ADI HODLER staking — cumulative participants"
          note={`${st.unique_stakers} unique stakers since the programme opened`}
          flush
        >
          <Chart
            data={st.series}
            xKey="date"
            height={210}
            series={[
              { key: 'cumulative_stakers', label: 'Cumulative stakers', color: 'var(--accent)' },
              { key: 'dau', label: 'Active that day', color: 'var(--accent-green)', bars: true },
            ]}
          />
        </Panel>
      )}
    </>
  );
}
