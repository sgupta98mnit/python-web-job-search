import * as React from "react";

import { cn } from "@/lib/utils";

type CyberCardProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "terminal" | "holographic";
  hover?: boolean;
};

export function CyberCard({
  className,
  variant = "default",
  hover = false,
  children,
  ...props
}: CyberCardProps) {
  return (
    <section
      className={cn(
        "cyber-chamfer relative overflow-hidden border bg-card/82 text-card-foreground shadow-terminal",
        variant === "default" && "border-border",
        variant === "terminal" && "border-primary/45",
        variant === "holographic" && "border-secondary/45 bg-cyber-panel2/70 shadow-neon-cyan",
        hover && "transition hover:-translate-y-0.5 hover:border-primary/70 hover:shadow-neon",
        className
      )}
      {...props}
    >
      {variant === "terminal" && (
        <div className="flex items-center gap-2 border-b border-primary/20 px-4 py-2 terminal-dots">
          <span />
          <span />
          <span />
        </div>
      )}
      <div className={cn(variant === "terminal" ? "p-4" : "p-5")}>{children}</div>
    </section>
  );
}
