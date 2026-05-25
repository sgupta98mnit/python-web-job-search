import type { NextConfig } from "next";

const basePath = normalizeBasePath(process.env.NEXT_PUBLIC_BASE_PATH);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: process.cwd(),
  ...(basePath ? { basePath } : {}),
};

function normalizeBasePath(value: string | undefined) {
  if (!value) {
    return "";
  }
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed || trimmed === "/") {
    return "";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

export default nextConfig;
