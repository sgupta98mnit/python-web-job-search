"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CyberBadge } from "@/components/cyber/CyberBadge";
import { clientApiFetch } from "@/lib/client-api";
import type { Application, Status } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const allowedStatusOptions: Record<Status, Status[]> = {
  discovered: ["discovered", "saved", "applied", "rejected", "ghosted", "irrelevant"],
  saved: ["saved", "applied", "rejected", "ghosted", "irrelevant"],
  applied: ["applied", "interview", "offer", "rejected", "ghosted", "irrelevant"],
  interview: ["interview", "offer", "rejected", "ghosted", "irrelevant"],
  offer: ["offer", "rejected", "irrelevant"],
  rejected: ["rejected", "applied", "irrelevant"],
  ghosted: ["ghosted", "applied", "interview", "rejected", "irrelevant"],
  irrelevant: ["irrelevant", "discovered", "saved"],
};

type JobCardProps = {
  job: Application;
};

export function JobCard({ job }: JobCardProps) {
  const router = useRouter();
  const [status, setStatus] = useState<Status>(job.status);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function changeStatus(nextStatus: Status) {
    if (nextStatus === status) {
      return;
    }
    const previousStatus = status;
    setStatus(nextStatus);
    setSaving(true);
    setError(null);
    try {
      const updated = await clientApiFetch<Application>(`/api/applications/${job.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus }),
      });
      setStatus(updated.status);
      router.refresh();
    } catch (e) {
      setStatus(previousStatus);
      setError(e instanceof Error ? e.message : "status update failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="group relative border border-border bg-card/70 p-4 transition hover:border-primary/60 hover:shadow-neon cyber-chamfer">
      <Link
        href={`/applications/${job.id}`}
        aria-label={`Open application page for ${job.title}`}
        className="absolute inset-0 z-0"
      />
      <div className="pointer-events-none relative z-10 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <CyberBadge status={status} />
            <span className="font-label text-xs uppercase text-muted-foreground">{job.engine}</span>
          </div>
          <h2 className="mt-2 font-heading text-xl uppercase text-foreground">{job.title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {job.company || "unknown"} / {job.location || "unknown"} / {formatDateTime(job.created_at)}
          </p>
          <p className="mt-3 line-clamp-2 text-sm text-muted-foreground">{job.reason || job.snippet}</p>
        </div>
        <div className="flex shrink-0 items-start justify-between gap-3 md:flex-col md:items-end">
          <div className="pointer-events-auto flex items-center gap-2">
            <select
              value={status}
              disabled={saving}
              onChange={(event) => changeStatus(event.target.value as Status)}
              aria-label={`Change status for ${job.title}`}
              className="h-9 min-w-36 border border-primary/45 bg-input/90 px-3 font-label text-xs uppercase text-primary outline-none transition focus:cyber-focus disabled:opacity-45 cyber-chamfer-sm"
            >
              {allowedStatusOptions[status].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <a
              href={job.url}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open original job link for ${job.title}`}
              title="Open job link"
              className="inline-flex size-9 items-center justify-center border border-secondary/70 bg-secondary/10 text-secondary transition hover:border-secondary hover:bg-secondary/20 hover:shadow-neon-cyan cyber-chamfer-sm"
            >
              <ExternalLink className="size-4" aria-hidden="true" />
            </a>
          </div>
          <div className="font-heading text-3xl text-primary">{job.score}</div>
          {error && <p className="max-w-44 text-right text-xs text-destructive">{error}</p>}
        </div>
      </div>
    </article>
  );
}
