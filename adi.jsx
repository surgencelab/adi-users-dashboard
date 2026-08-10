/* ADI Active Users - shared shell, data loading and helpers.
 * Loaded after charts.jsx and widgets.jsx, before each page's App script.
 * Everything registers on window, matching the SDK convention.
 */

/* Chart watermark. The SDK ships "DATUM LABS · DEMO" hardcoded, which does not
 * belong on a delivered dashboard. Set to '' to remove it entirely. */
window.CHART_WATERMARK = 'SURGENCE RESEARCH';

const ADI_NAV = [
  { id: 'overview',      label: 'Overview',      href: 'index.html' },
  { id: 'predictstreet', label: 'PredictStreet', href: 'predictstreet.html' },
  { id: 'chain',         label: 'ADI Chain',     href: 'chain.html' },
  { id: 'staking',       label: 'Staking',       href: 'staking.html' },
  { id: 'methodology',   label: 'Methodology',   href: 'methodology.html' },
];

/* ── formatting ───────────────────────────────────────────────────────── */

/* Exact integer count with thousand separators.
 * The SDK's fmtNum always compacts (131494 -> "131.49K"), which is right for a
 * chart axis and wrong for a headline: the precise figure is the point here.
 * Use fmtNum on axes and tooltips, fmtCount for KPI values and table cells. */
function fmtCount(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return 'n/a';
  return Math.round(n).toLocaleString('en-US');
}

/* Exact USD, no compaction. For totals a reader may want to quote. */
function fmtUSDExact(n, dp) {
  if (n === null || n === undefined || Number.isNaN(n)) return 'n/a';
  return '$' + n.toLocaleString('en-US', {
    minimumFractionDigits: dp === undefined ? 0 : dp,
    maximumFractionDigits: dp === undefined ? 0 : dp,
  });
}

function fmtADI(n, dp) {
  if (n === null || n === undefined || Number.isNaN(n)) return 'n/a';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: dp === undefined ? 0 : dp,
    maximumFractionDigits: dp === undefined ? 0 : dp,
  }) + ' ADI';
}

function fmtDate(iso) {
  if (!iso) return 'n/a';
  const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const p = iso.split('-');
  return `${p[2]} ${M[Number(p[1]) - 1]}`;
}

function shortAddr(a) {
  return !a ? 'n/a' : (a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);
}

/* ── data ─────────────────────────────────────────────────────────────── */

function useDataset() {
  const [state, setState] = React.useState({ data: null, error: null });
  React.useEffect(() => {
    let alive = true;
    fetch('data.json?v=' + Date.now())
      .then((r) => {
        if (!r.ok) throw new Error(`data.json returned ${r.status}`);
        return r.json();
      })
      .then((d) => { if (alive) setState({ data: d, error: null }); })
      .catch((e) => { if (alive) setState({ data: null, error: String(e) }); });
    return () => { alive = false; };
  }, []);
  return state;
}

/* Measure the wrapping element so charts fill their panel and refit on resize.
 * One instance per chart, never shared: a chart in a half-width grid would
 * otherwise leak its narrow width into a full-width one. */
function useElementWidth(initial) {
  const ref = React.useRef(null);
  const [w, setW] = React.useState(initial || 900);
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const cw = Math.floor(el.clientWidth);
      if (cw > 0) setW(cw);
    };
    measure();
    let ro;
    if (window.ResizeObserver) { ro = new ResizeObserver(measure); ro.observe(el); }
    window.addEventListener('resize', measure);
    return () => { if (ro) ro.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  return [ref, w];
}

/* Height scales with measured width so mobile charts stay in proportion. */
function chartHeight(w) {
  return w >= 1100 ? 340 : w >= 760 ? 300 : 240;
}

/* ── shell ────────────────────────────────────────────────────────────── */

function ThemeToggle() {
  const [theme, setTheme] = React.useState(
    () => document.body.getAttribute('data-theme') || 'light');
  const flip = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.body.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
    setTheme(next);
  };
  return (
    <button className="icon-btn" onClick={flip}
      title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}>
      {theme === 'dark' ? 'Light' : 'Dark'}
    </button>
  );
}

