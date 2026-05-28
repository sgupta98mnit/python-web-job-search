import Link from "next/link";

import { CyberCard, GlitchHeading } from "@/components/cyber";
import { apiFetch, serverCookieHeader } from "@/lib/api";
import type { SearchSourceHost, SearchSourcesResponse } from "@/lib/types";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "result_count_desc", label: "results: most first" },
  { value: "avg_score_desc", label: "avg score: high to low" },
  { value: "avg_score_asc", label: "avg score: low to high (find junk)" },
  { value: "kept_count_desc", label: "kept count: most first" },
  { value: "host_asc", label: "host A-Z" },
];

export default async function SourcesPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const engine = single(params.engine) ?? "";
  const dateFrom = single(params.date_from) ?? "";
  const dateTo = single(params.date_to) ?? "";
  const sort = single(params.sort) ?? "result_count_desc";

  const query = new URLSearchParams({ sort, limit: "200" });
  if (engine) query.set("engine", engine);
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);

  const cookie = await serverCookieHeader();
  const data = await apiFetch<SearchSourcesResponse>(
    `/api/search/sources?${query.toString()}`,
    { cookie }
  );

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GlitchHeading>sources</GlitchHeading>
        <p className="max-w-3xl text-sm text-muted-foreground">
          aggregated host stats across every SearchResult row. Use this to spot
          domains that waste your serper budget on low-scoring URLs, then strike
          them from sites.txt.
        </p>
      </div>

      <CyberCard variant="terminal">
        <form className="grid gap-3 md:grid-cols-5">
          <select name="sort" defaultValue={sort} className="field md:col-span-2">
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                sort: {option.label}
              </option>
            ))}
          </select>
          <input className="field" name="engine" placeholder="engine (e.g. serper)" defaultValue={engine} />
          <input className="field" name="date_from" type="date" defaultValue={dateFrom} />
          <input className="field" name="date_to" type="date" defaultValue={dateTo} />
          <button className="cyber-chamfer-sm border border-primary/60 bg-primary px-4 py-2 font-label text-sm uppercase text-primary-foreground md:col-span-5">
            apply filters
          </button>
        </form>
      </CyberCard>

      <p className="font-label text-xs uppercase text-muted-foreground">
        {data.total_hosts} hosts (showing {data.hosts.length})
      </p>

      <div className="space-y-3">
        {data.hosts.length === 0 ? (
          <p className="border border-border bg-card/40 p-6 text-center text-sm text-muted-foreground cyber-chamfer">
            no results matched
          </p>
        ) : (
          data.hosts.map((host) => <HostRow key={host.host} host={host} />)
        )}
      </div>
    </div>
  );
}

function HostRow({ host }: { host: SearchSourceHost }) {
  const avg = host.avg_score === null ? "-" : host.avg_score.toFixed(1);
  return (
    <CyberCard variant="terminal">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <h2 className="font-heading text-lg uppercase text-foreground">{host.host}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {host.result_count} results / {host.scored_count} scored / {host.kept_count} kept
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          <div className="text-center">
            <div className="font-heading text-2xl text-primary">{avg}</div>
            <div className="font-label text-xs uppercase text-muted-foreground">avg</div>
          </div>
          <div className="text-center">
            <div className="font-heading text-2xl text-secondary">
              {host.max_score ?? "-"}
            </div>
            <div className="font-label text-xs uppercase text-muted-foreground">max</div>
          </div>
        </div>
      </div>

      {host.top_queries.length > 0 && (
        <div className="mt-3">
          <p className="font-label text-xs uppercase text-muted-foreground">top queries</p>
          <ul className="mt-1 space-y-1 text-xs">
            {host.top_queries.map((q) => (
              <li key={q.query_text} className="truncate">
                <span className="text-secondary">{q.query_text}</span>{" "}
                <span className="text-muted-foreground">({q.count})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {host.examples.length > 0 && (
        <div className="mt-3">
          <p className="font-label text-xs uppercase text-muted-foreground">examples</p>
          <ul className="mt-1 space-y-1 text-xs">
            {host.examples.map((ex) => (
              <li key={ex.url} className="truncate">
                <span className="text-primary">
                  {ex.score === null ? "-" : ex.score}
                </span>{" "}
                {ex.application_id !== null ? (
                  <Link
                    href={`/applications/${ex.application_id}`}
                    className="text-foreground hover:text-primary"
                  >
                    {ex.url}
                  </Link>
                ) : (
                  <span className="text-foreground">{ex.url}</span>
                )}
                {ex.query_text && (
                  <span className="text-muted-foreground"> via {ex.query_text}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          href={`/jobs?site=${encodeURIComponent(host.host)}`}
          className="cyber-chamfer-sm border border-border px-3 py-1 font-label text-xs uppercase text-muted-foreground transition hover:border-primary/60 hover:text-primary"
        >
          view all jobs from {host.host}
        </Link>
      </div>
    </CyberCard>
  );
}

function single(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}
