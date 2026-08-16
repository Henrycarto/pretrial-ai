"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { EngineBanner } from "./EngineBanner";

/**
 * Application chrome.
 *
 * A fixed left rail rather than a top nav bar. The working surfaces here are
 * wide tables and side by side charts, so vertical space is the scarce
 * resource and a persistent horizontal bar spends it badly.
 */

const NAV: { section: string; items: { href: string; label: string; code: string }[] }[] = [
  {
    section: "cohorts",
    items: [
      { href: "/dashboard", label: "Dashboard", code: "00" },
      { href: "/cohorts", label: "All cohorts", code: "01" },
      { href: "/cohorts/new", label: "New cohort", code: "02" },
    ],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // The landing page is the marketing surface and gets no application
  // chrome around it.
  if (pathname === "/" || pathname.startsWith("/login")) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-edge bg-surface-sunken">
        <div className="border-b border-edge px-4 py-4">
          <Link href="/" className="block">
            <div className="font-mono text-sm tracking-tight text-ink">
              Pretrial<span className="text-accent">.ai</span>
            </div>
            <div className="label-micro mt-1">feasibility instrument</div>
          </Link>
        </div>

        <nav className="flex-1 overflow-y-auto py-4">
          {NAV.map((group) => (
            <div key={group.section} className="mb-5">
              <div className="label-micro px-4 pb-2">{group.section}</div>
              <ul>
                {group.items.map((item) => {
                  const active =
                    item.href === "/cohorts"
                      ? pathname === "/cohorts"
                      : pathname.startsWith(item.href);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={cn(
                          "flex items-center gap-3 border-l-2 px-4 py-2 text-sm transition-colors",
                          active
                            ? "border-accent bg-surface text-ink"
                            : "border-transparent text-ink-muted hover:border-edge-strong hover:text-ink",
                        )}
                      >
                        <span className="tabular text-[10px] text-ink-dim">{item.code}</span>
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-edge px-4 py-3">
          <div className="label-micro mb-1.5">services</div>
          <ul className="space-y-1">
            {[
              ["SyntheCore", "8001"],
              ["FidelityCheck", "8002"],
              ["FHIR-Link", "8003"],
            ].map(([name, port]) => (
              <li key={name} className="flex items-center justify-between">
                <span className="text-[11px] text-ink-muted">{name}</span>
                <span className="tabular text-[10px] text-ink-dim">:{port}</span>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <EngineBanner />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

/** Page header used by every application page, for a consistent top rule. */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="border-b border-edge bg-surface px-6 py-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-medium tracking-tight text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
