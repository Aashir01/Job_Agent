"use client";

import { useState, useTransition } from "react";

import { resendDigestAction, type ActionResult } from "@/app/actions";

import { Toast } from "./Toast";

/**
 * Re-push a past batch's digest.
 *
 * The case this exists for: you set up Telegram after a run had already
 * finished, so the one batch you most want to see is the one that was never
 * announced. Re-reads the queue at send time, so it reflects what is still
 * waiting rather than what was built.
 */
export function ResendDigest({
  batchId,
  delivered,
}: {
  batchId: string;
  /** Channel → success, as recorded when the batch finished. */
  delivered?: Record<string, boolean>;
}) {
  const [toast, setToast] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  const sentTo = Object.entries(delivered ?? {})
    .filter(([, ok]) => ok)
    .map(([channel]) => channel);

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() =>
          startTransition(async () => setToast(await resendDigestAction(batchId)))
        }
        disabled={pending}
        className="rounded-lg border border-edge px-3 py-1.5 text-sm text-muted
                   transition-colors duration-150 hover:border-edge-strong hover:text-fg
                   disabled:cursor-not-allowed disabled:opacity-40"
      >
        {pending ? "Sending…" : "Re-send digest"}
      </button>
      <p className="text-2xs text-faint">
        {sentTo.length ? `sent to ${sentTo.join(", ")}` : "no digest was sent"}
      </p>
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