function Sidebar({ active }) {
  // No nav splash: the branded loading overlay has been removed, and
  // showNavSplash() would re-inject exactly the mark we took out.
  const go = (e, href) => {
    e.preventDefault();
    window.location.href = href;
  };
  // Structure follows the SDK's own shell: section divs holding the nav items,
  // then a final div that the mobile rules hide. At <=720px the sidebar becomes
  // a horizontal bottom tab bar, and the rules that do that select `div`
  // children, so a <nav> wrapper here would leave the items stacked vertically.
  // Branding lives in the topbar, not here, for the same reason.
  return (
    <aside className="sidebar">
      <div>
        <div className="sidebar-section-label">Surfaces</div>
        {ADI_NAV.map((n) => (
          <a key={n.id} href={n.href}
            className={`nav-item ${active === n.id ? 'active' : ''}`}
            onClick={(e) => (active === n.id ? e.preventDefault() : go(e, n.href))}>
            <span>{n.label}</span>
          </a>
        ))}
      </div>
      <div style={{ marginTop: 'auto', padding: '16px 10px 8px', borderTop: '1px solid var(--border)' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--fg-muted)', lineHeight: 1.5 }}>
          Built by Surgence Research with{' '}
          <span style={{ whiteSpace: 'nowrap' }}>
            @datumlabs/<span style={{ color: 'var(--orange)' }}>dashboard-kit</span>
          </span>
        </div>
      </div>
    </aside>
  );
}

/* Freshness thresholds, in hours. The pipeline is meant to run daily, so a
 * dataset older than a day and a bit has missed a run. */
const FRESH_H = 26;
const DEGRADED_H = 72;

function hoursSince(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 3.6e6;
}

/* Age as a state, not a timestamp.
 * A three-week-old dataset and a fresh one look identical if all you print is
 * "generated at", so grade it and let the badge carry the warning. The price
 * is graded separately: it can rot while every on-chain figure stays correct,
 * and it silently mis-states every USD number when it does. */
function FreshnessBadge({ data }) {
  const dataAge = hoursSince(data && data.generated_at);
  const price = (data && data.staking && data.staking.price) || null;
  const priceAge = hoursSince(price && price.fetched_at);

  let level = 'ok';
  let label = 'Fresh';
  let tip = [];

  if (dataAge === null) {
    level = 'degraded';
    label = 'Unknown age';
  } else {
    tip.push(`Dataset ${dataAge < 1 ? 'under an hour' : Math.round(dataAge) + 'h'} old`);
    if (dataAge >= DEGRADED_H) { level = 'broken'; label = 'Stale'; }
    else if (dataAge >= FRESH_H) { level = 'degraded'; label = 'Ageing'; }
  }

  if (priceAge !== null) {
    tip.push(`ADI price ${priceAge < 1 ? 'under an hour' : Math.round(priceAge) + 'h'} old`);
    if (priceAge >= DEGRADED_H && level === 'ok') { level = 'degraded'; label = 'Stale price'; }
  } else if (price) {
    tip.push('ADI price has no timestamp');
  }

  return <DataQualityBadge level={level} label={label} tooltip={tip.join('. ')} />;
}

function Topbar({ active, data }) {
  const label = (ADI_NAV.find((n) => n.id === active) || {}).label || '';
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-brand">
          <span className="topbar-brand-name">
            adi<span style={{ color: 'var(--orange)' }}>users</span>
          </span>
        </div>
        <span className="topbar-terminal">
          <span className="prompt">❯</span>
          <span>{label}</span>
        </span>
      </div>
      <div className="topbar-right">
        {data && <FreshnessBadge data={data} />}
        {data && (
          <DataSourceBadge
            source="Onchain"
            lastUpdated={data.generated_at ? new Date(data.generated_at) : null}
          />
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}

function Statusbar({ data }) {
  if (!data) return <footer className="statusbar"><span>ADI active users</span></footer>;
  return (
    <footer className="statusbar">
      <span>Chain {data.meta.adi_chain_id}</span>
      <span>·</span>
      <span>MAU window {data.meta.rolling_window_days}d rolling</span>
      <span>·</span>
      <span>ADI RPC and Ethereum mainnet</span>
      {data.partial_day && (
        <React.Fragment>
          <span>·</span>
          <span>{data.partial_day} still in progress</span>
        </React.Fragment>
      )}
    </footer>
  );
}

/* Page wrapper: shell regions, loading and error states. `render` receives the
 * dataset once it has arrived. */
function Page({ active, title, subtitle, render }) {
  const { data, error } = useDataset();
  // Region order matters: the .shell grid places the topbar as a full-width
  // first row, so it must come before the sidebar in the DOM. Put the sidebar
  // first and `main` gets auto-placed into the sidebar's column, collapsing
  // every panel to a few dozen pixels. LINT.md section 5 has the correct order.
  return (
    <React.Fragment>
      <Topbar active={active} data={data} />
      <Sidebar active={active} />
      <main className="main">
        <section style={{ padding: 24 }}>
          <div className="page-header">
            <h1 className="page-title">{title}</h1>
            {subtitle && <p className="page-subtitle">{subtitle}</p>}
          </div>
          {error && (
            <div className="panel">
              <div className="panel-body">
                <b>Could not load data.json.</b> {error}. Run{' '}
                <code>python3 scripts/refresh_all.py</code> to build it.
              </div>
            </div>
          )}
          {!error && !data && (
            <React.Fragment>
              <div className="grid grid-4" style={{ marginBottom: 16 }}>
                {[0, 1, 2, 3].map((i) => (
                  <PanelSkeleton key={i} label="Loading" height={92} />
                ))}
              </div>
              <PanelSkeleton label="Loading dataset" description="Reading onchain index" height={300} />
            </React.Fragment>
          )}
          {data && render(data)}
        </section>
      </main>
      <Statusbar data={data} />
    </React.Fragment>
  );
}

/* ── small presentational helpers ─────────────────────────────────────── */

function Metric({ label, value, footer }) {
  return (
    <div className="panel" style={{ padding: '18px 20px' }}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {footer && <div className="metric-footer">{footer}</div>}
    </div>
  );
}

function PanelHead({ title, subtitle, badge }) {
  return (
    <div className="panel-header">
      <span className="panel-title">
        <span className="bullet">●</span> {title}
        {subtitle && <span style={{ color: 'var(--fg-dim)' }}> · {subtitle}</span>}
      </span>
      {badge && <span className="panel-badge">{badge}</span>}
    </div>
  );
}

/* Persistent key for a chart's series.
 * The SDK's AreaChart and StackedBarChart name their series only inside the
 * hover tooltip, so a multi-line chart is unreadable until you mouse over it.
 * Render the key here rather than forking charts.jsx, which is shared across
 * every Datum dashboard. Uses the SDK's own .legend classes. */
function ChartLegend({ items }) {
  if (!items || items.length < 1) return null;
  return (
    <div className="legend" style={{ marginTop: 10 }}>
      {items.map((s) => (
        <span className="legend-item" key={s.name} style={{ cursor: 'default' }}>
          <span className="legend-swatch" style={{ background: s.color }} />
          {s.name}
        </span>
      ))}
    </div>
  );
}

/* A chart in a panel, with its own width measurement, a mandatory caption and
 * an optional series key. Pass `legend` for anything with more than one series. */
function ChartPanel({ title, subtitle, badge, caption, height, legend, children }) {
  const [ref, w] = useElementWidth(900);
  return (
    <div className="panel">
      <PanelHead title={title} subtitle={subtitle} badge={badge} />
      <div className="panel-caption">{caption}</div>
      <div className="panel-body">
        <div ref={ref} style={{ width: '100%' }}>
          {children(w, height || chartHeight(w))}
        </div>
        <ChartLegend items={legend} />
      </div>
    </div>
  );
}

function TablePanel({ title, subtitle, badge, caption, children }) {
  return (
    <div className="panel">
      <PanelHead title={title} subtitle={subtitle} badge={badge} />
      <div className="panel-caption">{caption}</div>
      <div className="panel-body flush">{children}</div>
    </div>
  );
}

/* Series arrays for the SDK charts, sliced to a window and reversed-safe. */
function pick(series, key) {
  return series.map((r) => Number(r[key]) || 0);
}
function labelsOf(series) {
  return series.map((r) => fmtDate(r.date));
}

Object.assign(window, {
  ADI_NAV, fmtCount, fmtUSDExact, fmtADI, fmtDate, shortAddr,
  useDataset, useElementWidth, chartHeight,
  Page, Sidebar, Topbar, Statusbar, ThemeToggle, FreshnessBadge, hoursSince,
  Metric, PanelHead, ChartPanel, ChartLegend, TablePanel, pick, labelsOf,
});
