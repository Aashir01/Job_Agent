import { NextResponse } from "next/server";

import { getBatches } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Polling endpoint for the run controls and the header status dot. The agent
 * key stays server-side; the browser only ever sees the latest batch row.
 */
export async function GET() {
  try {
    const { batches } = await getBatches(1);
    return NextResponse.json({ batch: batches[0] ?? null });
  } catch (error) {
    return NextResponse.json(
      { batch: null, error: error instanceof Error ? error.message : "unknown error" },
      { status: 502 },
    );
  }
}
