/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import accountDeletion from "@/messages/en/accountDeletion.json";
import type { DeletionConfirmMethod } from "@/lib/accountDeletion";

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  requestAccountDeletion: vi.fn(),
  sendAccountDeletionCode: vi.fn(),
}));
const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ApiError } from "@/lib/api";
import { DeleteAccountCard } from "../DeleteAccountCard";

const d = accountDeletion.dialog;

function user(role: string, methods: DeletionConfirmMethod[]) {
  return { id: "u1", email: "a@b.c", role, language_code: "en", email_verified: true, deletion_confirm_methods: methods };
}

async function openDialog(role = "owner", methods: DeletionConfirmMethod[] = ["password", "otp_email"]) {
  api.getCurrentUser.mockResolvedValue(user(role, methods));
  render(
    <NextIntlClientProvider locale="en" messages={{ accountDeletion }}>
      <DeleteAccountCard />
    </NextIntlClientProvider>
  );
  fireEvent.click(await screen.findByRole("button", { name: accountDeletion.card.button }));
}

// The card and the dialog both have a "Delete my account" button: the submit is the one in the dialog.
const submitButton = () => within(screen.getByRole("dialog")).getByRole("button", { name: d.submit });
const tick = () => fireEvent.click(screen.getByLabelText(d.understand));

describe("DeleteAccountCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("an Owner is told the whole business goes, with the export hint", async () => {
    await openDialog("owner");
    expect(screen.getByText(d.ownerIntro)).toBeInTheDocument();
    for (const item of d.ownerItems) expect(screen.getByText(item)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: d.exportLink })).toHaveAttribute("href", "/reports");
  });

  test("staff are told only their own login goes", async () => {
    await openDialog("manager");
    expect(screen.getByText(d.staffIntro)).toBeInTheDocument();
    expect(screen.queryByText(d.ownerIntro)).not.toBeInTheDocument();
  });

  test("the card text differs for an Owner and for staff", async () => {
    api.getCurrentUser.mockResolvedValue(user("manager", ["password"]));
    render(
      <NextIntlClientProvider locale="en" messages={{ accountDeletion }}>
        <DeleteAccountCard />
      </NextIntlClientProvider>
    );
    expect(await screen.findByText(accountDeletion.card.staffBody)).toBeInTheDocument();
  });

  test("submit stays disabled until the warning is acknowledged and a password is typed", async () => {
    await openDialog();
    expect(submitButton()).toBeDisabled();
    fireEvent.change(screen.getByLabelText(d.passwordLabel), { target: { value: "pw" } });
    expect(submitButton()).toBeDisabled();
    tick();
    expect(submitButton()).toBeEnabled();
  });

  test("confirming with the password requests deletion and goes to the pending screen", async () => {
    api.requestAccountDeletion.mockResolvedValue({ scope: "tenant", status: "pending" });
    await openDialog();
    fireEvent.change(screen.getByLabelText(d.passwordLabel), { target: { value: "my-password" } });
    tick();
    fireEvent.click(submitButton());

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/account/deletion-pending"));
    expect(api.requestAccountDeletion).toHaveBeenCalledWith({ password: "my-password" });
  });

  test("confirming with an emailed code sends the code first, then requests deletion with it", async () => {
    api.sendAccountDeletionCode.mockResolvedValue(undefined);
    api.requestAccountDeletion.mockResolvedValue({ scope: "tenant", status: "pending" });
    await openDialog();
    fireEvent.click(screen.getByLabelText(d.methods.otp_email));

    fireEvent.click(screen.getByRole("button", { name: d.sendCode }));
    expect(await screen.findByText(d.codeSent)).toBeInTheDocument();
    expect(api.sendAccountDeletionCode).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText(d.codeLabel), { target: { value: "12ab3456" } }); // letters dropped
    tick();
    fireEvent.click(submitButton());

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(api.requestAccountDeletion).toHaveBeenCalledWith({ otp: "123456" });
  });

  test("a wrong password shows the backend's own (translated) message and stays open", async () => {
    api.requestAccountDeletion.mockRejectedValue(new ApiError(400, { password: ["Incorrect password."] }));
    await openDialog();
    fireEvent.change(screen.getByLabelText(d.passwordLabel), { target: { value: "bad" } });
    tick();
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect password.");
    expect(router.push).not.toHaveBeenCalled();
    expect(submitButton()).toBeEnabled();
  });

  test("throttling and unknown failures have their own messages", async () => {
    api.requestAccountDeletion.mockRejectedValueOnce(new ApiError(429, { detail: "slow down" }));
    await openDialog();
    fireEvent.change(screen.getByLabelText(d.passwordLabel), { target: { value: "x" } });
    tick();
    fireEvent.click(submitButton());
    expect(await screen.findByText(d.throttled)).toBeInTheDocument();

    api.requestAccountDeletion.mockRejectedValueOnce(new Error("network"));
    fireEvent.click(submitButton());
    expect(await screen.findByText(d.failed)).toBeInTheDocument();
  });

  test("an account with no way to confirm online is pointed at support", async () => {
    await openDialog("owner", []);
    expect(screen.getByText(d.noMethod)).toBeInTheDocument();
    tick();
    expect(submitButton()).toBeDisabled();
  });

  test("phone-code confirmation is never offered", async () => {
    await openDialog("manager", ["otp_phone"]);
    expect(screen.getByText(d.noMethod)).toBeInTheDocument();
  });

  test("keeping the account closes the dialog without calling the API", async () => {
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: d.keep }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.requestAccountDeletion).not.toHaveBeenCalled();
  });
});
