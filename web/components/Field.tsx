import type { ReactNode } from "react";

export const inputClass =
  "w-full rounded-lg border border-edge bg-ink/60 px-3 py-2 text-sm text-fg " +
  "placeholder:text-faint transition-colors duration-150 focus:border-accent/50 focus:outline-none";

export const monoInputClass = `${inputClass} font-mono text-xs leading-relaxed`;

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-2xs uppercase tracking-[0.12em] text-faint">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-2xs leading-relaxed text-faint">{hint}</span>}
    </label>
  );
}

/** "a, b , c" → ["a","b","c"], dropping blanks. */
export function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function joinList(value: string[] | null | undefined): string {
  return (value ?? []).join(", ");
}
