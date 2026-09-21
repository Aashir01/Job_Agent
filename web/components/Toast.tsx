"use client";

import { useEffect } from "react";

import type { ActionResult } from "@/app/actions";

/**
 * One toast style for the whole console. Fixed bottom-right, announces itself
 * to screen readers, and dismisses itself — the operator should never have to
 * close a confirmation.
 */
export function Toast({
  toast,
  onDismiss,
}: {
  toast: ActionResult | null;
  onDismiss: () => void;
}) {
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(onDismiss, 6000);
    return () => clearTimeout(timer);
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div
      role="status"
      className={`animate-fade-up fixed bottom-5 right-5 z-50 flex max-w-sm items-start gap-2
                  rounded-xl border px-4 py-3 text-sm shadow-pop backdrop-blur-xl ${
                    toast.ok
                      ? "border-fast/40 bg-fast/10 text-fast"
                      : "border-marginal/40 bg-marginal/10 text-marginal"
                  }`}
    >
      <span aria-hidden className="mt-px shrink-0">
        {toast.ok ? "✓" : "!"}
      </span>
      <span className="text-fg/90">{toast.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="ml-1 shrink-0 rounded px-1 text-faint transition-colors duration-150 hover:text-fg"
      >
        ×
      </button>
    </div>
  );
}
