import { Loader2 } from "lucide-react";
import * as React from "react";

import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CyberButtonProps = Omit<ButtonProps, "variant"> & {
  variant?: "default" | "secondary" | "outline" | "ghost" | "glitch";
  loading?: boolean;
};

export const CyberButton = React.forwardRef<HTMLButtonElement, CyberButtonProps>(
  ({ className, variant = "default", loading = false, children, disabled, ...props }, ref) => {
    const mapped = variant === "glitch" ? "default" : variant;
    return (
      <Button
        ref={ref}
        className={cn(
          "font-label",
          variant === "glitch" && "animate-glitch shadow-neon hover:animate-rgb-shift",
          className
        )}
        variant={mapped}
        disabled={disabled || loading}
        {...props}
      >
        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
        {children}
      </Button>
    );
  }
);
CyberButton.displayName = "CyberButton";
