/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import accountDeletion from "@/messages/en/accountDeletion.json";
import type { AccountDeletion } from "@/lib/accountDeletion";

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  cancelAccountDeletion: vi.fn(),
  clearSession: vi.fn(),
}));
const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { DeletionPendingScreen } from "../DeletionPendingScreen";

const pending = (overrides: Partial<AccountDeletion> = {}): AccountDeletion => ({
  scope: "tenant",
  status: "pending",
  scheduled_for: "2026-10-31T00:00:00+05:30",
  can_cancel: true,
  ...overrides,
});

function me(role: string, deletion: AccountDeletion | null) {
  return { id: "u1", email: "a@b.c", role, language_code: "en", email_verified: true, permissions: [], deletion };
}

function renderScreen() {
  render(
    <NextIntlClientProvider locale="en" messages={{ accountDeletion }}>
      <DeletionPendingScreen />
    </NextIntlClientProvider>
  );
}

describe("DeletionPendingScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("an Owner sees the whole-business date and can cancel", async () => {
    api.getCurrentUser.mockResolvedValue(me("owner", pending()));
    renderScreen();

    expect(await screen.findByText(accountDeletion.pending.titlePending)).toBeInTheDocument();
    expect(screen.getByText(/October 31, 2026/)).toBeInTheDocument();
    expect(screen.getByText(/whole business/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: accountDeletion.pending.cancel })).toBeEnabled();
  });

  test("cancelling calls the API, re-checks the account and leaves the screen once it is unlocked", async () => {
    api.getCurrentUser
      .mockResolvedValueOnce(me("owner", pending()))
      .mockResolvedValueOnce(me("owner", null));
    api.cancelAccountDeletion.mockResolvedValue(undefined);
    renderScreen();

    fireEvent.click(await screen.findByRole("button", { name: accountDeletion.pending.cancel }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledTimes(1));
    expect(api.cancelAccountDeletion).toHaveBeenCalledTimes(1);
    expect(router.replace).toHaveBeenCalledWith("/profile"); // no permissions -> the profile
  });

  test("a failed cancel says so and keeps the button", async () => {
    api.getCurrentUser.mockResolvedValue(me("owner", pending()));
    api.cancelAccountDeletion.mockRejectedValue(new Error("boom"));
    renderScreen();

    fireEvent.click(await screen.findByRole("button", { name: accountDeletion.pending.cancel }));

    expect(await screen.findByText(accountDeletion.pending.cancelFailed)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: accountDeletion.pending.cancel })).toBeEnabled();
  });

  test("staff of a deleting business see their access end and cannot cancel", async () => {
    api.getCurrentUser.mockResolvedValue(me("manager", pending({ can_cancel: false })));
    renderScreen();

    expect(await screen.findByText(/Your organisation is being deleted/)).toBeInTheDocument();
    expect(screen.getByText(accountDeletion.pending.ownerOnly)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: accountDeletion.pending.cancel })).not.toBeInTheDocument();
  });

  test("a staff member's own request names their account, not a business", async () => {
    api.getCurrentUser.mockResolvedValue(me("manager", pending({ scope: "user" })));
    renderScreen();
    expect(await screen.findByText(/Your account will be permanently deleted/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: accountDeletion.pending.cancel })).toBeInTheDocument();
  });

  test("a deletion in progress cannot be cancelled", async () => {
    api.getCurrentUser.mockResolvedValue(me("owner", pending({ status: "processing", can_cancel: false })));
    renderScreen();
    expect(await screen.findByText(accountDeletion.pending.titleProcessing)).toBeInTheDocument();
    expect(screen.getByText(accountDeletion.pending.processingBody)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: accountDeletion.pending.cancel })).not.toBeInTheDocument();
  });

  test("a failed deletion shows the delayed state, not a cancel button", async () => {
    api.getCurrentUser.mockResolvedValue(me("owner", pending({ status: "failed", can_cancel: false })));
    renderScreen();
    expect(await screen.findByText(accountDeletion.pending.titleFailed)).toBeInTheDocument();
    expect(screen.getByText(accountDeletion.pending.failedBody)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: accountDeletion.pending.cancel })).not.toBeInTheDocument();
  });

  test("an account that is no longer locked is sent back into the app", async () => {
    api.getCurrentUser.mockResolvedValue(me("owner", null));
    renderScreen();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/profile"));
  });

  test("a load failure can be retried", async () => {
    api.getCurrentUser.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(me("owner", pending()));
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: accountDeletion.pending.retry }));
    expect(await screen.findByText(accountDeletion.pending.titlePending)).toBeInTheDocument();
  });

  test("a started deletion is re-checked on a timer", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.getCurrentUser.mockResolvedValue(me("owner", pending({ status: "processing", can_cancel: false })));
    renderScreen();
    await screen.findByText(accountDeletion.pending.titleProcessing);
    expect(api.getCurrentUser).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(api.getCurrentUser.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  test("sign out clears the session and goes to login", async () => {
    api.getCurrentUser.mockResolvedValue(me("owner", pending()));
    api.clearSession.mockResolvedValue(undefined);
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: accountDeletion.pending.signOut }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(api.clearSession).toHaveBeenCalledTimes(1);
  });
});
