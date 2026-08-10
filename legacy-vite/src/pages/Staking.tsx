import type { Dataset } from '../data/types';
import { Panel, Stat } from '../components/Panel';
import { Chart } from '../components/Chart';
import { fmtNum } from '../lib/format';

export function Staking({ d }: { d: Dataset }) {
  const st = d.staking;
  if (!st) return <div className="loading">No staking data in this build.</div>;

  const last = st.series[st.series.length - 1];
  const first = st.series[0];
  const ev = st.event_counts;

  return (
    <>
      <div className="callout">
        The ADI HODLER staking programme runs on <b>Ethereum mainnet</b>, not on
        ADI Chain. Participants stake the ERC-20 ADI token at{' '}
        <code>{d.meta.contracts.staking_ethereum}</code>. Counts here are unique
        addresses, so one person using several wallets shows up more than once.
      </div>

      <div className="stat-row">
        <Stat label="Unique stakers" value={fmtNum(st.unique_stakers)}
              sub={`since ${first?.date ?? '–'}`} accent />
        <Stat label="Cumulative (latest)" value={fmtNum(last?.cumulative_stakers ?? 0)} />
        <Stat label="Active (30d)" value={fmtNum(last?.mau ?? 0)}
              sub="staked, harvested or claimed" />
        <Stat label="Stake events" value={fmtNum(ev.Staked ?? 0)} />
        <Stat label="Harvests" value={fmtNum(ev.Harvested ?? 0)} />
        <Stat label="Claims" value={fmtNum(ev.Claimed ?? 0)} />
      </div>

      <Panel title="Participants over time" note="cumulative unique stakers and daily actives" flush>
        <Chart
          data={st.series}
          xKey="date"
          height={280}
          series={[
            { key: 'cumulative_stakers', label: 'Cumulative stakers', color: 'var(--accent)' },
            { key: 'mau', label: 'Active (30d)', color: 'var(--accent-blue)' },
            { key: 'dau', label: 'Active that day', color: 'var(--accent-green)', bars: true },
          ]}
        />
      </Panel>

      <Panel title="Daily detail">
        <table>
          <thead>
            <tr>
              <th>Date</th><th>New stakers</th><th>Cumulative</th>
              <th>Active</th><th>Active (30d)</th>
            </tr>
          </thead>
          <tbody>
            {[...st.series].reverse().map((r) => (
              <tr key={r.date}>
                <td>{r.date}</td>
                <td>{r.new_stakers || <span className="mono-dim">0</span>}</td>
                <td>{fmtNum(r.cumulative_stakers)}</td>
                <td>{r.dau || <span className="mono-dim">0</span>}</td>
                <td>{fmtNum(r.mau)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
