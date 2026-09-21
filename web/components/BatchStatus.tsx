import type { BatchStatus } from "@/lib/types";

const STATUS_TONE: Record<BatchStatus, { text: string; dot: string; pulse?: boolean }> = {
  running: { text: "text-accent", dot: "bg-accent", pulse: true },
  ok: { text: "text-fast", dot: "bg-fast" },
  partial: { text: "text-standard", dot: "bg-standard" },
  failed: { text: "text-marginal", dot: "bg-marginal" },
};

export function StatusBadge({ status }: { status: BatchStatus }) {
  const tone = STATUS_TONE[status] ?? STATUS_TONE.partial;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${tone.text}`}>
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${tone.dot} ${tone.pulse ? "animate-pulse-dot" : ""}`}
      />
      {status}
    </span>
  );
}
