/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";

const api = vi.hoisted(() => ({ requestPasswordReset: vi.fn(), resendVerification: vi.fn() }));

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
import { RESEND_COOLDOWN_S } from "../EmailCodeLogin";
import { ForgotPasswordForm } from "../ForgotPasswordForm";

function renderForm() {
  render(
    <NextIntlClientProvider locale="en" messages={{ auth }}>
      <ForgotPasswordForm />
    </NextIntlClientProvider>
  );
}

async function submit(email: string) {
  fireEvent.change(screen.getByLabelText(auth.login.emailLabel), { target: { value: email } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: auth.forgotPassword.submit }));
  });
}

describe("ForgotPasswordForm", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.requestPasswordReset.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("links back to sign-in", () => {
    renderForm();
    expect(screen.getByRole("link", { name: auth.forgotPassword.backToLogin }).getAttribute("href")).toBe("/login");
  });

  test("validates the address before calling the API", async () => {
    renderForm();
    await submit("");
    expect(screen.getByText(auth.login.errEmailRequired)).toBeTruthy();
    await submit("not-an-email");
    expect(screen.getByText(auth.login.errEmailInvalid)).toBeTruthy();
    expect(api.requestPasswordReset).not.toHaveBeenCalled();
  });

  test("really calls the API, then says a link was sent without claiming the address is registered", async () => {
    renderForm();
    await submit("  owner@example.com ");
    expect(api.requestPasswordReset).toHaveBeenCalledWith("owner@example.com");
    expect(screen.getByText(auth.checkEmail.title)).toBeTruthy();
    expect(screen.getByText(/If an account exists for owner@example.com/)).toBeTruthy();
  });

  test("a failed request does not claim anything was sent", async () => {
    api.requestPasswordReset.mockRejectedValue(new ApiError(429, { detail: "throttled" }));
    renderForm();
    await submit("owner@example.com");
    expect(screen.queryByText(auth.checkEmail.title)).toBeNull();
    expect(screen.getByRole("alert").textContent).toBe(auth.checkEmail.errThrottled);
  });

  test("a network failure gets the unreachable message", async () => {
    api.requestPasswordReset.mockRejectedValue(new ApiError(0, { detail: "offline" }));
    renderForm();
    await submit("owner@example.com");
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errServerUnreachable);
  });

  test("the resend asks for another reset link, never a verification link", async () => {
    vi.useFakeTimers();
    renderForm();
    await submit("owner@example.com");
    expect(screen.getByText(`resend in ${RESEND_COOLDOWN_S}s`)).toBeTruthy();

    for (let i = 0; i < RESEND_COOLDOWN_S; i++) {
      act(() => {
        vi.advanceTimersByTime(1000);
      });
    }
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: auth.checkEmail.resend }));
    });
    expect(api.requestPasswordReset).toHaveBeenCalledTimes(2);
    expect(api.requestPasswordReset).toHaveBeenLastCalledWith("owner@example.com");
    expect(api.resendVerification).not.toHaveBeenCalled();
  });
});
