/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import auth from "@/messages/en/auth.json";
import common from "@/messages/en/common.json";

const api = vi.hoisted(() => ({ login: vi.fn(), loginPhone: vi.fn(), clearSession: vi.fn() }));

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

import { LoginForm } from "../LoginForm";

function renderForm(props: { initialView?: "owner" | "staff" } = {}) {
  render(
    <NextIntlClientProvider locale="en" messages={{ auth, common }}>
      <LoginForm {...props} />
    </NextIntlClientProvider>
  );
}

describe("LoginForm", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  test("starts on the role chooser by default", () => {
    renderForm();
    expect(screen.getByText(auth.login.chooseTitle)).toBeTruthy();
  });

  test("initialView=staff opens the staff sign-in directly (the landing spot after an invite)", () => {
    renderForm({ initialView: "staff" });
    expect(screen.queryByText(auth.login.chooseTitle)).toBeNull();
    expect(screen.getByLabelText(auth.login.phoneLabel)).toBeTruthy();
  });

  test("initialView=owner opens the owner sign-in directly", () => {
    renderForm({ initialView: "owner" });
    expect(screen.getByLabelText(auth.login.emailLabel)).toBeTruthy();
  });

  test("'Forgot password?' is a real link to /forgot-password in both views", () => {
    renderForm({ initialView: "owner" });
    expect(screen.getByRole("link", { name: auth.login.forgotPassword }).getAttribute("href")).toBe("/forgot-password");
    fireEvent.click(screen.getByText(auth.login.backToSelection));
    fireEvent.click(screen.getByText(auth.login.staffOptionTitle));
    expect(screen.getByRole("link", { name: auth.login.forgotPassword }).getAttribute("href")).toBe("/forgot-password");
  });

  test("sign-in accepts any non-empty password: an older, shorter one must still reach Django", async () => {
    api.login.mockResolvedValue({ role: "owner", permissions: [] });
    renderForm({ initialView: "owner" });
    fireEvent.change(screen.getByLabelText(auth.login.emailLabel), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText(auth.login.passwordLabel), { target: { value: "abcd" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: auth.login.submitPassword }));
    });
    expect(api.login).toHaveBeenCalledWith("owner@example.com", "abcd");
  });

  test("an empty password is still rejected on the client", async () => {
    renderForm({ initialView: "owner" });
    fireEvent.change(screen.getByLabelText(auth.login.emailLabel), { target: { value: "owner@example.com" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: auth.login.submitPassword }));
    });
    expect(screen.getByText(auth.login.errPasswordRequired)).toBeTruthy();
    expect(api.login).not.toHaveBeenCalled();
  });

  test("no demo-credentials box and no unwired 'keep me signed in' checkbox", () => {
    renderForm({ initialView: "owner" });
    expect(screen.queryByText(/Demo Credentials/i)).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
