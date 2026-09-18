import { NextRequest, NextResponse } from "next/server";
import { authMode, DEV_AUTH_COOKIE, devAuthAllowed, safeReturnTo } from "@/app/lib/auth-config";

export async function POST(request: NextRequest) {
  if (authMode() !== "dev" || !devAuthAllowed()) {
    return NextResponse.json({ detail: "Development login is not available" }, { status: 403 });
  }
  const form = await request.formData();
  const response = new NextResponse(null, {
    status: 303,
    headers: { Location: safeReturnTo(String(form.get("returnTo") ?? "/")) },
  });
  response.cookies.set(DEV_AUTH_COOKIE, "authenticated", {
    httpOnly: true,
    maxAge: 8 * 60 * 60,
    path: "/",
    sameSite: "strict",
    secure: request.nextUrl.protocol === "https:",
  });
  return response;
}
