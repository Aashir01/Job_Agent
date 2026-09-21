import { NextResponse } from "next/server";

import { getStatsOverview } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Nav badge counts. Polled client-side so the root layout stays static. */
export async function GET() {
  try {
    const stats = await getStatsOverview();
    return NextResponse.json({ outreach: stats.outreach_due });
  } catch {
    return NextResponse.json({ outreach: 0 }, { status: 502 });
  }
}
