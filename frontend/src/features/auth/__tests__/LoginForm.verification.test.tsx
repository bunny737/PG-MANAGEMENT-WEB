/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";
import common from "@/messages/en/common.json";

const api = vi.hoisted(() => ({ login: vi.fn(), resendVerification: vi.fn(), clearSession: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

import { ApiError } from "@/lib/api";
import { LoginForm } from "../LoginForm";

const NOT_VERIFIED_TEXT = "Verify your email address to log in.";

function renderForm(signupEnabled = false) {
  render(
    <NextIntlClientProvider locale="en" messages={{ auth, common }}>
      <LoginForm signupEnabled={signupEnabled} />
    </NextIntlClientProvider>
  );
}

async function passwordLogin() {
  fireEvent.click(screen.getByText(auth.login.ownerOptionTitle));
  fireEvent.change(screen.getByLabelText(auth.login.emailLabel), { target: { value: "owner@example.com" } });
  fireEvent.change(screen.getByLabelText(auth.login.passwordLabel), { target: { value: "Vintage-Kite-77" } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: auth.login.submitPassword }));
  });
}

describe("LoginForm email verification", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.resendVerification.mockResolvedValue(undefined);
  });

  test("EMAIL_NOT_VERIFIED offers a resend, and 'We sent…' appears only after it succeeds", async () => {
    api.login.mockRejectedValue(new ApiError(401, { detail: NOT_VERIFIED_TEXT, code: "EMAIL_NOT_VERIFIED" }));
    renderForm();
    await passwordLogin();

    expect(screen.getByText(NOT_VERIFIED_TEXT)).toBeTruthy();
    expect(screen.queryByText(auth.checkEmail.title)).toBeNull(); // nothing claimed as sent yet

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: auth.checkEmail.sendLink }));
    });
    expect(api.resendVerification).toHaveBeenCalledWith("owner@example.com");
    expect(screen.getByText(auth.checkEmail.title)).toBeTruthy();
  });

  test("a failed resend does not claim the email was sent", async () => {
    api.login.mockRejectedValue(new ApiError(401, { detail: NOT_VERIFIED_TEXT, code: "EMAIL_NOT_VERIFIED" }));
    api.resendVerification.mockRejectedValue(new ApiError(429, { detail: "throttled" }));
    renderForm();
    await passwordLogin();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: auth.checkEmail.sendLink }));
    });
    expect(screen.queryByText(auth.checkEmail.title)).toBeNull();
    expect(screen.getByText(auth.checkEmail.errThrottled)).toBeTruthy();
  });

  test("editing the email withdraws the resend offer, so it can't go to the old address", async () => {
    api.login.mockRejectedValue(new ApiError(401, { detail: NOT_VERIFIED_TEXT, code: "EMAIL_NOT_VERIFIED" }));
    renderForm();
    await passwordLogin();
    expect(screen.getByRole("button", { name: auth.checkEmail.sendLink })).toBeTruthy();

    fireEvent.change(screen.getByLabelText(auth.login.emailLabel), { target: { value: "other@example.com" } });
    expect(screen.queryByRole("button", { name: auth.checkEmail.sendLink })).toBeNull();
    expect(api.resendVerification).not.toHaveBeenCalled();
  });

  test("branches on the code, not the text: same message with another code offers no resend", async () => {
    api.login.mockRejectedValue(new ApiError(401, { detail: NOT_VERIFIED_TEXT, code: "NO_ACTIVE_ACCOUNT" }));
    renderForm();
    await passwordLogin();
    expect(screen.getByText(NOT_VERIFIED_TEXT)).toBeTruthy();
    expect(screen.queryByRole("button", { name: auth.checkEmail.sendLink })).toBeNull();
  });

  test("the signup link shows only when signup is enabled", () => {
    renderForm(false);
    expect(screen.queryByRole("link", { name: auth.login.signupLink })).toBeNull();
  });

  test("the signup link points at /signup when enabled", () => {
    renderForm(true);
    expect(screen.getByRole("link", { name: auth.login.signupLink }).getAttribute("href")).toBe("/signup");
  });
});
