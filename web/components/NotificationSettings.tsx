"use client";

import { useCallback, useState, useTransition } from "react";

import { sendTestNotificationAction, type ActionResult } from "@/app/actions";
import type { NotifyStatus } from "@/lib/types";

import { Toast } from "./Toast";

/**
 * A batch that quietly fills the queue at 02:00 UTC is worth nothing if nobody
 * opens the dashboard, so this panel exists to make a silent channel loud.
 *
 * Credentials live in the environment, not the database — a dashboard that
 * could rewrite them would be a way to redirect the digest — so this is
 * read-only plus a test send. What it does add is the thing you cannot get
 * from a README: which half of a two-part credential is missing.
 */
export function NotificationSettings({ status }: { status: NotifyStatus | null }) {
  const [toast, setToast] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  const test = useCallback(() => {
    startTransition(async () => setToast(await sendTestNotificationAction()));
  }, []);

  if (!status) {
    return (
      <section className="rounded-xl border border-edge bg-panel/40 p-4">
        <h2 className="text-sm font-medium text-fg">Notifications</h2>
        <p className="mt-1 text-sm text-muted">
          The API did not answer, so channel status is unknown.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-edge bg-panel/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-fg">Notifications</h2>
          <p className="mt-0.5 max-w-prose text-sm text-muted">
            {status.any ? (
              <>
                After every run a digest goes to{" "}
                <span className="text-fg">{status.configured.join(", ")}</span> — what was
                built, the top matches, and a link back here.
              </>
            ) : (
              <>
                Nothing is configured, so every run is silent and you have to remember to
                look. Set up one channel below.
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={test}
          disabled={pending || !status.any}
          className="shrink-0 rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-sm
                     text-accent transition-colors duration-150 hover:bg-accent/20
                     disabled:cursor-not-allowed disabled:opacity-40"
        >
          {pending ? "Sending…" : "Send test"}
        </button>
      </div>

      <ul className="mt-4 space-y-2">
        {status.channels.map((channel) => (
          <li
            key={channel.id}
            className={`rounded-lg border px-3 py-2.5 ${
              channel.active ? "border-fast/30 bg-fast/[0.04]" : "border-edge bg-ink/30"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  channel.active ? "bg-fast" : "bg-faint"
                }`}
              />
              <span className="text-sm text-fg">{channel.label}</span>
              <span className="ml-auto font-mono text-2xs text-faint">
                {channel.active ? "active" : `set ${channel.missing.join(" + ")}`}
              </span>
            </div>
            {!channel.active && (
              <p className="mt-1.5 pl-3.5 text-2xs leading-relaxed text-faint">{channel.how}</p>
            )}
          </li>
        ))}
      </ul>

      <p className="mt-3 text-2xs leading-relaxed text-faint">
        These are set where the code runs — repository secrets for the scheduled runs, and
        the host&rsquo;s environment for this dashboard&rsquo;s API.{" "}
        {!status.notify_on_empty && "A run that finds nothing stays quiet. "}
        See <code className="font-mono text-faint">docs/DEPLOY.md</code>.
      </p>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </section>
  );
}
