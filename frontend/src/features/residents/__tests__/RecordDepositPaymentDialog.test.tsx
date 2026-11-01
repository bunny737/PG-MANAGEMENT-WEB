/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import residents from "@/messages/en/residents.json";
import status from "@/messages/en/status.json";
import { ApiError, type Resident } from "@/lib/api";
import { RecordDepositPaymentDialog } from "../RecordDepositPaymentDialog";

const api = vi.hoisted(() => ({ createDepositPayment: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));

const t = residents.profile.depositDialog;

const RESIDENT = {
  id: "r1",
  first_name: "Ravi",
  last_name: "Kumar",
  status: "active",
  security_deposit_agreed: "5000.00",
  security_deposit_amount: "2000.00",
  security_deposit_pending: "3000.00",
} as unknown as Resident;

function renderDialog(onRecorded = vi.fn(), onClose = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={{ residents, status }}>
      <RecordDepositPaymentDialog resident={RESIDENT} onClose={onClose} onRecorded={onRecorded} />
    </NextIntlClientProvider>
  );
  return { onRecorded, onClose };
}

const amountInput = () => screen.getByLabelText(t.amount) as HTMLInputElement;
const submit = () => fireEvent.click(screen.getByRole("button", { name: t.submit }));

describe("RecordDepositPaymentDialog", () => {
  beforeEach(() => {
    api.createDepositPayment.mockReset().mockResolvedValue({ payment: { id: "p1" }, replayed: false });
  });

  test("starts at the pending amount and says who owes how much", () => {
    renderDialog();

    expect(amountInput().value).toBe("3000.00");
    expect(screen.getByText("Ravi Kumar · ₹3,000.00 pending")).toBeInTheDocument();
  });

  test("records a part payment for the resident, then reports success and lets the profile reload", async () => {
    const { onRecorded } = renderDialog();
    fireEvent.change(amountInput(), { target: { value: "1500" } });
    fireEvent.change(screen.getByLabelText(t.reference), { target: { value: "UPI-123" } });
    submit();

    expect(await screen.findByText(t.success)).toBeInTheDocument();
    expect(api.createDepositPayment).toHaveBeenCalledWith(
      { resident: "r1", amount: "1500.00", payment_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), payment_mode: "cash", reference: "UPI-123" },
      expect.any(String)
    );
    expect(onRecorded).toHaveBeenCalledTimes(1);
  });

  test("a replay of the same key reads as already recorded", async () => {
    api.createDepositPayment.mockResolvedValue({ payment: { id: "p1" }, replayed: true });
    renderDialog();
    submit();

    expect(await screen.findByText(t.replayed)).toBeInTheDocument();
  });

  test("more than pending, zero, and junk are refused without calling the API", () => {
    renderDialog();

    for (const [value, message] of [
      ["3000.01", t.errExceeds],
      ["0", t.errAmount],
      ["abc", t.errAmount],
      ["-5", t.errAmount],
    ] as const) {
      fireEvent.change(amountInput(), { target: { value } });
      submit();
      expect(screen.getByRole("alert").textContent, value).toBe(message);
    }
    expect(api.createDepositPayment).not.toHaveBeenCalled();
  });

  test("the server's own message is shown, and a retry reuses the same Idempotency-Key", async () => {
    api.createDepositPayment
      .mockRejectedValueOnce(new ApiError(400, { amount: ["This exceeds the pending security deposit of 1000.00."] }))
      .mockResolvedValueOnce({ payment: { id: "p1" }, replayed: false });
    renderDialog();
    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent("This exceeds the pending security deposit of 1000.00.");
    submit();
    await screen.findByText(t.success);

    const [first, second] = api.createDepositPayment.mock.calls;
    expect(first[1]).toBe(second[1]);
  });

  test("a reused key (409) gets a friendly message", async () => {
    api.createDepositPayment.mockRejectedValueOnce(new ApiError(409, { code: "idempotency_key_reused", detail: "x" }));
    renderDialog();
    submit();

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(t.errReused));
  });

  test("offers only the modes the API accepts", () => {
    renderDialog();

    const options = Array.from((screen.getByLabelText(t.mode) as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(["cash", "upi", "bank_transfer"]);
  });
});
