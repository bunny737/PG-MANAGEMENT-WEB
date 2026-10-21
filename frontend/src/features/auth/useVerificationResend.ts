"use client";

import { resendVerification } from "@/lib/api";
import { useEmailRequest } from "./useEmailRequest";

/** Requests a new verification link. */
export function useVerificationResend() {
  return useEmailRequest(resendVerification);
}
