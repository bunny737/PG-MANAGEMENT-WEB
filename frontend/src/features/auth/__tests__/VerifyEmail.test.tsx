/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";

const api = vi.hoisted(() => ({ verifyEmail: vi.fn(), resendVerification: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

import { ApiError } from "@/lib/api";
import { VerifyEmail, readVerificationToken } from "../VerifyEmail";

function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  render(
    <StrictMode>
      <NextIntlClientProvider locale="en" messages={{ auth }}>
        <VerifyEmail />
      </NextIntlClientProvider>
    </StrictMode>
  );
}

async function settle() {
  await act(async () => {});
}

describe("VerifyEmail", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  test("verifies once (even under Strict Mode) and strips the token from the URL", async () => {
    api.verifyEmail.mockResolvedValue(undefined);
    renderAt("/verify-email#token=abc.def:ghi");
    await settle();

    expect(api.verifyEmail).toHaveBeenCalledTimes(1);
    expect(api.verifyEmail).toHaveBeenCalledWith("abc.def:ghi");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname + window.location.search).toBe("/verify-email");
    expect(screen.getByText(auth.verifyEmail.successTitle)).toBeTruthy();
    // The link never signs anyone in: the only way on is the sign-in page.
    expect(screen.getByRole("link", { name: auth.verifyEmail.signIn }).getAttribute("href")).toBe("/login");
  });

  test("while the request is in flight, Strict Mode's second effect run doesn't flip to 'no link'", async () => {
    api.verifyEmail.mockReturnValue(new Promise(() => {})); // never settles
    renderAt("/verify-email#token=pending");
    await settle();
    expect(screen.getByRole("status").textContent).toContain(auth.verifyEmail.verifying);
    expect(screen.queryByText(auth.verifyEmail.noTokenTitle)).toBeNull();
  });

  test("accepts a ?token= query as a fallback and strips it too", async () => {
    api.verifyEmail.mockResolvedValue(undefined);
    renderAt("/verify-email?token=query-token");
    await settle();
    expect(api.verifyEmail).toHaveBeenCalledWith("query-token");
    expect(window.location.search).toBe("");
  });

  test("any 400 means invalid or expired, and offers a new link", async () => {
    api.verifyEmail.mockRejectedValue(new ApiError(400, { token: ["whatever text"], code: "INVALID" }));
    renderAt("/verify-email#token=old");
    await settle();
    expect(screen.getByText(auth.verifyEmail.invalidTitle)).toBeTruthy();
    expect(screen.getByRole("button", { name: auth.checkEmail.sendLink })).toBeTruthy();
  });

  test("no token: nothing is posted and a new link is offered", async () => {
    renderAt("/verify-email");
    await settle();
    expect(api.verifyEmail).not.toHaveBeenCalled();
    expect(screen.getByText(auth.verifyEmail.noTokenTitle)).toBeTruthy();
  });

  test("a network failure can be retried with the same token", async () => {
    api.verifyEmail.mockRejectedValueOnce(new ApiError(0, { detail: "offline" })).mockResolvedValueOnce(undefined);
    renderAt("/verify-email#token=t1");
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errServerUnreachable);

    await act(async () => {
      screen.getByRole("button", { name: auth.verifyEmail.retry }).click();
    });
    expect(api.verifyEmail).toHaveBeenLastCalledWith("t1");
    expect(screen.getByText(auth.verifyEmail.successTitle)).toBeTruthy();
  });

  test("readVerificationToken prefers the fragment", () => {
    expect(readVerificationToken({ hash: "#token=a", search: "?token=b" })).toBe("a");
    expect(readVerificationToken({ hash: "", search: "?token=b" })).toBe("b");
    expect(readVerificationToken({ hash: "", search: "" })).toBeNull();
  });
});
