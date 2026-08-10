import { useEffect, useState } from 'react';
import type { Dataset } from './data/types';
import { Overview } from './pages/Overview';
import { PredictStreet } from './pages/PredictStreet';
import { ChainActivity } from './pages/ChainActivity';
import { Staking } from './pages/Staking';
import { Methodology } from './pages/Methodology';

const TABS = ['Overview', 'PredictStreet', 'ADI Chain', 'Staking', 'Method'] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [data, setData] = useState<Dataset | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('Overview');
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('adi-users-theme') as 'dark' | 'light') || 'dark',
  );

  useEffect(() => {
    document.body.setAttribute('data-theme', theme);
    localStorage.setItem('adi-users-theme', theme);
  }, [theme]);

  useEffect(() => {
    fetch('data.json')
      .then((r) => {
        if (!r.ok) throw new Error(`data.json ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-tile">A</span>
          <span>
            <span className="brand-name">ADI · ACTIVE USERS</span>{' '}
            <span className="brand-sub">DAU / MAU terminal</span>
          </span>
        </div>
        <nav className="nav">
          {TABS.map((t) => (
            <button key={t} data-active={tab === t} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>
        <button
          className="icon-btn"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? 'LIGHT' : 'DARK'}
        </button>
      </header>

      <main>
        {err && <div className="error">Failed to load data.json — {err}</div>}
        {!err && !data && <div className="loading">Loading dataset…</div>}
        {data && tab === 'Overview' && <Overview d={data} onGo={setTab as any} />}
        {data && tab === 'PredictStreet' && <PredictStreet d={data} />}
        {data && tab === 'ADI Chain' && <ChainActivity d={data} />}
        {data && tab === 'Staking' && <Staking d={data} />}
        {data && tab === 'Method' && <Methodology d={data} />}
      </main>

      {data && (
        <footer className="statusbar">
          <span>CHAIN {data.meta.adi_chain_id}</span>
          <span>GENERATED {data.generated_at.slice(0, 16).replace('T', ' ')}Z</span>
          <span>MAU WINDOW {data.meta.rolling_window_days}D ROLLING</span>
          <span>SOURCE ADI RPC + ETHEREUM MAINNET</span>
        </footer>
      )}
    </div>
  );
}
