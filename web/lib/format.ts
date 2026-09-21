/** Display helpers shared by the dashboard pages. No locale surprises: the
 *  operator reads UTC dates everywhere. */

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return iso.slice(0, 10);
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

export function usd(value: number | null | undefined): string {
  const amount = value ?? 0;
  return amount >= 0.01 ? `$${amount.toFixed(2)}` : `$${amount.toFixed(4)}`;
}

export function elapsed(isoStart: string, isoEnd: string | null): string {
  const start = new Date(isoStart).getTime();
  const end = isoEnd ? new Date(isoEnd).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
