"use client";

import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Review" },
  { href: "/applications", label: "Applications" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Sections" className="flex items-center gap-1">
      {LINKS.map((link) => {
        const active = pathname === link.href;
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
