import { cache } from "react";
import { z } from "zod";
import { fetchPublic } from "./publicFetch";

// Mirrors GET /api/v1/support/. A channel the Super Admin hasn't configured is null.
export const supportSchema = z.object({
  email: z.string().nullable(),
  phone: z.string().nullable(),
  whatsapp: z.string().nullable(),
  whatsapp_url: z.string().nullable(),
  website: z.string().nullable(),
  hours: z.string().nullable(),
});

export type SupportContacts = z.infer<typeof supportSchema>;

/** Contacts, or null when the API can't be reached and nothing was ever cached. */
export const getSupportContacts = cache(async (): Promise<SupportContacts | null> => {
  const result = await fetchPublic("/api/v1/support/", supportSchema);
  return result.status === "unavailable" ? null : result.data;
});

/** True when there is anything at all to show on the contact page: any channel,
 * the website, the support hours, or the company address (which comes from site
 * config, not the support API, so it can exist while every channel is unset). */
export function hasContactInfo(contacts: SupportContacts | null, address = ""): boolean {
  return Boolean(
    address.trim() ||
      (contacts &&
        (contacts.email || contacts.phone || contacts.whatsapp_url || contacts.website || contacts.hours))
  );
}

/** `tel:` target from the stored digits-with-country-code form. */
export function telHref(digits: string): string {
  return `tel:+${digits.replace(/\D/g, "")}`;
}

/** "919876543210" -> "+91 98765 43210" for display (best effort for +91, raw otherwise). */
export function formatPhone(digits: string): string {
  const clean = digits.replace(/\D/g, "");
  if (clean.length === 12 && clean.startsWith("91")) {
    return `+91 ${clean.slice(2, 7)} ${clean.slice(7)}`;
  }
  return `+${clean}`;
}
