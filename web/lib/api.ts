import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/errors";

const API_BASE =
  process.env.API_BASE_INTERNAL ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000";

type FetchOptions = RequestInit & {
  cookie?: string;
};

export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (options.cookie) {
    headers.set("Cookie", options.cookie);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const message = await errorMessage(response);
    if (response.status === 401) {
      redirect("/login");
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export async function serverCookieHeader() {
  const cookieStore = await cookies();
  return cookieStore.toString();
}

export function apiBase() {
  return API_BASE;
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
