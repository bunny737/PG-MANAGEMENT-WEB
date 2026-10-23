/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { StrictMode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";

const api = vi.hoisted(() => ({ confirmPasswordReset: vi.fn() }));

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
import { ResetPasswordForm, readResetLink } from "../ResetPasswordForm";

const NEW_PASSWORD = "Copper-Meadow-42";

async function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  render(
    <StrictMode>
      <NextIntlClientProvider locale="en" messages={{ auth }}>
        <ResetPasswordForm />
      </NextIntlClientProvider>
    </StrictMode>
  );
  await act(async () => {});
}

async function submit(password = NEW_PASSWORD, confirm = password) {
  fireEvent.change(screen.getByLabelText(auth.resetPassword.newPasswordLabel), { target: { value: password } });
  fireEvent.change(screen.getByLabelText(auth.signup.confirmPasswordLabel), { target: { value: confirm } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /Update password|Set password/ }));
  });
}

describe("ResetPasswordForm", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.confirmPasswordReset.mockResolvedValue(undefined);
  });

  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  test("readResetLink reads uid, token and the invite flag from the fragment only", () => {
    expect(readResetLink({ hash: "#uid=MQ&token=abc-123" })).toEqual({ uid: "MQ", token: "abc-123", invite: false });
    expect(readResetLink({ hash: "#uid=MQ&token=abc-123&invite=1" })).toEqual({
      uid: "MQ",
      token: "abc-123",
      invite: true,
    });
    expect(readResetLink({ hash: "#uid=MQ" })).toBeNull();
    expect(readResetLink({ hash: "" })).toBeNull();
  });

  test("strips the link from the address bar (even under Strict Mode) and keeps it for the submit", async () => {
    await renderAt("/reset-password#uid=MQ&token=abc-123");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/reset-password");
    expect(screen.getByRole("heading", { name: auth.resetPassword.title })).toBeTruthy();

    await submit();
    expect(api.confirmPasswordReset).toHaveBeenCalledTimes(1);
    expect(api.confirmPasswordReset).toHaveBeenCalledWith({ uid: "MQ", token: "abc-123", new_password: NEW_PASSWORD });
  });

  test("success shows a sign-in link and never signs anyone in", async () => {
    await renderAt("/reset-password#uid=MQ&token=t");
    await submit();
    expect(screen.getByText(auth.resetPassword.successTitle)).toBeTruthy();
    expect(screen.getByRole("link", { name: auth.resetPassword.signIn }).getAttribute("href")).toBe("/login");
  });

  test("an invite uses the 'set your password' wording and lands on the staff sign-in", async () => {
    await renderAt("/reset-password#uid=MQ&token=t&invite=1");
    expect(screen.getByRole("heading", { name: auth.resetPassword.inviteTitle })).toBeTruthy();
    await submit();
    expect(screen.getByText(auth.resetPassword.inviteSuccessBody)).toBeTruthy();
    expect(screen.getByRole("link", { name: auth.resetPassword.signIn }).getAttribute("href")).toBe("/login?view=staff");
  });

  test("validates length and confirmation before calling the API", async () => {
    await renderAt("/reset-password#uid=MQ&token=t");
    await submit("short");
    expect(screen.getByText(auth.login.errPasswordLength)).toBeTruthy();
    await submit(NEW_PASSWORD, "something-else-entirely");
    expect(screen.getByText(auth.signup.errPasswordMismatch)).toBeTruthy();
    expect(api.confirmPasswordReset).not.toHaveBeenCalled();
  });

  test("a dead link (400 on the token) offers a new one", async () => {
    api.confirmPasswordReset.mockRejectedValue(
      new ApiError(400, { token: ["This reset link is invalid or has expired."], code: "INVALID_TOKEN" })
    );
    await renderAt("/reset-password#uid=MQ&token=used");
    await submit();
    expect(screen.getByText(auth.resetPassword.invalidTitle)).toBeTruthy();
    expect(screen.getByRole("link", { name: auth.resetPassword.requestNew }).getAttribute("href")).toBe(
      "/forgot-password"
    );
  });

  test("the backend's password-strength message is shown under the field and the form stays usable", async () => {
    api.confirmPasswordReset.mockRejectedValue(
      new ApiError(400, { new_password: ["This password is too common."], code: "INVALID" })
    );
    await renderAt("/reset-password#uid=MQ&token=t");
    await submit("password1234");
    expect(screen.getByText("This password is too common.")).toBeTruthy();
    expect(screen.queryByText(auth.resetPassword.invalidTitle)).toBeNull();
  });

  test("throttling and network failures show a message without killing the link", async () => {
    api.confirmPasswordReset.mockRejectedValueOnce(new ApiError(429, { detail: "throttled" }));
    await renderAt("/reset-password#uid=MQ&token=t");
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(auth.checkEmail.errThrottled);

    api.confirmPasswordReset.mockRejectedValueOnce(new ApiError(0, { detail: "offline" }));
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errServerUnreachable);
    expect(screen.queryByText(auth.resetPassword.invalidTitle)).toBeNull();
  });

  test("without a link it posts nothing and offers a new one", async () => {
    await renderAt("/reset-password");
    expect(screen.getByText(auth.resetPassword.noLinkTitle)).toBeTruthy();
    expect(screen.getByRole("link", { name: auth.resetPassword.requestNew }).getAttribute("href")).toBe(
      "/forgot-password"
    );
    expect(api.confirmPasswordReset).not.toHaveBeenCalled();
  });
});
