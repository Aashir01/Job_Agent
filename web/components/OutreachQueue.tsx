"use client";

import { useState } from "react";

import { approveOutreachAction, type ActionResult } from "@/app/actions";
import { dateTime } from "@/lib/format";
import type { DueOutreach } from "@/lib/types";

import { Toast } from "./Toast";

const KIND_LABEL: Record<string, string> = {
  pre_apply: "Pre-apply",
  follow_up_1: "Follow-up 1",
  follow_up_2: "Follow-up 2",
  thank_you: "Thank you",
};

const CONFIDENCE_TONE: Record<string, string> = {
  verified: "border-fast/40 text-fast",
  pattern_guess: "border-standard/40 text-standard",
  unknown: "border-edge text-faint",
};

/**
 * §6: the cadence is pre-approved, the content is not. Each row is one email
 * the Chaser drafted; nothing sends until its body gets a click here.
 */
export function OutreachQueue({ initial }: { initial: DueOutreach[] }) {
  const [items, setItems] = useState(initial);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<ActionResult | null>(null);

  const decide = (item: DueOutreach, sendNow: boolean) => {
    setBusy(item.id);
    const edited = drafts[item.id];
    const changed = edited !== undefined && edited !== (item.body ?? "");
    void approveOutreachAction(item.id, changed ? edited : null, sendNow).then((result) => {
      setBusy(null);
      setToast(result);
      if (result.ok) setItems((rows) => rows.filter((row) => row.id !== item.id));
    });
  };

  if (!items.length) {
    return (
      <div className="animate-fade-in rounded-2xl border border-dashed border-edge bg-panel/40 px-6 py-16 text-center">
        <p className="text-base font-medium text-fg">Nothing due.</p>
        <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted">
          The chaser queues day-3 and day-10 follow-ups after each batch. When one is
          waiting, it lands here for your approval before anything is sent.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const contact = item.contacts;
        const confidence = contact?.email_confidence ?? "unknown";
        return (
          <article
            key={item.id}
            className="rounded-xl border border-edge bg-panel/60 shadow-panel"
          >
            <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-edge/60 px-4 py-2.5">
              <span className="rounded-full border border-edge px-2 py-0.5 text-2xs text-muted">
                {KIND_LABEL[item.kind] ?? item.kind}
              </span>
              <span className="text-sm text-fg">{contact?.name ?? "Unknown contact"}</span>
              {contact?.email && (
                <span
                  className={`rounded-full border px-2 py-0.5 font-mono text-2xs ${CONFIDENCE_TONE[confidence] ?? CONFIDENCE_TONE.unknown}`}
                  title={`Address confidence: ${confidence.replace(/_/g, " ")}`}
                >
                  {contact.email}
                </span>
              )}
              <span className="ml-auto text-2xs text-faint">
                due {dateTime(item.due_at)}
              </span>
            </header>

            <div className="px-4 py-3">
              <label htmlFor={`body-${item.id}`} className="sr-only">
                Email body
              </label>
              <textarea
                id={`body-${item.id}`}
                rows={Math.min(14, Math.max(5, (item.body ?? "").split("\n").length + 1))}
                value={drafts[item.id] ?? item.body ?? ""}
                onChange={(event) =>
                  setDrafts((map) => ({ ...map, [item.id]: event.target.value }))
                }
                className="w-full resize-y rounded-lg border border-edge bg-ink/60 px-3 py-2
                           font-mono text-xs leading-relaxed text-fg/90
                           focus:border-accent/50 focus:outline-none"
              />
            </div>

            <footer className="flex items-center gap-2 border-t border-edge/60 px-4 py-2.5">
              <button
                type="button"
                onClick={() => decide(item, true)}
                disabled={busy !== null}
                className="rounded-lg border border-fast/40 bg-fast/15 px-3 py-1.5 text-xs
                           font-medium text-fast transition-colors duration-150 hover:bg-fast/25
                           disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === item.id ? "Sending…" : "Approve and send"}
              </button>
              <button
                type="button"
                onClick={() => decide(item, false)}
                disabled={busy !== null}
                className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-xs text-muted
                           transition-colors duration-150 hover:border-edge-strong hover:text-fg
                           disabled:cursor-not-allowed disabled:opacity-50"
              >
                Approve, hold
              </button>
              {drafts[item.id] !== undefined && drafts[item.id] !== (item.body ?? "") && (
                <span className="ml-auto text-2xs text-standard">edited</span>
              )}
            </footer>
          </article>
        );
      })}

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
