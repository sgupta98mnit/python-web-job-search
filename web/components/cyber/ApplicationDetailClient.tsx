"use client";

import { Copy, Download, ExternalLink, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CyberBadge, CyberButton, CyberCard, CyberSelect, GlitchHeading } from "@/components/cyber";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Toast } from "@/components/ui/toast";
import { clientApiBase, clientApiFetch } from "@/lib/client-api";
import type { ApplicationDetail, ApplicationPatch, ResumeVersion, ResumeVersionSummary, Status } from "@/lib/types";
import { statuses } from "@/lib/types";
import { formatDate, formatDateTime } from "@/lib/utils";

type Props = {
  application: ApplicationDetail;
  initialResumes: ResumeVersionSummary[];
};

export function ApplicationDetailClient({ application, initialResumes }: Props) {
  const [status, setStatus] = useState<Status>(application.status);
  const [notes, setNotes] = useState(application.notes ?? "");
  const [appliedAt, setAppliedAt] = useState(dateInput(application.applied_at));
  const [resumes, setResumes] = useState(initialResumes);
  const [selected, setSelected] = useState<ResumeVersion | null>(null);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [existing, setExisting] = useState<ResumeVersion | null>(null);

  const downloadHref = useMemo(() => {
    if (!selected) {
      return null;
    }
    return `${clientApiBase()}/api/resumes/${selected.id}/download`;
  }, [selected]);

  useEffect(() => {
    if (notes === (application.notes ?? "")) {
      return;
    }
    const handle = window.setTimeout(async () => {
      await patch({ notes }, "notes saved");
    }, 800);
    return () => window.clearTimeout(handle);
  }, [notes]);

  async function patch(body: ApplicationPatch, message: string) {
    setSaving(true);
    setError(null);
    try {
      const updated = await clientApiFetch<ApplicationDetail>(`/api/applications/${application.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setStatus(updated.status);
      setAppliedAt(dateInput(updated.applied_at));
      setToast(message);
      window.setTimeout(() => setToast(null), 2200);
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(next: string) {
    await patch({ status: next as Status }, "status updated");
  }

  async function changeAppliedAt(value: string) {
    setAppliedAt(value);
    await patch({ applied_at: value ? new Date(`${value}T12:00:00`).toISOString() : null }, "applied date updated");
  }

  async function loadVersion(versionId: number) {
    const full = await clientApiFetch<ResumeVersion>(`/api/resumes/${versionId}`);
    setSelected(full);
  }

  async function generate(force = false) {
    setGenerating(true);
    setError(null);
    try {
      const version = await clientApiFetch<ResumeVersion>(
        `/api/applications/${application.id}/resumes${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      const alreadyListed = resumes.some((resume) => resume.id === version.id);
      if (!alreadyListed) {
        setResumes([{ ...version }, ...resumes]);
        setSelected(version);
        setToast("resume generated");
      } else if (!force) {
        setExisting(version);
      } else {
        setSelected(version);
        setToast("resume regenerated");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "resume generation failed");
    } finally {
      setGenerating(false);
      window.setTimeout(() => setToast(null), 2200);
    }
  }

  async function copyTex() {
    if (!selected) {
      return;
    }
    await navigator.clipboard.writeText(selected.tex_content);
    setToast("copied");
    window.setTimeout(() => setToast(null), 2200);
  }

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <GlitchHeading>{application.title}</GlitchHeading>
        <div className="flex flex-wrap items-center gap-3">
          <CyberBadge status={status} />
          <span className="font-heading text-2xl text-primary">{application.score}</span>
          <span className="font-label text-xs uppercase text-muted-foreground">{application.company || "unknown"}</span>
          <a
            className="inline-flex items-center gap-1 font-label text-xs uppercase text-secondary hover:underline"
            href={application.url}
            target="_blank"
            rel="noreferrer"
          >
            source <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <p className="text-sm text-muted-foreground">found {formatDateTime(application.created_at)}</p>
      </section>

      <CyberCard variant="terminal">
        <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
          <div className="space-y-4">
            <CyberSelect label="status" value={status} onValueChange={changeStatus} options={statuses} />
            {status === "applied" && (
              <label className="block space-y-2">
                <span className="font-label text-xs uppercase text-muted-foreground">applied at</span>
                <input className="field" type="date" value={appliedAt} onChange={(event) => changeAppliedAt(event.target.value)} />
              </label>
            )}
            <div className="text-xs text-muted-foreground">last status update {formatDate(application.status_updated_at)}</div>
          </div>
          <label className="block space-y-2">
            <span className="font-label text-xs uppercase text-muted-foreground">notes</span>
            <textarea
              className="min-h-44 w-full resize-y border border-border bg-input/80 p-3 text-sm outline-none focus:cyber-focus cyber-chamfer-sm"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
            <span className="font-label text-xs uppercase text-muted-foreground">{saving ? "saving" : "autosave armed"}</span>
          </label>
        </div>
        {error && <p className="mt-4 text-sm text-destructive">{error}</p>}
      </CyberCard>

      <CyberCard variant="holographic">
        <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="font-heading text-2xl uppercase text-secondary">resume builder</h2>
            <p className="mt-1 text-sm text-muted-foreground">{resumes.length} stored versions</p>
          </div>
          <CyberButton variant="glitch" onClick={() => generate(false)} loading={generating}>
            <Sparkles className="h-4 w-4" />
            generate tailored resume
          </CyberButton>
        </div>

        <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
          <div className="space-y-3">
            {resumes.map((resume) => (
              <button
                key={resume.id}
                onClick={() => loadVersion(resume.id)}
                className="block w-full border border-border bg-background/45 p-3 text-left transition hover:border-primary/60 cyber-chamfer-sm"
              >
                <div className="font-label text-sm uppercase text-foreground">version #{resume.id}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {formatDateTime(resume.generated_at)} / {resume.model}
                </div>
              </button>
            ))}
            {resumes.length === 0 && <p className="text-sm text-muted-foreground">no generated resumes</p>}
          </div>

          <div className="min-w-0">
            {selected ? (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <CyberButton variant="outline" size="sm" onClick={copyTex}>
                    <Copy className="h-4 w-4" />
                    copy
                  </CyberButton>
                  {downloadHref && (
                    <a href={downloadHref} download>
                      <CyberButton variant="secondary" size="sm">
                        <Download className="h-4 w-4" />
                        download
                      </CyberButton>
                    </a>
                  )}
                </div>
                <pre className="max-h-[36rem] overflow-auto border border-border bg-background/80 p-4 text-xs leading-relaxed text-foreground cyber-chamfer-sm">
                  <code>{selected.tex_content}</code>
                </pre>
              </div>
            ) : (
              <div className="flex min-h-72 items-center justify-center border border-border bg-background/45 text-sm text-muted-foreground cyber-chamfer-sm">
                select or generate a version
              </div>
            )}
          </div>
        </div>
      </CyberCard>

      <Dialog open={Boolean(existing)} onOpenChange={(open) => !open && setExisting(null)}>
        <DialogContent>
          <DialogTitle className="font-heading text-xl uppercase text-primary">existing version found</DialogTitle>
          <DialogDescription className="mt-2 text-sm text-muted-foreground">
            A resume with the same prompt hash already exists from {existing ? formatDateTime(existing.generated_at) : ""}.
          </DialogDescription>
          <div className="mt-5 flex flex-wrap gap-3">
            <CyberButton
              onClick={() => {
                if (existing) {
                  setSelected(existing);
                }
                setExisting(null);
              }}
            >
              open
            </CyberButton>
            <CyberButton variant="outline" onClick={() => generate(true)}>
              regenerate anyway
            </CyberButton>
          </div>
        </DialogContent>
      </Dialog>

      <Toast message={toast} tone="success" />
    </div>
  );
}

function dateInput(value: string | null) {
  if (!value) {
    return "";
  }
  return value.slice(0, 10);
}
