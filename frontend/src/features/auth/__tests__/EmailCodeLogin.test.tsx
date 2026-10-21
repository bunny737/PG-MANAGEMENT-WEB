/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";

const api = vi.hoisted(() => ({
  requestEmailOtp: vi.fn(),
  loginEmailOtp: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { EmailCodeLogin, RESEND_COOLDOWN_S, type CodeRequest } from "../EmailCodeLogin";

const onSuccess = vi.fn();
const onUsePassword = vi.fn();

/** Stands in for LoginForm: owns the last request and unmounts the code form for "use password". */
function Harness({ expectedRoles }: { expectedRoles: string[] }) {
  const [lastRequest, setLastRequest] = useState<CodeRequest | null>(null);
  const [showCodeForm, setShowCodeForm] = useState(true);
  if (!showCodeForm) {
    return <button onClick={() => setShowCodeForm(true)}>back-to-code</button>;
  }
  return (
    <EmailCodeLogin
      expectedRoles={expectedRoles}
      initialEmail=" owner@example.com "
      lastRequest={lastRequest}
      onCodeRequested={setLastRequest}
      roleMismatchMessage="Not an owner"
      onSuccess={onSuccess}
      onUsePassword={() => {
        onUsePassword();
        setShowCodeForm(false);
      }}
    />
  );
}

function renderLogin(expectedRoles = ["owner"]) {
  render(
    <NextIntlClientProvider locale="en" messages={{ auth }}>
      <Harness expectedRoles={expectedRoles} />
    </NextIntlClientProvider>
  );
}

async function sendCode() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: auth.login.sendOtp }));
  });
}

async function submitCode(code: string) {
  fireEvent.change(screen.getByLabelText(auth.login.otpCodeLabel), { target: { value: code } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: auth.login.verifySubmit }));
  });
}

describe("EmailCodeLogin", () => {
  beforeEach(() => {
    for (const fn of [...Object.values(api), onSuccess, onUsePassword]) fn.mockReset();
    api.requestEmailOtp.mockResolvedValue(undefined);
    api.clearSession.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("requests a code, then signs in with it", async () => {
    const me = { id: "u1", role: "owner", permissions: ["view_dashboard"] };
    api.loginEmailOtp.mockResolvedValue(me);
    renderLogin();

    await sendCode();
    expect(api.requestEmailOtp).toHaveBeenCalledWith("owner@example.com");
    expect(screen.getByText(/If owner@example.com can sign in with a code/)).toBeTruthy();
    expect(screen.getByText(/only the most recent code works/)).toBeTruthy();

    await submitCode("123456");
    expect(api.loginEmailOtp).toHaveBeenCalledWith("owner@example.com", "123456");
    expect(onSuccess).toHaveBeenCalledWith(me);
    expect(api.clearSession).not.toHaveBeenCalled();
  });

  test("a signed-in account of the wrong role is signed straight back out", async () => {
    api.loginEmailOtp.mockResolvedValue({ id: "u2", role: "manager", permissions: [] });
    renderLogin(["owner"]);
    await sendCode();
    await submitCode("123456");

    expect(api.clearSession).toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("Not an owner");
  });

  test("an incomplete code is rejected locally", async () => {
    renderLogin();
    await sendCode();
    await submitCode("12ab3");
    expect(api.loginEmailOtp).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errOtpCodeInvalid);
  });

  test("a wrong or expired code shows the server's message", async () => {
    api.loginEmailOtp.mockRejectedValue(
      new ApiError(401, { code: "INVALID_OTP", detail: "The code is incorrect or has expired." })
    );
    renderLogin();
    await sendCode();
    await submitCode("000000");
    expect(screen.getByRole("alert").textContent).toBe("The code is incorrect or has expired.");
    expect(onSuccess).not.toHaveBeenCalled();
  });

  test("throttling and network failures get their own messages", async () => {
    api.requestEmailOtp.mockRejectedValueOnce(new ApiError(429, { detail: "Request was throttled." }));
    renderLogin();
    await sendCode();
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errTooManyRequests);

    api.requestEmailOtp.mockRejectedValueOnce(new ApiError(0, { detail: "offline" }));
    await sendCode();
    expect(screen.getByRole("alert").textContent).toBe(auth.login.errServerUnreachable);
  });

  test("resend is offered only after the cooldown", async () => {
    vi.useFakeTimers();
    renderLogin();
    await sendCode();
    expect(screen.queryByRole("button", { name: auth.login.resendCode })).toBeNull();
    expect(screen.getByText(`Resend OTP in ${RESEND_COOLDOWN_S}s`)).toBeTruthy();

    for (let i = 0; i < RESEND_COOLDOWN_S; i++) {
      act(() => {
        vi.advanceTimersByTime(1000);
      });
    }
    const resend = screen.getByRole("button", { name: auth.login.resendCode });
    await act(async () => {
      fireEvent.click(resend);
    });
    expect(api.requestEmailOtp).toHaveBeenCalledTimes(2);
    expect(screen.getByText(`Resend OTP in ${RESEND_COOLDOWN_S}s`)).toBeTruthy();
  });

  test("change email cannot bypass the cooldown for the same address", async () => {
    renderLogin();
    await sendCode();
    fireEvent.click(screen.getByRole("button", { name: auth.login.changeEmail }));
    await sendCode(); // same address, still cooling down
    expect(api.requestEmailOtp).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(auth.login.otpCodeLabel)).toBeTruthy();
    expect(screen.getByText(/^Resend OTP in \d+s$/)).toBeTruthy();

    // A different address is a new request.
    fireEvent.click(screen.getByRole("button", { name: auth.login.changeEmail }));
    fireEvent.change(screen.getByLabelText(auth.login.emailLabel), { target: { value: "other@example.com" } });
    await sendCode();
    expect(api.requestEmailOtp).toHaveBeenCalledTimes(2);
    expect(api.requestEmailOtp).toHaveBeenLastCalledWith("other@example.com");
  });

  test("leaving for the password form and coming back keeps the cooldown", async () => {
    renderLogin();
    await sendCode();
    fireEvent.click(screen.getByRole("button", { name: auth.login.usePassword }));
    fireEvent.click(screen.getByRole("button", { name: "back-to-code" }));
    await sendCode(); // remounted, same address remembered by the parent
    expect(api.requestEmailOtp).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/^Resend OTP in \d+s$/)).toBeTruthy();
  });

  test("the same address can be re-sent once the cooldown has passed", async () => {
    vi.useFakeTimers();
    renderLogin();
    await sendCode();
    fireEvent.click(screen.getByRole("button", { name: auth.login.changeEmail }));
    act(() => {
      vi.advanceTimersByTime(RESEND_COOLDOWN_S * 1000);
    });
    await sendCode();
    expect(api.requestEmailOtp).toHaveBeenCalledTimes(2);
  });

  test("change email and use password go back", async () => {
    renderLogin();
    await sendCode();
    fireEvent.click(screen.getByRole("button", { name: auth.login.changeEmail }));
    await waitFor(() => expect(screen.getByRole("button", { name: auth.login.sendOtp })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: auth.login.usePassword }));
    expect(onUsePassword).toHaveBeenCalled();
  });
});
