import * as React from "react";

import { Input, type InputProps } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type CyberInputProps = InputProps & {
  prompt?: boolean;
};

export const CyberInput = React.forwardRef<HTMLInputElement, CyberInputProps>(
  ({ className, prompt = true, ...props }, ref) => (
    <div className="relative w-full">
      {prompt && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-primary">&gt;</span>}
      <Input ref={ref} className={cn(prompt && "pl-7", className)} {...props} />
    </div>
  )
);
CyberInput.displayName = "CyberInput";
