import { cn } from "@/lib/utils";

type StatPanelProps = {
  label: string;
  value: number | string;
  tone?: "accent" | "cyan" | "magenta" | "red";
};

const tones: Record<NonNullable<StatPanelProps["tone"]>, string> = {
  accent: "text-primary",
  cyan: "text-secondary",
  magenta: "text-cyber-magenta",
  red: "text-destructive",
};

export function StatPanel({ label, value, tone = "accent" }: StatPanelProps) {
  return (
    <div className="cyber-chamfer border border-border bg-card/78 p-4 shadow-terminal">
      <div className={cn("font-heading text-3xl leading-none drop-shadow-[0_0_12px_currentColor]", tones[tone])}>
        {value}
      </div>
      <div className="mt-2 font-label text-xs uppercase text-muted-foreground">{label}</div>
    </div>
  );
}
