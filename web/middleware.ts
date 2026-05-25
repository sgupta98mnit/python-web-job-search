import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/", "/login"];
const BASE_PATH = normalizeBasePath(process.env.NEXT_PUBLIC_BASE_PATH);

export function middleware(request: NextRequest) {
  const pathname = stripBasePath(request.nextUrl.pathname);
  const authed = Boolean(request.cookies.get("app_session")?.value);

  if (
    pathname === "/favicon.ico" ||
    pathname === "/api" ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/")
  ) {
    return NextResponse.next();
  }

  if (!authed && !PUBLIC_PATHS.includes(pathname)) {
    const loginUrl = new URL(`${BASE_PATH}/login`, request.url);
    loginUrl.searchParams.set("next", `${BASE_PATH}${pathname}`);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api).*)"],
};

function stripBasePath(pathname: string) {
  if (!BASE_PATH) {
    return pathname;
  }
  if (pathname === BASE_PATH) {
    return "/";
  }
  if (pathname.startsWith(`${BASE_PATH}/`)) {
    return pathname.slice(BASE_PATH.length);
  }
  return pathname;
}

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
