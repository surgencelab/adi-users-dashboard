import type { ReactNode } from 'react';

export function Panel({
  title, note, children, flush = false,
}: { title: string; note?: string; children: ReactNode; flush?: boolean }) {
  return (
    <section className="panel">
      <header className="panel-head">
        <span className="panel-title">{title}</span>
        {note && <span className="panel-note">{note}</span>}
      </header>
      {flush ? children : <div className="panel-body">{children}</div>}
    </section>
  );
}

export function Stat({
  label, value, sub, accent = false,
}: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${accent ? ' accent' : ''}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
