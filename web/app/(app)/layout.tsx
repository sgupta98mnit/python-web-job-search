import Link from "next/link";

import { LogoutButton } from "@/components/cyber";

const nav = [
  { href: "/dashboard", label: "dashboard" },
  { href: "/jobs", label: "jobs" },
  { href: "/applications", label: "applications" },
];

export default function AppLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-primary/20 bg-background/88 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4">
          <Link href="/dashboard" className="font-heading text-sm uppercase text-primary glitch-text">
            jobsearch://control
          </Link>
          <nav className="flex items-center gap-2">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="cyber-chamfer-sm border border-border px-3 py-2 font-label text-xs uppercase text-muted-foreground transition hover:border-primary/60 hover:text-primary"
              >
                {item.label}
              </Link>
            ))}
            <LogoutButton />
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-8">{children}</main>
    </div>
  );
}
