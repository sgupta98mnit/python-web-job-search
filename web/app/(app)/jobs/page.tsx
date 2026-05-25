import { CyberCard, GlitchHeading, JobCard, SerperSearchButton } from "@/components/cyber";
import { apiFetch, serverCookieHeader } from "@/lib/api";
import type { Application, SerperEstimate } from "@/lib/types";
import { statuses } from "@/lib/types";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function JobsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const status = single(params.status);
  const minScore = single(params.min_score);
  const site = single(params.site)?.toLowerCase();
  const dateFrom = single(params.date_from);
  const dateTo = single(params.date_to);
  const query = new URLSearchParams({ limit: "100" });
  if (status && status !== "all") {
    query.set("status", status);
  }
  if (minScore) {
    query.set("min_score", minScore);
  }

  const cookie = await serverCookieHeader();
  const [rawJobs, serperEstimate] = await Promise.all([
    apiFetch<Application[]>(`/api/applications?${query.toString()}`, { cookie }),
    apiFetch<SerperEstimate>("/api/search/serper/estimate", { cookie }),
  ]);
  const jobs = applyLocalFilters(rawJobs, { site, dateFrom, dateTo });

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
        <form className="grid gap-3 md:grid-cols-5">
          <select name="status" defaultValue={status ?? "all"} className="field">
            <option value="all">all statuses</option>
            {statuses.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <input className="field" name="min_score" placeholder="min score" defaultValue={minScore ?? ""} />
          <input className="field" name="site" placeholder="site filter" defaultValue={site ?? ""} />
          <input className="field" name="date_from" type="date" defaultValue={dateFrom ?? ""} />
          <input className="field" name="date_to" type="date" defaultValue={dateTo ?? ""} />
          <button className="cyber-chamfer-sm border border-primary/60 bg-primary px-4 py-2 font-label text-sm uppercase text-primary-foreground md:col-span-5">
            apply filters
          </button>
        </form>
      </CyberCard>

      <div className="space-y-3">
        {jobs.map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
      </div>
    </div>
  );
}

function single(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function applyLocalFilters(
  jobs: Application[],
  filters: { site?: string; dateFrom?: string; dateTo?: string }
) {
  return jobs.filter((job) => {
    const found = new Date(job.created_at).getTime();
    if (filters.site && !job.url.toLowerCase().includes(filters.site)) {
      return false;
    }
    if (filters.dateFrom && found < new Date(filters.dateFrom).getTime()) {
      return false;
    }
    if (filters.dateTo && found > new Date(`${filters.dateTo}T23:59:59`).getTime()) {
      return false;
    }
    return true;
  });
}
