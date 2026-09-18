import { NextRequest, NextResponse } from "next/server";
import { authMode, DEV_AUTH_COOKIE } from "@/app/lib/auth-config";

export async function POST(_request: NextRequest) {
  if (authMode() !== "dev") return NextResponse.json({ detail: "Cloud logout is managed by the identity provider" }, { status: 400 });
  const response = new NextResponse(null, { status: 303, headers: { Location: "/login" } });
  response.cookies.set(DEV_AUTH_COOKIE, "", { httpOnly: true, maxAge: 0, path: "/", sameSite: "strict" });
  return response;
}
