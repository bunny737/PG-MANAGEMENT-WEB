import type { NextRequest } from "next/server";
import { handleLogin } from "@/lib/server/loginHandler";

export const dynamic = "force-dynamic";

export function POST(request: NextRequest) {
  return handleLogin(request, "/api/v1/auth/otp/email/verify/");
}
