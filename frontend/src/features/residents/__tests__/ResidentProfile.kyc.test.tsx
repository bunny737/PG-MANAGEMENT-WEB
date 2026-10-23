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
  user: { value: null as { kyc_uploads_enabled?: boolean } | null },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getResident: mocks.getResident, listComplaints: mocks.listComplaints };
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
