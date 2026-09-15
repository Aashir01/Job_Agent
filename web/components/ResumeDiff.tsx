import type { ResumeDiff } from "@/lib/types";

/**
 * §6: "Stores a diff so the user sees exactly what changed."
 *
 * A rejected rewrite is shown too. When the Tailor's traceability check throws
 * a rewrite away, that is worth seeing — it is the model trying to drift, and
 * the user should know it happened rather than only see the clean result.
 */
export function ResumeDiffView({ diff }: { diff: ResumeDiff | null }) {
  if (!diff || !diff.entries?.length) {
    return (
      <p className="rounded-lg border border-dashed border-edge px-4 py-6 text-center text-sm text-faint">
        No resume was built — the bullet bank had nothing to match this posting.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
        <Stat value={diff.bullet_count} label="bullets" />
        <Stat value={diff.changed_count} label="reworded" />
        <Stat value={diff.verbatim_count} label="verbatim" />
        {diff.rejected_rewrites ? (
          <Stat
            value={diff.rejected_rewrites}
            label={diff.rejected_rewrites === 1 ? "rewrite rejected" : "rewrites rejected"}
            tone="bad"
          />
        ) : null}
      </div>

      <ul className="space-y-2">
        {diff.entries.map((entry) => (
          <li
            key={entry.bullet_id}
            className="rounded-lg border border-edge bg-ink/40 p-3.5 text-sm leading-relaxed"
          >
            <div className="mb-2 flex items-center gap-2.5 text-2xs">
              <span className="truncate text-muted">{entry.role_context ?? "Experience"}</span>
              {entry.similarity != null && (
                <span className="font-mono text-faint">sim {entry.similarity.toFixed(2)}</span>
              )}
              <span
                className={`ml-auto shrink-0 rounded-full border px-2 py-px ${
                  entry.changed ? "border-accent/40 text-accent" : "border-edge text-faint"
                }`}
              >
                {entry.changed ? "reworded" : "verbatim"}
              </span>
            </div>

            <p className="text-fg/90">
              {entry.ops.map((op, index) => (
                <span
                  key={index}
                  className={
                    op.op === "insert" ? "diff-ins" : op.op === "delete" ? "diff-del" : undefined
                  }
                >
                  {op.text}
                </span>
              ))}
            </p>

            {entry.rejected_rewrite && (
              <div className="mt-2.5 rounded-lg border border-marginal/30 bg-marginal/5 p-3">
                <p className="text-2xs text-marginal">
                  <span aria-hidden className="mr-1.5">
                    ✕
                  </span>
                  Rewrite discarded — {entry.reject_reason}
                </p>
                <p className="mt-1.5 text-xs italic leading-relaxed text-muted">
                  “{entry.rejected_rewrite}”
                </p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stat({
  value,
  label,
  tone,
}: {
  value: number;
  label: string;
  tone?: "bad";
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span
        className={`font-mono text-base font-semibold tabular-nums ${
          tone === "bad" ? "text-marginal" : "text-fg"
        }`}
      >
        {value}
      </span>
      <span className="text-2xs uppercase tracking-wider text-faint">{label}</span>
    </span>
  );
}
