import "server-only";

import type { ApplicationRow, QueueResponse, ReviewPackage, Tier } from "./types";

const BASE = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const KEY = process.env.AGENT_KEY ?? "";

/**
 * Every call runs on the server. The agent key is a server-only secret — it is
 * never inlined into a client bundle, so the browser can only reach the API
 * through the server actions in app/actions.ts.
 */
async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!KEY) {
    throw new Error("AGENT_KEY is not set; the dashboard cannot reach the API");
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "X-Agent-Key": KEY,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.text();
    let detail = body.slice(0, 300);
    try {
      detail = (JSON.parse(body) as { detail?: string }).detail ?? detail;
    } catch {
      /* the API returned something that is not JSON; the raw text is the message */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function getQueue(tier?: Tier, status = "queued"): Promise<QueueResponse> {
  const params = new URLSearchParams({ status, limit: "100" });
  if (tier) params.set("tier", tier);
  return call<QueueResponse>(`/packages?${params}`);
}

export function getPackage(id: string): Promise<ReviewPackage> {
  return call<ReviewPackage>(`/packages/${id}`);
}

export function approvePackage(
  id: string,
  opts: { submit?: boolean; sendPreApply?: boolean; editedFields?: string[] } = {},
) {
  return call<{ ok: boolean; status: string; method?: string; detail?: string }>(
    `/packages/${id}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        submit: opts.submit ?? true,
        send_pre_apply: opts.sendPreApply ?? false,
        edited_fields: opts.editedFields ?? [],
      }),
    },
  );
}

export function rejectPackage(id: string, reasonCode: string, reason = "") {
  return call<{ ok: boolean; status: string }>(`/packages/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason, reason_code: reasonCode }),
  });
}

export function editPackage(id: string, patch: Record<string, unknown>) {
  return call<{ ok: boolean; edited_fields: string[] }>(`/packages/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** §7: batch approve the entire fast lane with one action. */
export function approveFastLane(limit = 20) {
  return call<{ approved: number; results: { package_id: string; ok: boolean; detail?: string }[] }>(
    `/packages/fast-lane/approve-all?submit=true&limit=${limit}`,
    { method: "POST" },
  );
}

export function getApplications(): Promise<{
  applications: ApplicationRow[];
  funnel: Record<string, number>;
}> {
  return call(`/applications?limit=200`);
}

export function getQuota(): Promise<{
  day: string;
  caps: Record<string, number>;
  counters: Record<string, number>;
  llm_calls_today: number;
  llm_cost_usd_today: number;
  llm_failures_today: number;
}> {
  return call(`/health/quota`);
}
