import type { Dataset } from '../data/types';
import { lastComplete } from '../data/types';
import { Panel, Stat } from '../components/Panel';
import { Chart } from '../components/Chart';
import { fmtNum, fmtPct } from '../lib/format';

export function PredictStreet({ d }: { d: Dataset }) {
  const ps = d.predictstreet;
  if (!ps) return <div className="loading">No PredictStreet data in this build.</div>;

  const last = lastComplete(ps.series) ?? ps.series[ps.series.length - 1];
  const peakDau = Math.max(...ps.series.map((r) => r.dau));
  const peakDauDay = ps.series.find((r) => r.dau === peakDau)?.date ?? '–';
  const peakReg = Math.max(...ps.series.map((r) => r.new_users));
  const peakRegDay = ps.series.find((r) => r.new_users === peakReg)?.date ?? '–';
  const peakMau = Math.max(...ps.series.map((r) => r.mau));

  const stickiness = last.mau > 0 ? (last.dau / last.mau) * 100 : null;
  const activation = (last.mau / ps.registered_total) * 100;

  return (
    <>
      <div className="stat-row">
        <Stat label="Registered users" value={fmtNum(ps.registered_total)}
              sub="cumulative vaults created" accent />
        <Stat label="Distinct owners" value={fmtNum(ps.distinct_owners)}
              sub="one vault per owner address" />
        <Stat label="MAU (30d rolling)" value={fmtNum(last.mau)}
              sub={`peak ${fmtNum(peakMau)}`} />
        <Stat label={`DAU (${last.date})`} value={fmtNum(last.dau)}
              sub={`peak ${fmtNum(peakDau)} on ${peakDauDay}`} />
        <Stat label="Activation" value={fmtPct(activation)} sub="MAU ÷ registered" />
        <Stat label="Stickiness" value={stickiness === null ? '–' : fmtPct(stickiness)}
              sub="DAU ÷ MAU" />
        <Stat label="Visible to a signer count"
              value={fmtPct(ps.signer_visible_pct, 2)}
              sub={`${fmtNum(ps.owners_that_self_signed)} owners ever self-signed`} />
      </div>

      <div className="callout">
        Vaults are plain contracts, not smart accounts:{' '}
        {ps.vaults_that_sent_txs === 0
          ? 'not one of them has ever sent a transaction'
          : `${fmtNum(ps.vaults_that_sent_txs)} have sent a transaction`}
        . User activity reaches the chain through operator relayers, which is why
        these counts are read from event topics rather than from senders.
      </div>

      <Panel
        title="Active users"
        note={`daily and trailing-${d.meta.rolling_window_days}-day unique vaults`}
        flush
      >
        <Chart
          data={ps.series}
          xKey="date"
          height={290}
          series={[
            { key: 'mau', label: 'MAU (30d)', color: 'var(--accent-blue)' },
            { key: 'dau', label: 'DAU', color: 'var(--accent-green)' },
          ]}
        />
      </Panel>

      <div className="chart-grid">
        <Panel title="Registrations" note={`peak ${fmtNum(peakReg)} on ${peakRegDay}`} flush>
          <Chart
            data={ps.series}
            xKey="date"
            height={240}
            series={[
              { key: 'new_users', label: 'New users/day', color: 'var(--accent)', bars: true },
              { key: 'registered_cumulative', label: 'Cumulative', color: 'var(--accent-orange)', right: true },
            ]}
          />
        </Panel>
        <Panel title="On-chain actions" note="settled events attributable to a user vault" flush>
          <Chart
            data={ps.series}
            xKey="date"
            height={240}
            series={[
              { key: 'actions', label: 'Actions', color: 'var(--accent-purple)', bars: true },
              { key: 'dau', label: 'DAU', color: 'var(--accent-green)', right: true },
            ]}
          />
        </Panel>
      </div>

      <Panel
        title="Monthly"
        note="calendar-month unique actives — not the same as the rolling MAU above"
      >
        <p className="panel-note" style={{ margin: '0 0 10px' }}>
          The rolling 30-day MAU still carries July's World Cup traffic forward.
          These calendar-month counts are the cleaner read on where engagement
          actually sits now.
        </p>
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>MAU</th>
              <th>New users</th>
              <th>MAU / new</th>
            </tr>
          </thead>
          <tbody>
            {ps.monthly.map((m) => (
              <tr key={m.month}>
                <td>{m.month}</td>
                <td>{fmtNum(m.mau)}</td>
                <td>{fmtNum(m.new_users)}</td>
                <td className="mono-dim">
                  {m.new_users ? (m.mau / m.new_users).toFixed(2) : '–'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel
        title="Event mix"
        note="event signatures seen on the PredictStreet contracts (unverified, so shown by selector)"
      >
        <table>
          <thead>
            <tr><th>Event selector</th><th>Occurrences</th></tr>
          </thead>
          <tbody>
            {ps.event_mix.map((e) => (
              <tr key={e.sig}>
                <td className="addr">{e.sig}</td>
                <td>{fmtNum(e.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
