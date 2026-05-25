import * as React from "react";

import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "cyber-chamfer-sm h-10 w-full border border-border bg-input/80 px-3 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus:cyber-focus",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
