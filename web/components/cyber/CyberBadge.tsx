import { cn } from "@/lib/utils";
import type { Status } from "@/lib/types";

type CyberBadgeProps = {
  status: Status;
  className?: string;
};

const statusClasses: Record<Status, string> = {
  discovered: "border-secondary/50 bg-secondary/10 text-secondary",
  saved: "border-primary/50 bg-primary/10 text-primary",
  applied: "border-accent/60 bg-accent/12 text-accent shadow-neon",
  interview: "border-cyber-magenta/60 bg-cyber-magenta/10 text-cyber-magenta shadow-neon-magenta",
  offer: "border-primary bg-primary/15 text-primary shadow-neon",
  rejected: "border-destructive/60 bg-destructive/10 text-destructive",
  ghosted: "border-muted-foreground/40 bg-muted/60 text-muted-foreground",
  irrelevant: "border-cyber-yellow/55 bg-cyber-yellow/10 text-cyber-yellow",
};

export function CyberBadge({ status, className }: CyberBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center border px-2.5 py-1 font-label text-xs uppercase cyber-chamfer-sm",
        statusClasses[status],
        className
      )}
    >
      {status}
    </span>
  );
}
