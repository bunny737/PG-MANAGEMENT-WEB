"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ApiError, resendVerification } from "@/lib/api";

/** Requests a new verification link and maps failures to a message. Branches on status only:
 * 429 is throttling, status 0 is the network, anything else shows the backend's (already
 * translated) field message or a generic one. */
export function useVerificationResend() {
  const t = useTranslations("auth");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (email: string): Promise<boolean> => {
    setSending(true);
    setError(null);
    try {
      await resendVerification(email);
      return true;
    } catch (err) {
      if (!(err instanceof ApiError) || err.status === 0) setError(t("login.errServerUnreachable"));
      else if (err.status === 429) setError(t("checkEmail.errThrottled"));
      else setError(err.fieldError("email") ?? t("checkEmail.errSendFailed"));
      return false;
    } finally {
      setSending(false);
    }
  };

  return { send, sending, error };
}
