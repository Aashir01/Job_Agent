"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  addBoard,
  approveFastLane,
  approveOutreach,
  approvePackage,
  deleteBoard,
  editPackage,
  refreshRegisters,
  rejectPackage,
  resendBatchDigest,
  runBatch,
  runChaser,
  runConfiguredBatch,
  sendNotifyTest,
  setBoardEnabled,
  updateProfile,
  updateRunSettings,
} from "@/lib/api";

import type { ProfilePatch, RunFilters } from "@/lib/types";

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

/* ── Setup: the profile, the platforms, and the run ─────────────────────── */

export async function saveProfileAction(patch: ProfilePatch): Promise<ActionResult> {
  try {
    await updateProfile(patch);
    revalidatePath("/setup");
    return { ok: true, message: "Profile saved — the next batch will use it" };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function toggleBoardAction(id: string, enabled: boolean): Promise<ActionResult> {
  try {
    await setBoardEnabled(id, enabled);
    revalidatePath("/setup");
    return { ok: true, message: enabled ? "Board enabled" : "Board disabled" };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function addBoardAction(input: {
  kind: string;
  slug: string;
  company_name?: string;
}): Promise<ActionResult> {
  try {
    const { board } = await addBoard(input);
    revalidatePath("/setup");
    return { ok: true, message: `Added ${board.kind}/${board.slug}` };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function deleteBoardAction(id: string, label: string): Promise<ActionResult> {
  try {
    await deleteBoard(id);
    revalidatePath("/setup");
    return { ok: true, message: `Removed ${label}` };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function saveRunSettingsAction(input: {
  platforms: string[];
  filters: RunFilters;
}): Promise<ActionResult> {
  try {
    await updateRunSettings(input);
    revalidatePath("/setup");
    return { ok: true, message: "Saved. The scheduled batches will use this too." };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

/**
 * Save the console's choices and fire a batch with them. Both happen in one
 * call so the run can never use a stale configuration.
 */
export async function saveAndRunAction(input: {
  platforms: string[];
  filters: RunFilters;
  skipScout: boolean;
}): Promise<ActionResult> {
  try {
    await runConfiguredBatch(input);
    revalidatePath("/setup");
    revalidatePath("/batches");
    const scope = input.platforms.length ? `${input.platforms.length} platforms` : "all platforms";
    return {
      ok: true,
      message: input.skipScout
        ? `Batch started over stored jobs — ${scope}`
        : `Batch started — scouting ${scope}`,
    };
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


/* ── Notifications ─────────────────────────────────────────────────────── */

export async function sendTestNotificationAction(): Promise<ActionResult> {
  try {
    const res = await sendNotifyTest();
    if (!res.sent) {
      const failed = res.results.filter((r) => !r.ok);
      return {
        ok: false,
        message: failed.length
          ? `Failed: ${failed.map((r) => `${r.channel} — ${r.detail}`).join("; ")}`
          : (res.reason ?? "No channel is configured."),
      };
    }
    const ok = res.results.filter((r) => r.ok).map((r) => r.channel);
    const failed = res.results.filter((r) => !r.ok);
    return {
      ok: failed.length === 0,
      message: failed.length
        ? `Sent to ${ok.join(", ")}; ${failed.map((r) => `${r.channel} failed (${r.detail})`).join("; ")}`
        : `Test digest sent to ${ok.join(", ")}. Check your phone.`,
    };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}

export async function resendDigestAction(batchId: string): Promise<ActionResult> {
  try {
    const res = await resendBatchDigest(batchId);
    const ok = res.results.filter((r) => r.ok).map((r) => r.channel);
    return res.sent
      ? { ok: true, message: `Digest re-sent to ${ok.join(", ")}.` }
      : { ok: false, message: res.reason ?? "Nothing was sent — no channel is configured." };
  } catch (error) {
    return { ok: false, message: describe(error) };
  }
}
