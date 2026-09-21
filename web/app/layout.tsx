import type { Metadata } from "next";

import { Nav } from "@/components/Nav";
import { RunStatus } from "@/components/RunStatus";

import "./globals.css";

export const metadata: Metadata = {
  title: "job-agent — console",
  description:
    "Run the agents, approve what they draft, track what comes back. Nothing leaves without a click.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Browser extensions inject attributes onto <html> (e.g. data-*-installed)
    // before React hydrates. That is not an app mismatch, and suppressing it
    // here only covers this element's own attributes, nothing deeper.
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen">
        <header className="sticky top-0 z-30 border-b border-edge/80 bg-ink/80 backdrop-blur-xl">
          <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-5 px-5">
            <a href="/" className="group flex items-center gap-2.5">
              <span
                aria-hidden
                className="grid h-6 w-6 place-items-center rounded-md border border-accent/30
                           bg-accent/10 text-[13px] font-semibold text-accent"
              >
                j
              </span>
              <span className="font-mono text-sm font-semibold tracking-tight text-fg">
                job<span className="text-faint">-</span>agent
              </span>
            </a>

            <span aria-hidden className="h-5 w-px bg-edge" />

            <Nav />

            <div className="ml-auto flex items-center gap-4">
              <RunStatus />
              <p className="hidden text-2xs uppercase tracking-[0.14em] text-faint lg:block">
                Agents draft · you approve
              </p>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1440px] px-5 py-6">{children}</main>
      </body>
    </html>
  );
}
