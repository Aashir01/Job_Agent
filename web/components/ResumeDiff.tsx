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
      <p className="text-sm text-muted">
        No resume was built — the bullet bank had nothing to match this posting.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        {diff.bullet_count} bullets · {diff.changed_count} reworded ·{" "}
        {diff.verbatim_count} verbatim
        {diff.rejected_rewrites ? (
          <span className="text-marginal">
            {" "}
            · {diff.rejected_rewrites} rewrite
            {diff.rejected_rewrites === 1 ? "" : "s"} rejected as untraceable
          </span>
        ) : null}
      </p>

      <ul className="space-y-2">
        {diff.entries.map((entry) => (
          <li
            key={entry.bullet_id}
            className="rounded-lg border border-edge bg-panel/60 p-3 text-sm leading-relaxed"
          >
            <div className="mb-1 flex items-center gap-2 text-[11px] text-muted">
              <span>{entry.role_context ?? "Experience"}</span>
              {entry.similarity != null && (
                <span className="font-mono">sim {entry.similarity.toFixed(2)}</span>
              )}
              {!entry.changed && <span className="text-muted">unchanged</span>}
            </div>

            <p>
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
              <p className="mt-2 rounded border border-marginal/30 bg-marginal/5 p-2 text-xs text-marginal">
                Rewrite discarded — {entry.reject_reason}
                <span className="mt-1 block italic text-muted">“{entry.rejected_rewrite}”</span>
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
