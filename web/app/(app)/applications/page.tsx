import Link from "next/link";

import { CyberBadge, CyberCard, GlitchHeading } from "@/components/cyber";
import { apiFetch, serverCookieHeader } from "@/lib/api";
import type { Application, Status } from "@/lib/types";
import { statuses } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const applicationStatuses = statuses.filter((status) => status !== "discovered");

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ApplicationsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const selected = single(params.status);
  const statusFilter = selected && selected !== "all" ? selected : applicationStatuses.join(",");
  const cookie = await serverCookieHeader();
  const applications = await apiFetch<Application[]>(
    `/api/applications?status=${encodeURIComponent(statusFilter)}&limit=200`,
    { cookie }
  );
  const grouped = groupByStatus(applications);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <GlitchHeading>applications</GlitchHeading>
        <div className="flex flex-wrap gap-2">
          <Chip href="/applications" label="all" active={!selected || selected === "all"} />
          {applicationStatuses.map((status) => (
            <Chip key={status} href={`/applications?status=${status}`} label={status} active={selected === status} />
          ))}
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        {applicationStatuses.map((status) => (
          <CyberCard key={status} variant={status === "interview" ? "holographic" : "terminal"}>
            <div className="mb-4 flex items-center justify-between">
              <CyberBadge status={status} />
              <span className="font-heading text-2xl text-primary">{grouped[status].length}</span>
            </div>
            <div className="space-y-3">
              {grouped[status].map((job) => (
                <ApplicationRow key={job.id} job={job} />
              ))}
              {grouped[status].length === 0 && (
                <p className="py-3 text-sm text-muted-foreground">no rows in this status</p>
              )}
            </div>
          </CyberCard>
        ))}
      </div>
    </div>
  );
}

function Chip({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={`cyber-chamfer-sm border px-3 py-2 font-label text-xs uppercase transition ${
        active ? "border-primary bg-primary/10 text-primary shadow-neon" : "border-border text-muted-foreground"
      }`}
    >
      {label}
    </Link>
  );
}

function ApplicationRow({ job }: { job: Application }) {
  return (
    <Link
      href={`/applications/${job.id}`}
      className="block border border-border bg-background/45 p-3 transition hover:border-primary/60 hover:bg-primary/5 cyber-chamfer-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-label text-sm uppercase text-foreground">{job.title}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {job.company || "unknown"} / score {job.score} / {formatDateTime(job.status_updated_at)}
          </p>
        </div>
      </div>
    </Link>
  );
}

function groupByStatus(jobs: Application[]) {
  const grouped = Object.fromEntries(applicationStatuses.map((status) => [status, [] as Application[]])) as Record<
    Exclude<Status, "discovered">,
    Application[]
  >;
  for (const job of jobs) {
    if (job.status !== "discovered") {
      grouped[job.status].push(job);
    }
  }
  return grouped;
}

function single(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}
