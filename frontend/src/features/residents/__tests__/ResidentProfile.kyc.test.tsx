/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import common from "@/messages/en/common.json";
import residents from "@/messages/en/residents.json";
import status from "@/messages/en/status.json";

const mocks = vi.hoisted(() => ({
  getResident: vi.fn(),
  listComplaints: vi.fn(),
  createDepositPayment: vi.fn(),
  user: { value: null as { kyc_uploads_enabled?: boolean } | null },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getResident: mocks.getResident,
    listComplaints: mocks.listComplaints,
    createDepositPayment: mocks.createDepositPayment,
  };
});
vi.mock("@/lib/session", () => ({
  useSession: () => ({ can: () => true, user: mocks.user.value }),
}));
vi.mock("@/components/shared/PermissionGate", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/shared/ContactActions", () => ({ ContactActions: () => null }));
vi.mock("../FinanceCard", () => ({ FinanceCard: () => null }));
vi.mock("../TransferRoomDialog", () => ({ TransferRoomDialog: () => null }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { ResidentProfile } from "../ResidentProfile";

const RESIDENT = {
  id: "r1",
  first_name: "Ravi",
  last_name: "Kumar",
  phone: "9000000001",
  status: "active",
  aadhaar_number: "1234",
  aadhaar_document: "https://files.example.test/aadhaar.pdf",
  pan_document: null,
};

async function openDocumentsTab() {
  render(
    <NextIntlClientProvider locale="en" messages={{ common, residents, status }}>
      <ResidentProfile id="r1" />
    </NextIntlClientProvider>
  );
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: new RegExp(residents.profile.tabs.documents) }));
}

describe("ResidentProfile → documents tab and the KYC upload gate", () => {
  beforeEach(() => {
    mocks.getResident.mockReset().mockResolvedValue(RESIDENT);
    mocks.listComplaints.mockReset().mockResolvedValue([]);
  });

  test("uploads off: no file inputs and an explanation, but stored documents stay downloadable", async () => {
    mocks.user.value = { kyc_uploads_enabled: false };
    await openDocumentsTab();

    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
    expect(screen.getByText(residents.profile.documents.uploadsDisabled)).toBeTruthy();
    expect(screen.getByRole("link", { name: new RegExp(residents.profile.documents.download) }).getAttribute("href")).toBe(
      RESIDENT.aadhaar_document
    );
  });

  test("an older cached profile without the flag is treated as off", async () => {
    mocks.user.value = {};
    await openDocumentsTab();
    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
  });

  test("uploads on: both document slots can be uploaded to and there is no notice", async () => {
    mocks.user.value = { kyc_uploads_enabled: true };
    await openDocumentsTab();

    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(2);
    expect(screen.queryByText(residents.profile.documents.uploadsDisabled)).toBeNull();
  });
});

describe("ResidentProfile → security deposit paid in parts", () => {
  beforeEach(() => {
    mocks.user.value = {};
    mocks.listComplaints.mockReset().mockResolvedValue([]);
  });

  const renderProfile = async (resident: object) => {
    mocks.getResident.mockReset().mockResolvedValue({ ...RESIDENT, ...resident });
    render(
      <NextIntlClientProvider locale="en" messages={{ common, residents, status }}>
        <ResidentProfile id="r1" />
      </NextIntlClientProvider>
    );
    await act(async () => {});
  };

  test("shows agreed, collected and pending, with a button to record the rest", async () => {
    await renderProfile({
      security_deposit_agreed: "5000.00", security_deposit_amount: "2000.00", security_deposit_pending: "3000.00",
    });

    expect(screen.getByText(residents.profile.overview.depositAgreed)).toBeTruthy();
    expect(screen.getByText("₹5,000.00")).toBeTruthy();
    expect(screen.getByText("₹2,000.00")).toBeTruthy();
    expect(screen.getByText("₹3,000.00")).toBeTruthy();
    expect(screen.getByRole("button", { name: residents.profile.overview.recordDeposit })).toBeTruthy();
  });

  test("nothing pending: no pending row and no record button", async () => {
    await renderProfile({
      security_deposit_agreed: "5000.00", security_deposit_amount: "5000.00", security_deposit_pending: "0.00",
    });

    expect(screen.queryByText(residents.profile.overview.depositPending)).toBeNull();
    expect(screen.queryByRole("button", { name: residents.profile.overview.recordDeposit })).toBeNull();
  });

  test("a vacated resident can't pay a deposit, so there is no record button", async () => {
    await renderProfile({
      status: "vacated", security_deposit_agreed: "5000.00", security_deposit_amount: "2000.00", security_deposit_pending: "3000.00",
    });

    expect(screen.queryByRole("button", { name: residents.profile.overview.recordDeposit })).toBeNull();
  });

  test("an older API without the agreed amount still shows what was collected", async () => {
    await renderProfile({ security_deposit_amount: "1500.00" });

    expect(screen.getAllByText("₹1,500.00").length).toBe(2); // agreed falls back to collected
    expect(screen.queryByRole("button", { name: residents.profile.overview.recordDeposit })).toBeNull();
  });

  test("the button opens the record-deposit dialog; recording reloads the profile", async () => {
    await renderProfile({
      security_deposit_agreed: "5000.00", security_deposit_amount: "2000.00", security_deposit_pending: "3000.00",
    });
    fireEvent.click(screen.getByRole("button", { name: residents.profile.overview.recordDeposit }));

    const submit = await screen.findByRole("button", { name: residents.profile.depositDialog.submit });
    mocks.getResident.mockClear();
    mocks.createDepositPayment.mockResolvedValue({ payment: { id: "p1" }, replayed: false });
    fireEvent.click(submit);

    expect(await screen.findByText(residents.profile.depositDialog.success)).toBeTruthy();
    expect(mocks.getResident).toHaveBeenCalledWith("r1");
  });
});
