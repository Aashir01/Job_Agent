"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const LINKS = [
  { href: "/", label: "Review" },
  { href: "/outreach", label: "Outreach", badge: "outreach" },
  { href: "/applications", label: "Applications" },
  { href: "/batches", label: "Batches" },
  { href: "/extension", label: "Extension" },
] as const;

const BADGE_POLL_MS = 60000;

export function Nav() {
  const pathname = usePathname();
  const [badges, setBadges] = useState<Record<string, number>>({});

  // Badge counts come from a route handler, not the layout: the root layout
  // must stay static or the build-time /404 prerender breaks.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/stats/badges", { cache: "no-store" });
        if (!res.ok) return;
        if (!cancelled) setBadges((await res.json()) as Record<string, number>);
      } catch {
        /* a missing badge is not worth an error state */
      }
    };
    void poll();
    const timer = setInterval(poll, BADGE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <nav aria-label="Sections" className="flex items-center gap-1">
      {LINKS.map((link) => {
        const active =
          link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
        const count = "badge" in link && link.badge ? badges[link.badge] ?? 0 : 0;
        return (
          <a
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={`relative rounded-lg px-2.5 py-1.5 text-sm transition-colors duration-150 ${
              active ? "text-fg" : "text-muted hover:text-fg"
            }`}
          >
            {link.label}
            {count > 0 && (
              <span
                className="ml-1.5 rounded-full border border-standard/40 bg-standard/10 px-1.5
                           py-px font-mono text-2xs tabular-nums text-standard"
              >
                {count}
              </span>
            )}
            {active && (
              <span
                aria-hidden
                className="absolute inset-x-2.5 -bottom-px h-px bg-accent shadow-[0_0_8px_rgba(122,162,255,0.8)]"
              />
            )}
          </a>
        );
      })}
    </nav>
  );
}
