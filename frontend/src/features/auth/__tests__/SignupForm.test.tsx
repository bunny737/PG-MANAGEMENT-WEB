/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";
import common from "@/messages/en/common.json";

const api = vi.hoisted(() => ({ signup: vi.fn(), resendVerification: vi.fn() }));

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
import { SignupForm } from "../SignupForm";

function renderForm() {
  render(
    <NextIntlClientProvider locale="en" messages={{ auth, common }}>
      <SignupForm />
    </NextIntlClientProvider>
  );
}

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;

function fillValid() {
  fireEvent.change(field(auth.signup.businessNameLabel), { target: { value: "Sunrise PG" } });
  fireEvent.change(field(auth.signup.firstNameLabel), { target: { value: "Ramesh" } });
  fireEvent.change(field(auth.login.emailLabel), { target: { value: " ramesh@example.com " } });
  fireEvent.change(field(auth.signup.phoneLabel), { target: { value: "+91 98765 43210" } });
  fireEvent.change(field(auth.login.passwordLabel), { target: { value: "Vintage-Kite-77" } });
  fireEvent.change(field(auth.signup.confirmPasswordLabel), { target: { value: "Vintage-Kite-77" } });
}

async function submit() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: auth.signup.submit }));
  });
}

describe("SignupForm", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.signup.mockResolvedValue(undefined);
    api.resendVerification.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("validates on the client before calling the API", async () => {
    renderForm();
    fireEvent.change(field(auth.login.passwordLabel), { target: { value: "one" } });
    fireEvent.change(field(auth.signup.confirmPasswordLabel), { target: { value: "two" } });
    fireEvent.change(field(auth.signup.phoneLabel), { target: { value: "12345" } });
    await submit();
    expect(api.signup).not.toHaveBeenCalled();
    for (const message of [
      auth.signup.errBusinessNameRequired,
      auth.signup.errFirstNameRequired,
      auth.login.errEmailRequired,
      auth.login.errPhoneInvalid,
      auth.signup.errPasswordMismatch,
    ]) {
      expect(screen.getByText(message)).toBeTruthy();
    }
  });

  test("sends a normalized payload and shows the check-email panel", async () => {
    renderForm();
    fillValid();
    await submit();
    expect(api.signup).toHaveBeenCalledWith({
      business_name: "Sunrise PG",
      first_name: "Ramesh",
      last_name: "",
      email: "ramesh@example.com",
      phone: "9876543210",
      password: "Vintage-Kite-77",
      language_code: "en",
    });
    expect(screen.getByText(auth.checkEmail.title)).toBeTruthy();
    expect(screen.getByText(/ramesh@example.com/)).toBeTruthy();
  });

  test("shows the backend's translated field messages under the right fields", async () => {
    api.signup.mockRejectedValue(
      new ApiError(400, {
        email: ["An account with this email already exists."],
        password: ["This password is too common."],
        code: "INVALID",
      })
    );
    renderForm();
    fillValid();
    await submit();
    expect(screen.getByText("An account with this email already exists.")).toBeTruthy();
    expect(screen.getByText("This password is too common.")).toBeTruthy();
    expect(screen.queryByText(auth.checkEmail.title)).toBeNull();
  });

  test("a network failure gets the unreachable message", async () => {
    api.signup.mockRejectedValue(new ApiError(0, { detail: "offline" }));
    renderForm();
    fillValid();
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errServerUnreachable);
  });

  test("resend on the check-email panel waits out the cooldown", async () => {
    vi.useFakeTimers();
    renderForm();
    fillValid();
    await submit();
    expect(screen.queryByRole("button", { name: auth.checkEmail.resend })).toBeNull();
    expect(screen.getByText(`resend in ${RESEND_COOLDOWN_S}s`)).toBeTruthy();

    for (let i = 0; i < RESEND_COOLDOWN_S; i++) {
      act(() => {
        vi.advanceTimersByTime(1000);
      });
    }
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: auth.checkEmail.resend }));
    });
    expect(api.resendVerification).toHaveBeenCalledWith("ramesh@example.com");
    expect(screen.getByText(`resend in ${RESEND_COOLDOWN_S}s`)).toBeTruthy();
  });

  test("renders without any SIGNUP_ENABLED flag (discovery-only)", () => {
    delete process.env.SIGNUP_ENABLED;
    renderForm();
    expect(screen.getByRole("button", { name: auth.signup.submit })).toBeTruthy();
  });
});
