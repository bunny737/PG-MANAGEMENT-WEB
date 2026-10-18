import { describe, expect, it } from "vitest";
import { resolvePrimaryCta } from "../cta";
import type { SupportContacts } from "../data/support";

const NONE: SupportContacts = {
  email: null,
  phone: null,
  whatsapp: null,
  whatsapp_url: null,
  website: null,
  hours: null,
};
const base = { message: "Hi PGLive & team", subject: "Early access" };

describe("resolvePrimaryCta", () => {
  it("goes to signup once it exists, regardless of contacts", () => {
    const cta = resolvePrimaryCta({ ...base, signupEnabled: true, support: NONE });
    expect(cta).toEqual({ kind: "signup", href: "/signup", external: false });
  });

  it("prefers WhatsApp with an encoded pre-filled message", () => {
    const cta = resolvePrimaryCta({
      ...base,
      signupEnabled: false,
      support: { ...NONE, email: "help@pglive.in", whatsapp: "919876543210", whatsapp_url: "https://wa.me/919876543210" },
    });
    expect(cta.kind).toBe("whatsapp");
    expect(cta.external).toBe(true);
    expect(cta.href).toBe("https://wa.me/919876543210?text=Hi%20PGLive%20%26%20team");
  });

  it("falls back to email, then the contact page", () => {
    const email = resolvePrimaryCta({ ...base, signupEnabled: false, support: { ...NONE, email: "help@pglive.in" } });
    expect(email.kind).toBe("email");
    expect(email.href).toBe("mailto:help@pglive.in?subject=Early%20access&body=Hi%20PGLive%20%26%20team");

    const none = resolvePrimaryCta({ ...base, signupEnabled: false, support: null });
    expect(none).toEqual({ kind: "contact", href: "/contact", external: false });
  });

  it("never sends a prospect to /login", () => {
    for (const support of [null, NONE, { ...NONE, email: "a@b.in" }]) {
      for (const signupEnabled of [true, false]) {
        expect(resolvePrimaryCta({ ...base, signupEnabled, support }).href).not.toContain("/login");
      }
    }
  });
});
