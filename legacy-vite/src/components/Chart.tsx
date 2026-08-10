import { useMemo, useState } from 'react';
import { fmtCompact, fmtDate, fmtNum } from '../lib/format';

export interface Series {
  key: string;
  label: string;
  color: string;
  /** Draw as filled columns instead of a line. Bars render behind lines. */
  bars?: boolean;
  /** Plot against the right-hand axis. */
  right?: boolean;
}

interface Props {
  data: Record<string, any>[];
  xKey: string;
  series: Series[];
  height?: number;
  /** Force the left axis to start at 0 (default true). */
  zeroBased?: boolean;
}

const W = 900;
// top leaves room for the highest tick label to sit fully inside the viewBox
const PAD = { top: 20, right: 56, bottom: 26, left: 56 };

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
  return out;
}

export function Chart({ data, xKey, series, height = 260, zeroBased = true }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const H = height;

  const { leftMax, rightMax, hasRight } = useMemo(() => {
    let l = 0;
    let r = 0;
    let anyRight = false;
    for (const row of data) {
      for (const s of series) {
        const v = Number(row[s.key]) || 0;
        if (s.right) {
          anyRight = true;
          if (v > r) r = v;
        } else if (v > l) l = v;
      }
    }
    return { leftMax: l, rightMax: r, hasRight: anyRight };
  }, [data, series]);

  if (!data.length) return <div className="loading">No data</div>;

  const lTicks = niceTicks(leftMax);
  const rTicks = niceTicks(rightMax);
  const lTop = Math.max(lTicks[lTicks.length - 1], 1);
  const rTop = Math.max(rTicks[rTicks.length - 1], 1);

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i: number) =>
    PAD.left + (data.length === 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const y = (v: number, right = false) =>
    PAD.top + plotH - (Math.max(0, v) / (right ? rTop : lTop)) * plotH;

  const barW = Math.max(1, (plotW / data.length) * 0.62);

  // X labels: about six evenly spaced ticks, always including the last point.
  // Drop the second-to-last tick when it would collide with the final label.
  const step = Math.max(1, Math.floor(data.length / 6));
  const idx = [];
  for (let i = 0; i < data.length; i += step) idx.push(i);
  const lastIdx = data.length - 1;
  const MIN_GAP = 52; // px in viewBox units, roughly one "25 Nov" label
  while (idx.length && x(lastIdx) - x(idx[idx.length - 1]) < MIN_GAP) idx.pop();
  idx.push(lastIdx);
  const xLabels = idx.map((i) => ({ i, label: String(data[i][xKey]) }));

  const hoverRow = hover !== null ? data[hover] : null;

  return (
    <div
      className="chart-wrap"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const px = ((e.clientX - rect.left) / rect.width) * W;
        const i = Math.round(((px - PAD.left) / plotW) * (data.length - 1));
        setHover(Math.max(0, Math.min(data.length - 1, i)));
      }}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img">
        {/* horizontal gridlines + left axis */}
        {lTicks.map((t) => (
          <g key={`l${t}`}>
            <line
              x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)}
              stroke="var(--tint-medium)" strokeWidth={1}
            />
            <text
              x={PAD.left - 7} y={y(t) + 3.5} textAnchor="end"
              fontSize={10} fill="var(--text-dim)" fontFamily="var(--font-mono)"
            >
              {fmtCompact(t)}
            </text>
          </g>
        ))}

        {/* right axis */}
        {hasRight && rTicks.map((t) => (
          <text
            key={`r${t}`}
            x={W - PAD.right + 7} y={y(t, true) + 3.5} textAnchor="start"
            fontSize={10} fill="var(--text-dim)" fontFamily="var(--font-mono)"
          >
            {fmtCompact(t)}
          </text>
        ))}

        {/* bars behind lines */}
        {series.filter((s) => s.bars).map((s) => (
          <g key={s.key}>
            {data.map((row, i) => {
              const v = Number(row[s.key]) || 0;
              const yy = y(v, s.right);
              return (
                <rect
                  key={i}
                  x={x(i) - barW / 2}
                  y={yy}
                  width={barW}
                  height={Math.max(0, PAD.top + plotH - yy)}
                  fill={s.color}
                  opacity={hover === i ? 0.95 : 0.5}
                />
              );
            })}
          </g>
        ))}

        {/* lines */}
        {series.filter((s) => !s.bars).map((s) => {
          const d = data
            .map((row, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(2)},${y(Number(row[s.key]) || 0, s.right).toFixed(2)}`)
            .join(' ');
          return (
            <path
              key={s.key} d={d} fill="none" stroke={s.color}
              strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          );
        })}

        {/* hover crosshair + markers */}
        {hover !== null && (
          <>
            <line
              x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH}
              stroke="var(--tint-strong)" strokeWidth={1}
            />
            {series.filter((s) => !s.bars).map((s) => (
              <circle
                key={s.key}
                cx={x(hover)}
                cy={y(Number(data[hover][s.key]) || 0, s.right)}
                r={3} fill="var(--background)" stroke={s.color} strokeWidth={1.7}
              />
            ))}
          </>
        )}

        {/* x labels */}
        {xLabels.map(({ i, label }) => (
          <text
            key={i} x={x(i)} y={H - 8} textAnchor="middle"
            fontSize={10} fill="var(--text-dim)" fontFamily="var(--font-mono)"
          >
            {label.length === 10 ? fmtDate(label) : label}
          </text>
        ))}

        {/* baseline */}
        <line
          x1={PAD.left} x2={W - PAD.right} y1={PAD.top + plotH} y2={PAD.top + plotH}
          stroke="var(--border-bright)" strokeWidth={1}
        />
      </svg>

      {hoverRow && (
        <div
          className="tooltip"
          style={{
            left: `${(x(hover!) / W) * 100}%`,
            top: `${(PAD.top / H) * 100}%`,
          }}
        >
          <div style={{ marginBottom: 3 }}><b>{String(hoverRow[xKey])}</b></div>
          {series.map((s) => (
            <div key={s.key}>
              <span style={{ color: s.color }}>{s.label}</span>
              <span>{fmtNum(Number(hoverRow[s.key]) || 0)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="legend">
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color, height: s.bars ? 8 : 2 }} />
            {s.label}
            {s.right ? ' (right)' : ''}
          </span>
        ))}
      </div>
    </div>
  );
}
