import * as React from "react";

import { cn } from "@/lib/utils";

type GlitchHeadingProps = React.HTMLAttributes<HTMLHeadingElement> & {
  as?: "h1" | "h2";
};

export function GlitchHeading({ as: Tag = "h1", className, ...props }: GlitchHeadingProps) {
  return (
    <Tag
      className={cn(
        "font-heading uppercase tracking-normal text-primary glitch-text animate-rgb-shift",
        Tag === "h1" ? "text-3xl md:text-5xl" : "text-2xl md:text-3xl",
        className
      )}
      {...props}
    />
  );
}
