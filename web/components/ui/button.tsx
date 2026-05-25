import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap cyber-chamfer-sm border px-4 py-2 text-sm font-semibold uppercase tracking-normal transition focus-visible:cyber-focus disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "border-primary/70 bg-primary text-primary-foreground shadow-neon hover:bg-primary/90",
        secondary: "border-secondary/60 bg-secondary/15 text-secondary hover:shadow-neon-cyan",
        outline: "border-primary/50 bg-background/70 text-primary hover:bg-primary/10 hover:shadow-neon",
        ghost: "border-transparent bg-transparent text-muted-foreground hover:text-primary",
        destructive: "border-destructive/60 bg-destructive/15 text-destructive hover:bg-destructive/20",
      },
      size: {
        default: "h-10",
        sm: "h-8 px-3 text-xs",
        lg: "h-12 px-5",
        icon: "h-10 w-10 px-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>;

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
  )
);
Button.displayName = "Button";

export { buttonVariants };
