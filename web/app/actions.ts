"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  approveFastLane,
  approveOutreach,
  approvePackage,
  editPackage,
  refreshRegisters,
  rejectPackage,
  runBatch,
  runChaser,
} from "@/lib/api";

export interface ActionResult {
  ok: boolean;
  message: string;
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return `Daily cap reached — ${error.message}`;
    if (error.status === 409) return `Already decided — ${error.message}`;
    return error.message;
  }
  return error instanceof Error ? error.message : "unknown error";
}

export async function approveAction(id: string, sendPreApply = false): Promise<ActionResult> {
  try {
    const res = await approvePackage(id, { submit: true, sendPreApply });
    revalidatePath("/");
    return {
      ok: res.ok,
      message: res.ok
        ? `Approved — ${res.detail ?? res.method ?? "submitted"}`
        : `Approved, but submission failed: ${res.detail ?? "unknown"}`,
    };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function rejectAction(
  id: string,
  reasonCode: string,
  reason = "",
): Promise<ActionResult> {
  try {
    await rejectPackage(id, reasonCode, reason);
    revalidatePath("/");
    return { ok: true, message: `Rejected — ${reasonCode}` };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function editAction(
  id: string,
  patch: Record<string, unknown>,
): Promise<ActionResult> {
  try {
    const res = await editPackage(id, patch);
    revalidatePath("/");
    return { ok: true, message: `Saved ${res.edited_fields.join(", ")}` };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

/** §7: one action for the whole fast lane, bounded by the §10 daily cap. */
export async function approveFastLaneAction(limit = 20): Promise<ActionResult> {
  try {
    const res = await approveFastLane(limit);
    revalidatePath("/");
    const failed = res.results.filter((r) => !r.ok);
    if (failed.length) {
      return {
        ok: false,
        message: `Approved ${res.approved}, ${failed.length} failed to submit — ${failed[0]?.detail ?? ""}`,
      };
    }
    return { ok: true, message: `Approved and submitted ${res.approved} fast-lane packages` };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

/**
 * Starts the pipeline in the background on the API. The client polls
 * /api/batch/latest for progress — this action returns as soon as the run
 * is accepted, never when it finishes.
 */
export async function runBatchAction(skipScout = false): Promise<ActionResult> {
  try {
    await runBatch({ kind: "manual", skipScout });
    revalidatePath("/batches");
    return {
      ok: true,
      message: skipScout
        ? "Batch started — processing stored jobs, discovery skipped"
        : "Batch started — scouting, then building packages",
    };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function runChaserAction(): Promise<ActionResult> {
  try {
    const res = await runChaser();
    revalidatePath("/outreach");
    return {
      ok: true,
      message: `Chaser done — ${res.follow_ups_now_due} follow-ups due, ${res.marked_ghosted} marked ghosted`,
    };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function refreshRegistersAction(): Promise<ActionResult> {
  try {
    await refreshRegisters();
    return { ok: true, message: "Sponsorship registers refreshed" };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

/** §6: per-send content approval. `sendNow=false` approves but holds the send. */
export async function approveOutreachAction(
  id: string,
  editedBody: string | null,
  sendNow: boolean,
): Promise<ActionResult> {
  try {
    const res = await approveOutreach(id, { body: editedBody ?? undefined, sendNow });
    revalidatePath("/outreach");
    if (!sendNow) return { ok: true, message: "Approved — held, not sent" };
    return res.sent > 0
      ? { ok: true, message: "Approved and sent" }
      : { ok: false, message: "Approved, but the send failed — check the API logs" };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}
