import { NextRequest, NextResponse } from "next/server";
import { DEV_AUTH_COOKIE, localAdminRequestAllowed } from "@/app/lib/auth-config";

export async function POST(request: NextRequest) {
  if (!localAdminRequestAllowed(request.headers)) return NextResponse.json({ detail: "Cloud logout is managed by the identity provider" }, { status: 400 });
  const response = new NextResponse(null, { status: 303, headers: { Location: "/login" } });
  response.cookies.set(DEV_AUTH_COOKIE, "", { httpOnly: true, maxAge: 0, path: "/", sameSite: "strict" });
  return response;
}
