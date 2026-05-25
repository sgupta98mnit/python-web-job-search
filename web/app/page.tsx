import Link from "next/link";
import {
  Bot,
  BrainCircuit,
  Cpu,
  Database,
  FileCode2,
  LockKeyhole,
  Mail,
  Network,
  ShieldCheck,
} from "lucide-react";

import { CyberCard, GlitchHeading } from "@/components/cyber";

const contactEmail = process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? process.env.CONTACT_EMAIL;
const requestAccessHref = contactEmail
  ? `mailto:${contactEmail}?subject=${encodeURIComponent("Job Search Control Plane access")}`
  : undefined;

const workflow = [
  {
    title: "collect",
    text: "A Python daemon queries multiple job sources, deduplicates the feed, and stores each result in Postgres.",
  },
  {
    title: "score",
    text: "Claude reviews each role against target criteria, writes a score, and keeps the reasoning visible for audit.",
  },
  {
    title: "track",
    text: "FastAPI exposes a private control plane for saved roles, applications, notes, status changes, and history.",
  },
  {
    title: "tailor",
    text: "The resume builder uses the saved LaTeX template plus the job context to generate a targeted resume version.",
  },
];

const architecture = [
  { label: "Python daemon", icon: Bot, detail: "scheduled search ingestion and scoring loop" },
  { label: "Postgres", icon: Database, detail: "single source of truth for results, statuses, and resume versions" },
  { label: "FastAPI", icon: Cpu, detail: "authenticated JSON API with one transaction per request" },
  { label: "Next.js", icon: Network, detail: "cyberpunk control plane for review, tracking, and resume generation" },
  { label: "Claude", icon: BrainCircuit, detail: "job fit analysis and resume tailoring" },
  { label: "LaTeX", icon: FileCode2, detail: "versioned resume source that can be compiled or downloaded" },
];

export default function HomePage() {
  return (
    <main className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-primary/20 bg-background/88 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4">
          <span className="font-heading text-sm uppercase text-primary glitch-text">jobsearch://public</span>
          <nav className="flex items-center gap-2">
            <Link
              href="/login"
              className="cyber-chamfer-sm border border-primary/60 bg-primary/10 px-3 py-2 font-label text-xs uppercase text-primary transition hover:bg-primary hover:text-primary-foreground hover:shadow-neon"
            >
              login
            </Link>
          </nav>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-8 px-5 pb-14 pt-10 lg:min-h-[calc(100vh-4.5rem)] lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
        <div className="space-y-6">
          <p className="font-label text-xs uppercase text-secondary">for recruiters and engineering managers</p>
          <GlitchHeading className="max-w-4xl text-4xl md:text-6xl">job search control plane</GlitchHeading>
          <p className="max-w-3xl text-base leading-7 text-muted-foreground md:text-lg">
            This project is a working hiring-operations system: it finds software roles, scores fit with an LLM,
            tracks the application funnel, and generates per-job tailored LaTeX resumes from a single source
            template.
          </p>
          <div className="flex flex-wrap gap-3">
            {requestAccessHref ? (
              <a
                href={requestAccessHref}
                className="cyber-chamfer-sm inline-flex items-center gap-2 border border-primary/70 bg-primary px-4 py-3 font-label text-sm uppercase text-primary-foreground shadow-neon transition hover:bg-primary/90"
              >
                <Mail className="size-4" aria-hidden="true" />
                email for password
              </a>
            ) : (
              <span className="cyber-chamfer-sm inline-flex items-center gap-2 border border-primary/60 bg-primary/10 px-4 py-3 font-label text-sm uppercase text-primary">
                <Mail className="size-4" aria-hidden="true" />
                email me for password
              </span>
            )}
            <Link
              href="/login"
              className="cyber-chamfer-sm inline-flex items-center gap-2 border border-secondary/60 bg-secondary/10 px-4 py-3 font-label text-sm uppercase text-secondary transition hover:shadow-neon-cyan"
            >
              <LockKeyhole className="size-4" aria-hidden="true" />
              access demo
            </Link>
          </div>
          <p className="max-w-2xl text-sm text-muted-foreground">
            The live dashboard is password protected because it contains active job data, notes, scoring rationale,
            and resume material. Request the password by email before opening the private control plane.
          </p>
        </div>

        <div className="relative min-h-[28rem] overflow-hidden border border-primary/35 bg-card/60 p-5 shadow-terminal cyber-chamfer">
          <div className="absolute inset-x-0 top-0 border-t border-primary/70 shadow-neon" />
          <div className="grid h-full content-center gap-4">
            {architecture.slice(0, 5).map((node, index) => {
              const Icon = node.icon;
              return (
                <div
                  key={node.label}
                  className={`cyber-chamfer-sm border bg-background/70 p-4 ${
                    index % 2 === 0 ? "border-primary/50 text-primary" : "ml-8 border-secondary/45 text-secondary"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <Icon className="mt-1 size-5 shrink-0" aria-hidden="true" />
                    <div>
                      <div className="font-label text-sm uppercase">{node.label}</div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">{node.detail}</div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="border-y border-primary/20 bg-background/65">
        <div className="mx-auto grid max-w-7xl gap-4 px-5 py-12 md:grid-cols-4">
          {workflow.map((step, index) => (
            <CyberCard key={step.title} hover>
              <div className="font-heading text-3xl text-primary">{String(index + 1).padStart(2, "0")}</div>
              <h2 className="mt-4 font-heading text-xl uppercase text-foreground">{step.title}</h2>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{step.text}</p>
            </CyberCard>
          ))}
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-6 px-5 py-12 lg:grid-cols-[0.9fr_1.1fr]">
        <CyberCard variant="terminal">
          <h2 className="font-heading text-2xl uppercase text-primary">motivation</h2>
          <div className="mt-5 space-y-4 text-sm leading-6 text-muted-foreground">
            <p>
              Job searching is repetitive operational work. I built this to turn that process into a reliable system:
              collect the noisy feed, rank the roles worth attention, preserve context, and reduce the manual work
              needed to respond thoughtfully.
            </p>
            <p>
              The project also demonstrates how I approach product engineering: define the workflow, keep the data
              model simple, automate the expensive judgment calls, and build an interface that makes the next action
              obvious.
            </p>
          </div>
        </CyberCard>

        <CyberCard variant="holographic">
          <div className="flex items-center gap-3">
            <ShieldCheck className="size-6 text-secondary" aria-hidden="true" />
            <h2 className="font-heading text-2xl uppercase text-secondary">architecture signals</h2>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {architecture.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="border border-border bg-background/45 p-4 cyber-chamfer-sm">
                  <div className="flex items-center gap-2 font-label text-sm uppercase text-foreground">
                    <Icon className="size-4 text-primary" aria-hidden="true" />
                    {item.label}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                </div>
              );
            })}
          </div>
        </CyberCard>
      </section>
    </main>
  );
}
