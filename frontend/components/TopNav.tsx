"use client";

import { DatabaseZap, Library, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const NAV_ITEMS = [
  { href: "/", label: "NL2SQL", icon: DatabaseZap },
  { href: "/anomaly-engine", label: "Anomaly Engine", icon: ShieldAlert },
  { href: "/data-catalog", label: "Data Catalog", icon: Library },
] as const;

export default function TopNav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-surface-border bg-surface-raised">
      <div className="mx-auto flex max-w-6xl items-center gap-1 px-6 py-3">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition",
                isActive
                  ? "bg-indigo-500/15 text-indigo-400"
                  : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
              )}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
