/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import settings from "@/messages/en/settings.json";

const api = vi.hoisted(() => ({ changePassword: vi.fn(), getCurrentUser: vi.fn(), listProperties: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/features/subscription/SubscriptionPanel", () => ({ SubscriptionPanel: () => null }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { ApiError } from "@/lib/api";
import { GlobalSettings } from "../GlobalSettings";

const NEW_PASSWORD = "Copper-Meadow-42";

function renderSecurityTab() {
  render(
    <NextIntlClientProvider locale="en" messages={{ settings }}>
      <GlobalSettings initialTab="security" />
    </NextIntlClientProvider>
  );
}

async function submit(current = "Vintage-Kite-77", next = NEW_PASSWORD, confirm = next) {
  fireEvent.change(screen.getByLabelText(settings.global.currentPassword), { target: { value: current } });
  fireEvent.change(screen.getByLabelText(settings.global.newPassword), { target: { value: next } });
  fireEvent.change(screen.getByLabelText(settings.global.confirmPassword), { target: { value: confirm } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: settings.global.updateCredentials }));
  });
}

describe("Settings → change password", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getCurrentUser.mockResolvedValue({});
    api.listProperties.mockResolvedValue([]);
    api.changePassword.mockResolvedValue(undefined);
  });

  test("opens on the security tab when asked to", () => {
    renderSecurityTab();
    expect(screen.getByText(settings.global.changePassword)).toBeTruthy();
  });

  test("calls the real endpoint, clears the form and confirms", async () => {
    renderSecurityTab();
    await submit();
    expect(api.changePassword).toHaveBeenCalledWith("Vintage-Kite-77", NEW_PASSWORD);
    expect(screen.getByText(settings.global.passwordSavedToast)).toBeTruthy();
    expect((screen.getByLabelText(settings.global.newPassword) as HTMLInputElement).value).toBe("");
  });

  test("validates on the client first (8-character minimum, matching confirmation)", async () => {
    renderSecurityTab();
    await submit("Vintage-Kite-77", "short", "different");
    expect(screen.getByText(settings.global.errNewMinLength)).toBeTruthy();
    expect(screen.getByText(settings.global.errConfirmMatch)).toBeTruthy();
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  test("a wrong current password shows the backend's message under that field and changes nothing", async () => {
    api.changePassword.mockRejectedValue(
      new ApiError(400, { current_password: ["Current password is incorrect."], code: "INVALID" })
    );
    renderSecurityTab();
    await submit();
    expect(screen.getByText("Current password is incorrect.")).toBeTruthy();
    expect(screen.queryByText(settings.global.passwordSavedToast)).toBeNull();
    // The typed values stay so the user can correct them.
    expect((screen.getByLabelText(settings.global.newPassword) as HTMLInputElement).value).toBe(NEW_PASSWORD);
  });

  test("the backend's strength message is shown under the new-password field", async () => {
    api.changePassword.mockRejectedValue(
      new ApiError(400, { new_password: ["This password is too common."], code: "INVALID" })
    );
    renderSecurityTab();
    await submit();
    expect(screen.getByText("This password is too common.")).toBeTruthy();
  });

  test("throttling, network failures and anything else get a message", async () => {
    api.changePassword.mockRejectedValueOnce(new ApiError(429, { detail: "throttled" }));
    renderSecurityTab();
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(settings.global.errPasswordThrottled);

    api.changePassword.mockRejectedValueOnce(new ApiError(0, { detail: "offline" }));
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(settings.global.errPasswordUnreachable);

    api.changePassword.mockRejectedValueOnce(new ApiError(500, { detail: "boom" }));
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(settings.global.errPasswordFailed);
  });
});
