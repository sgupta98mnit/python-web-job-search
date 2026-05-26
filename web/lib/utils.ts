import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Display in user's timezone (EST/EDT). Server-side renders would otherwise
// format in UTC (the VPS clock), producing times 4-5 hours off.
const DISPLAY_TZ = "America/New_York";

export function formatDate(value: string | null) {
  if (!value) {
    return "not set";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: DISPLAY_TZ,
  }).format(new Date(value));
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: DISPLAY_TZ,
  }).format(new Date(value));
}
