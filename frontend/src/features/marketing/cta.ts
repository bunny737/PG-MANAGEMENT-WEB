import type { SupportContacts } from "./data/support";

export type PrimaryCtaKind = "signup" | "whatsapp" | "email" | "contact";

export interface PrimaryCta {
  kind: PrimaryCtaKind;
  href: string;
  /** Opens outside the app (new tab / mail client). */
  external: boolean;
}

interface CtaInput {
  signupEnabled: boolean;
  support: SupportContacts | null;
  /** Pre-filled message for WhatsApp / email body (already translated). */
  message: string;
  /** Email subject (already translated). */
  subject: string;
}

/** Where the main call-to-action goes. Never `/login`: login only serves existing
 * accounts, so sending a prospect there is a dead end (frontend-plan FE-01).
 *  - signup enabled        -> the real signup flow
 *  - otherwise (early access) -> WhatsApp, else email, else the contact page. */
export function resolvePrimaryCta({ signupEnabled, support, message, subject }: CtaInput): PrimaryCta {
  if (signupEnabled) return { kind: "signup", href: "/signup", external: false };
  if (support?.whatsapp_url) {
    return {
      kind: "whatsapp",
      href: `${support.whatsapp_url}?text=${encodeURIComponent(message)}`,
      external: true,
    };
  }
  if (support?.email) {
    const query = `subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(message)}`;
    return { kind: "email", href: `mailto:${support.email}?${query}`, external: true };
  }
  return { kind: "contact", href: "/contact", external: false };
}
