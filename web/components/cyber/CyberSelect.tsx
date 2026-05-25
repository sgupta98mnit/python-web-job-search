"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type CyberSelectProps = {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly string[];
  label?: string;
};

export function CyberSelect({ value, onValueChange, options, label }: CyberSelectProps) {
  return (
    <div className="space-y-2">
      {label && <label className="font-label text-xs uppercase text-muted-foreground">{label}</label>}
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
