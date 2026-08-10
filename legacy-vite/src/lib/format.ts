export const fmtNum = (n: number | null | undefined, dp = 0): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return '–';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
};

export const fmtCompact = (n: number | null | undefined): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return '–';
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
};

export const fmtPct = (n: number | null | undefined, dp = 1): string =>
  n === null || n === undefined || Number.isNaN(n) ? '–' : `${n.toFixed(dp)}%`;

export const shortAddr = (a: string): string =>
  a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;

export const fmtDate = (iso: string): string => {
  const [, m, d] = iso.split('-');
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d} ${months[Number(m) - 1]}`;
};
