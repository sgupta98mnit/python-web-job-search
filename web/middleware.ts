import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/", "/login"];

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const authed = Boolean(request.cookies.get("app_session")?.value);

  if (!authed && !PUBLIC_PATHS.includes(pathname)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api).*)"],
};
