"use client";

import { cn } from "@/lib/utils";

type ToastProps = {
  message: string | null;
  tone?: "default" | "error" | "success";
};

export function Toast({ message, tone = "default" }: ToastProps) {
  if (!message) {
    return null;
  }
  return (
    <div
      className={cn(
        "fixed bottom-6 right-6 z-50 max-w-sm border bg-card px-4 py-3 text-sm shadow-terminal cyber-chamfer-sm",
        tone === "default" && "border-primary/50 text-primary",
        tone === "success" && "border-primary/60 text-primary shadow-neon",
        tone === "error" && "border-destructive/60 text-destructive"
      )}
    >
      {message}
    </div>
  );
}
