import Link from "next/link";

import { CyberCard, GlitchHeading, JobCard, SerperSearchButton } from "@/components/cyber";
import { apiFetch, serverCookieHeader } from "@/lib/api";
import type { Application, SerperEstimate } from "@/lib/types";
import { statuses } from "@/lib/types";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PAGE_SIZE = 50;

const SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "date_desc", label: "newest first" },
  { value: "date_asc", label: "oldest first" },
  { value: "score_desc", label: "score: high to low" },
  { value: "score_asc", label: "score: low to high" },
  { value: "company_asc", label: "company A-Z" },
];

const BASE_PATH = normalizeBasePath(process.env.NEXT_PUBLIC_BASE_PATH);
const JOBS_ACTION = `${BASE_PATH}/jobs`;

export default async function JobsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const status = single(params.status);
  const minScore = single(params.min_score);
  const site = single(params.site)?.toLowerCase();
  const dateFrom = single(params.date_from);
  const dateTo = single(params.date_to);
  const sort = single(params.sort) ?? "date_desc";
  const page = Math.max(1, Number(single(params.page)) || 1);

  const query = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    sort,
  });
  if (status && status !== "all") query.set("status", status);
  if (minScore) query.set("min_score", minScore);
  if (site) query.set("site", site);
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);

  const cookie = await serverCookieHeader();
  const [jobs, serperEstimate] = await Promise.all([
    apiFetch<Application[]>(`/api/applications?${query.toString()}`, { cookie }),
    apiFetch<SerperEstimate>("/api/search/serper/estimate", { cookie }),
  ]);

  const hasNext = jobs.length === PAGE_SIZE;
  const hasPrev = page > 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <GlitchHeading>raw feed</GlitchHeading>
          <p className="max-w-3xl text-sm text-muted-foreground">
            SearXNG results arrive through the daemon. Use Serper boost only when you want a paid Google refresh.
          </p>
        </div>
        <SerperSearchButton estimate={serperEstimate} />
      </div>
      <CyberCard variant="terminal">
        {/* Filter form resets to page 1 on submit (no `page` field), so changing
            filters never strands the user on an empty page deep in the result set. */}
        <form action={JOBS_ACTION} className="grid gap-3 md:grid-cols-6">
          <select name="status" defaultValue={status ?? "all"} className="field">
            <option value="all">all statuses</option>
            {statuses.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select name="sort" defaultValue={sort} className="field">
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                sort: {option.label}
              </option>
            ))}
          </select>
          <input className="field" name="min_score" placeholder="min score" defaultValue={minScore ?? ""} />
          <input className="field" name="site" placeholder="site filter" defaultValue={site ?? ""} />
          <input className="field" name="date_from" type="date" defaultValue={dateFrom ?? ""} />
          <input className="field" name="date_to" type="date" defaultValue={dateTo ?? ""} />
          <button className="cyber-chamfer-sm border border-primary/60 bg-primary px-4 py-2 font-label text-sm uppercase text-primary-foreground md:col-span-6">
            apply filters
          </button>
        </form>
      </CyberCard>

      <div className="space-y-3">
        {jobs.length === 0 ? (
          <p className="border border-border bg-card/40 p-6 text-center text-sm text-muted-foreground cyber-chamfer">
            no results on this page
          </p>
        ) : (
          jobs.map((job) => <JobCard key={job.id} job={job} />)
        )}
      </div>

      <nav className="flex items-center justify-between border-t border-border pt-4 font-label text-xs uppercase text-muted-foreground">
        <span>page {page}</span>
        <div className="flex items-center gap-2">
          <PaginationLink
            disabled={!hasPrev}
            href={paginationHref(params, page - 1)}
            label="prev"
          />
          <PaginationLink
            disabled={!hasNext}
            href={paginationHref(params, page + 1)}
            label="next"
          />
        </div>
      </nav>
    </div>
  );
}

function paginationHref(
  params: Record<string, string | string[] | undefined>,
  targetPage: number,
) {
  const next = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (key === "page" || value === undefined) continue;
    next.set(key, Array.isArray(value) ? value[0] ?? "" : value);
  }
  if (targetPage > 1) next.set("page", String(targetPage));
  const qs = next.toString();
  return qs ? `/jobs?${qs}` : "/jobs";
}

function PaginationLink({
  disabled,
  href,
  label,
}: {
  disabled: boolean;
  href: string;
  label: string;
}) {
  const base =
    "cyber-chamfer-sm border px-3 py-2 transition";
  if (disabled) {
    return (
      <span
        aria-disabled
        className={`${base} cursor-not-allowed border-border/40 text-muted-foreground/40`}
      >
        {label}
      </span>
    );
  }
  return (
    <Link
      href={href}
      className={`${base} border-primary/60 text-primary hover:bg-primary/15`}
    >
      {label}
    </Link>
  );
}

function single(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeBasePath(value: string | undefined) {
  if (!value) {
    return "";
  }
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed || trimmed === "/") {
    return "";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}
