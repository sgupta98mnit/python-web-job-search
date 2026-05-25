import Link from "next/link";

import { CyberBadge, CyberCard, GlitchHeading, StatPanel } from "@/components/cyber";
import { apiFetch, serverCookieHeader } from "@/lib/api";
import type { Application, OverviewStats } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export default async function DashboardPage() {
  const cookie = await serverCookieHeader();
  const [overview, fresh, recent] = await Promise.all([
    apiFetch<OverviewStats>("/api/stats/overview", { cookie }),
    apiFetch<Application[]>("/api/applications?status=discovered&min_score=80&limit=5", { cookie }),
    apiFetch<Application[]>("/api/applications?status=saved,applied,interview,offer,rejected,ghosted&limit=5", {
      cookie,
    }),
  ]);

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-3">
        <GlitchHeading>dashboard</GlitchHeading>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {overview.total} scored results tracked through the application funnel.
        </p>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <StatPanel label="discovered" value={overview.statuses.discovered} tone="cyan" />
        <StatPanel label="saved" value={overview.statuses.saved} />
        <StatPanel label="applied" value={overview.statuses.applied} />
        <StatPanel label="interviews" value={overview.statuses.interview} tone="magenta" />
      </section>

      <section className="grid gap-5 lg:grid-cols-[1fr_1fr]">
        <CyberCard variant="terminal">
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="font-heading text-xl uppercase text-primary">fresh discoveries</h2>
            <span className="font-label text-xs uppercase text-muted-foreground">score &gt;= 80</span>
          </div>
          <div className="space-y-3">
            {fresh.map((job) => (
              <JobLine key={job.id} job={job} />
            ))}
            {fresh.length === 0 && <p className="text-sm text-muted-foreground">no high-score discoveries</p>}
          </div>
        </CyberCard>

        <CyberCard variant="holographic">
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="font-heading text-xl uppercase text-secondary">recent activity</h2>
            <Link href="/applications" className="font-label text-xs uppercase text-primary hover:underline">
              open funnel
            </Link>
          </div>
          <div className="space-y-3">
            {recent.map((job) => (
              <JobLine key={job.id} job={job} showStatus />
            ))}
            {recent.length === 0 && <p className="text-sm text-muted-foreground">no application movement yet</p>}
          </div>
        </CyberCard>
      </section>

      <CyberCard>
        <h2 className="mb-4 font-heading text-xl uppercase text-primary">score bands</h2>
        <div className="grid gap-3 md:grid-cols-4">
          {Object.entries(overview.score_buckets).map(([bucket, count]) => (
            <div key={bucket} className="border border-border bg-muted/35 p-4 cyber-chamfer-sm">
              <div className="font-heading text-2xl text-primary">{count}</div>
              <div className="mt-1 font-label text-xs uppercase text-muted-foreground">{bucket}</div>
            </div>
          ))}
        </div>
      </CyberCard>
    </div>
  );
}

function JobLine({ job, showStatus = false }: { job: Application; showStatus?: boolean }) {
  return (
    <Link
      href={`/applications/${job.id}`}
      className="block border border-border bg-background/45 p-3 transition hover:border-primary/60 hover:bg-primary/5 cyber-chamfer-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-label text-sm uppercase text-foreground">{job.title}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {job.company || "unknown"} / {formatDateTime(job.created_at)}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {showStatus && <CyberBadge status={job.status} />}
          <span className="font-heading text-lg text-primary">{job.score}</span>
        </div>
      </div>
    </Link>
  );
}
