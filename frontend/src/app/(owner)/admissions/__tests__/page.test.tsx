import { render } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import AdmissionsPage from "../page";

const state = vi.hoisted(() => ({ params: new URLSearchParams(), preselect: vi.fn() }));

vi.mock("next/navigation", () => ({ useSearchParams: () => state.params }));
vi.mock("@/components/shared/RequirePermission", () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/features/admissions/AdmissionWizard", () => ({
  AdmissionWizard: ({ preselect }: { preselect?: unknown }) => {
    state.preselect(preselect);
    return null;
  },
}));

describe("Admissions page preselection from the URL", () => {
  beforeEach(() => state.preselect.mockReset());

  test.each([
    ["?property=p1&bed=b1", { propertyId: "p1", bedId: "b1" }], // Vacancies screen
    ["?property=p1", { propertyId: "p1", bedId: undefined }], // Getting started checklist
    ["", undefined],
    ["?bed=b1", undefined], // a bed without its property is ignored
  ])("%s", (query, expected) => {
    state.params = new URLSearchParams(query);
    render(<AdmissionsPage />);
    expect(state.preselect).toHaveBeenLastCalledWith(expected);
  });
});
