import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "job-agent — review queue",
  description: "Approve, edit or reject drafted applications. Nothing leaves without a click.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="sticky top-0 z-20 border-b border-edge bg-ink/95 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
            <a href="/" className="font-mono text-sm font-semibold tracking-tight">
              job<span className="text-muted">-</span>agent
            </a>
            <nav className="flex gap-3 text-sm text-muted">
              <a className="hover:text-slate-200" href="/">Review</a>
              <a className="hover:text-slate-200" href="/applications">Applications</a>
            </nav>
            <span className="ml-auto text-xs text-muted">
              Agents draft. You approve.
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
