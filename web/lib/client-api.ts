import { ApiError } from "@/lib/errors";

const CONFIGURED_API_BASE = process.env.NEXT_PUBLIC_API_BASE?.trim() ?? "";

export async function clientApiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${clientApiBase()}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return (await response.json()) as T;
}

export function clientApiBase() {
  if (!CONFIGURED_API_BASE) {
    return "";
  }
  if (typeof window === "undefined") {
    return CONFIGURED_API_BASE;
  }

  try {
    const configured = new URL(CONFIGURED_API_BASE);
    const browserHost = window.location.hostname;
    const configuredHost = configured.hostname;
    if (isLoopbackHost(configuredHost) && !isLoopbackHost(browserHost)) {
      return "";
    }
  } catch {
    return CONFIGURED_API_BASE;
  }

  return CONFIGURED_API_BASE;
}

function isLoopbackHost(hostname: string) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

async function errorMessage(response: Response) {
  const text = await response.text();
  if (!text) {
    return response.statusText;
  }
  try {
    const parsed = JSON.parse(text) as { detail?: string };
    return parsed.detail ?? text;
  } catch {
    return text;
  }
}
