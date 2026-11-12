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
  uploadResidentDocument: vi.fn(),
  getResidentDocumentUrl: vi.fn(),
  clearResidentDocument: vi.fn(),
  user: { value: null as { kyc_uploads_enabled?: boolean } | null },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getResident: mocks.getResident,
    listComplaints: mocks.listComplaints,
    createDepositPayment: mocks.createDepositPayment,
    uploadResidentDocument: mocks.uploadResidentDocument,
    getResidentDocumentUrl: mocks.getResidentDocumentUrl,
    clearResidentDocument: mocks.clearResidentDocument,
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

import { ApiError } from "@/lib/api";
import { ResidentProfile } from "../ResidentProfile";

const RESIDENT = {
  id: "r1",
  first_name: "Ravi",
  last_name: "Kumar",
  phone: "9000000001",
  status: "active",
  aadhaar_number: "1234",
  has_aadhaar_document: true,
  pan_number: "",
  has_pan_document: false,
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
    mocks.uploadResidentDocument.mockReset();
    mocks.getResidentDocumentUrl.mockReset();
    mocks.clearResidentDocument.mockReset();
  });

  test("uploads off: no file inputs and an explanation, but stored documents stay downloadable", async () => {
    mocks.user.value = { kyc_uploads_enabled: false };
    mocks.getResidentDocumentUrl.mockResolvedValue({
      url: "https://storage.googleapis.com/pglive-prod-kyc/signed-url",
      expires_in: 300,
      expires_at: "2026-11-12T14:00:00Z",
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    try {
      await openDocumentsTab();

      expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
      expect(screen.getByText(residents.profile.documents.uploadsDisabled)).toBeTruthy();
      const downloadBtn = screen.getByRole("button", { name: new RegExp(residents.profile.documents.download) });
      await act(async () => {
        fireEvent.click(downloadBtn);
      });
      expect(mocks.getResidentDocumentUrl).toHaveBeenCalledWith("r1", "aadhaar_document");
      expect(openSpy).toHaveBeenCalledWith(
        "https://storage.googleapis.com/pglive-prod-kyc/signed-url",
        "_blank",
        "noopener,noreferrer"
      );
    } finally {
      openSpy.mockRestore();
    }
  });

  test("an older cached profile without the flag is treated as off", async () => {
    mocks.user.value = {};
    await openDocumentsTab();
    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
  });

  test("uploads on: narrowed accept attribute, format hint, and no disabled notice", async () => {
    mocks.user.value = { kyc_uploads_enabled: true };
    await openDocumentsTab();

    const inputs = document.querySelectorAll('input[type="file"]');
    expect(inputs).toHaveLength(2);
    expect(inputs[0].getAttribute("accept")).toBe(".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf");
    expect(screen.getByText(residents.profile.documents.formatHint)).toBeTruthy();
    expect(screen.queryByText(residents.profile.documents.uploadsDisabled)).toBeNull();
  });

  test("tolerant client validation rejects >5MB and disallowed MIME, but lets empty/octet-stream through", async () => {
    mocks.user.value = { kyc_uploads_enabled: true };
    await openDocumentsTab();
    const input = document.querySelectorAll('input[type="file"]')[0] as HTMLInputElement;

    const oversized = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "huge.pdf", { type: "application/pdf" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [oversized] } });
    });
    expect(screen.getByRole("alert").textContent).toContain(residents.profile.documents.errFileTooLarge);
    expect(mocks.uploadResidentDocument).not.toHaveBeenCalled();

    const disallowed = new File(["webp"], "pic.webp", { type: "image/webp" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [disallowed] } });
    });
    expect(screen.getByRole("alert").textContent).toContain(residents.profile.documents.errInvalidFileType);
    expect(mocks.uploadResidentDocument).not.toHaveBeenCalled();

    for (const mime of ["", "application/octet-stream", "application/pdf"]) {
      mocks.uploadResidentDocument.mockResolvedValueOnce({ ...RESIDENT, has_aadhaar_document: true });
      const file = new File(["%PDF-1.4"], "doc.pdf", { type: mime });
      await act(async () => {
        fireEvent.change(input, { target: { files: [file] } });
      });
      expect(mocks.uploadResidentDocument).toHaveBeenLastCalledWith("r1", "aadhaar_document", file);
    }
    expect(mocks.uploadResidentDocument).toHaveBeenCalledTimes(3);
  });

  test("download error maps 503 DOCUMENT_URL_UNAVAILABLE cleanly", async () => {
    mocks.user.value = { kyc_uploads_enabled: true };
    mocks.getResidentDocumentUrl.mockRejectedValue(
      new ApiError(503, { code: "DOCUMENT_URL_UNAVAILABLE", detail: "temporarily unavailable" })
    );
    await openDocumentsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(residents.profile.documents.download) }));
    });
    expect(screen.getByRole("alert").textContent).toContain(residents.profile.documents.errDownloadFailed);
  });

  test("remove flow requires confirmation and clears the document", async () => {
    mocks.user.value = { kyc_uploads_enabled: true };
    mocks.clearResidentDocument.mockResolvedValue({ ...RESIDENT, has_aadhaar_document: false });
    await openDocumentsTab();

    fireEvent.click(screen.getByRole("button", { name: new RegExp(residents.profile.documents.remove) }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(residents.profile.documents.removeConfirmDesc)).toBeTruthy();

    // Cancel does not call API
    fireEvent.click(screen.getByRole("button", { name: residents.profile.documents.cancel }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.clearResidentDocument).not.toHaveBeenCalled();

    // Confirm calls clearResidentDocument and updates state
    fireEvent.click(screen.getByRole("button", { name: new RegExp(residents.profile.documents.remove) }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: residents.profile.documents.removeConfirmButton }));
    });
    expect(mocks.clearResidentDocument).toHaveBeenCalledWith("r1", "aadhaar_document");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: new RegExp(residents.profile.documents.download) })).toBeNull();
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
