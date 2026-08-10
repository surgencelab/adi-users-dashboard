import type { Dataset } from '../data/types';
import { lastComplete } from '../data/types';
import { Panel, Stat } from '../components/Panel';
import { Chart } from '../components/Chart';
import { fmtNum, fmtPct, shortAddr } from '../lib/format';

export function ChainActivity({ d }: { d: Dataset }) {
  const c = d.chain;
  const last = lastComplete(c.series);
  const peakTx = Math.max(...c.series.map((r) => r.txs));
  const peakTxDay = c.series.find((r) => r.txs === peakTx)?.date ?? '–';
  const peakSigners = Math.max(...c.series.map((r) => r.dau_signers));

  const top10 = c.top_senders.slice(0, 10).reduce((a, s) => a + s.txs, 0);
  const top10Share = c.total_txs ? (top10 / c.total_txs) * 100 : 0;

  return (
    <>
      <div className="callout">
        <b>Signers are not users.</b> The ten busiest addresses account for{' '}
        {fmtPct(top10Share)} of every transaction ever sent on ADI Chain. Those
        are application relayers and sequencer-side infrastructure. Treat this
        page as a throughput and infrastructure view; user counts live on the
        PredictStreet and Staking tabs.
      </div>

      <div className="stat-row">
        <Stat label="Transactions all-time" value={fmtNum(c.total_txs)} accent />
        <Stat label="Distinct signers all-time" value={fmtNum(c.total_distinct_senders)} />
        <Stat label={`Signers (${last?.date ?? '–'})`}
              value={fmtNum(last?.dau_signers ?? 0)}
              sub={`peak ${fmtNum(peakSigners)}`} />
        <Stat label="Signers (30d rolling)" value={fmtNum(last?.mau_signers ?? 0)} />
        <Stat label="Peak daily transactions" value={fmtNum(peakTx)} sub={peakTxDay} />
        <Stat label="Top-10 sender share" value={fmtPct(top10Share)}
              sub="of all transactions" />
      </div>

      <Panel title="Daily transactions" note="every transaction included in a sealed block" flush>
        <Chart
          data={c.series}
          xKey="date"
          height={280}
          series={[
            { key: 'txs', label: 'Transactions', color: 'var(--accent)', bars: true },
          ]}
        />
      </Panel>

      <div className="chart-grid">
        <Panel title="Distinct signers" note="daily and trailing-30d unique senders" flush>
          <Chart
            data={c.series}
            xKey="date"
            height={240}
            series={[
              { key: 'mau_signers', label: '30d rolling', color: 'var(--accent-blue)' },
              { key: 'dau_signers', label: 'Daily', color: 'var(--accent-green)' },
            ]}
          />
        </Panel>
        <Panel title="Distinct recipients" note="unique `to` addresses touched per day" flush>
          <Chart
            data={c.series}
            xKey="date"
            height={240}
            series={[
              { key: 'distinct_recipients', label: 'Recipients', color: 'var(--accent-cyan)' },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Busiest senders" note="all-time transaction counts — mostly operator wallets">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Address</th><th>Transactions</th><th>Share</th>
            </tr>
          </thead>
          <tbody>
            {c.top_senders.map((s, i) => (
              <tr key={s.address}>
                <td className="mono-dim">{i + 1}</td>
                <td className="addr">
                  <a
                    href={`${d.meta.adi_explorer}/address/${s.address}`}
                    target="_blank" rel="noreferrer"
                  >
                    {shortAddr(s.address)}
                  </a>
                </td>
                <td>{fmtNum(s.txs)}</td>
                <td className="mono-dim">
                  {fmtPct(c.total_txs ? (s.txs / c.total_txs) * 100 : 0, 2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Monthly" note="calendar-month signer counts and volume">
        <table>
          <thead>
            <tr><th>Month</th><th>Distinct signers</th><th>Transactions</th></tr>
          </thead>
          <tbody>
            {c.monthly.map((m) => (
              <tr key={m.month}>
                <td>{m.month}</td>
                <td>{fmtNum(m.mau_signers)}</td>
                <td>{fmtNum(m.txs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
