import { NextResponse } from "next/server";

/**
 * Proxies the tailored resume out of the API.
 *
 * The private storage bucket needs the service key to read, and that key is
 * server-only, so the browser asks this route and this route asks the API.
 * A plain link to Supabase Storage would not work and must not carry the key.
 */
const BASE = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const KEY = process.env.AGENT_KEY ?? "";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;

  const res = await fetch(`${BASE}/packages/${encodeURIComponent(id)}/resume`, {
    headers: { "X-Agent-Key": KEY },
    cache: "no-store",
  });

  if (!res.ok) {
    const detail = await res.text();
    return new NextResponse(detail.slice(0, 300), {
      status: res.status,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  return new NextResponse(await res.arrayBuffer(), {
    headers: {
      "Content-Type":
        res.headers.get("Content-Type") ??
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "Content-Disposition": res.headers.get("Content-Disposition") ?? 'attachment; filename="resume.docx"',
      "Cache-Control": "no-store",
    },
  });
}
