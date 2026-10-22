import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { ApiError, type Property } from "@/lib/api";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { GlobalSettings } from "../GlobalSettings";

const api = vi.hoisted(() => ({
  listProperties: vi.fn(),
  getCurrentUser: vi.fn(),
  changePassword: vi.fn(),
  clearSession: vi.fn(),
}));
const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("@/features/subscription/SubscriptionPanel", () => ({ SubscriptionPanel: () => null }));

const property = (id: string, name: string): Property =>
  ({ id, name, city: "Hyderabad", state: "Telangana", property_type: "pg" }) as unknown as Property;

beforeEach(() => {
  vi.clearAllMocks();
  api.clearSession.mockResolvedValue(undefined);
  api.getCurrentUser.mockResolvedValue({ tenant: { default_language: "en", fiscal_year_start_month: 4 } });
});

describe("GlobalSettings property setup tab", () => {
  test("lists the account's own properties and links to their real ids", async () => {
    api.listProperties.mockResolvedValue([property("0b9c1a52-1111-4222-8333-444455556666", "Keshav PG")]);
    renderWithIntl(<GlobalSettings />);

    expect(await screen.findByText("Keshav PG")).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("href"))).toContain(
      "/properties/0b9c1a52-1111-4222-8333-444455556666/settings"
    );
  });

  test("a new owner with no properties sees an empty state, not demo properties", async () => {
    api.listProperties.mockResolvedValue([]);
    renderWithIntl(<GlobalSettings />);

    expect(await screen.findByText(/haven't added a property yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add property" })).toHaveAttribute("href", "/properties/add");
    expect(screen.queryByText("Skyline Tower")).not.toBeInTheDocument();
    expect(screen.queryByText("Sunset Apartments Complex")).not.toBeInTheDocument();
  });
});

describe("GlobalSettings change password", () => {
  const fill = async (current: string, next: string, confirm = next) => {
    api.listProperties.mockResolvedValue([]);
    renderWithIntl(<GlobalSettings />);
    fireEvent.click(await screen.findByRole("button", { name: /Account & Security/ }));
    fireEvent.change(document.getElementById("current")!, { target: { value: current } });
    fireEvent.change(document.getElementById("new")!, { target: { value: next } });
    fireEvent.change(document.getElementById("confirm")!, { target: { value: confirm } });
    fireEvent.click(screen.getByRole("button", { name: "Update Security Credentials" }));
  };

  test("sends the passwords to the API, then signs the user out to /login", async () => {
    api.changePassword.mockResolvedValue({ detail: "ok" });
    await fill("Old-Password-1", "New-Password-2");

    await waitFor(() =>
      expect(api.changePassword).toHaveBeenCalledWith({ current_password: "Old-Password-1", new_password: "New-Password-2" })
    );
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"), { timeout: 4000 });
    expect(api.clearSession).toHaveBeenCalled();
  });

  test("a wrong current password shows the server's message and keeps the session", async () => {
    api.changePassword.mockRejectedValue(
      new ApiError(400, { current_password: ["Your current password is incorrect."] })
    );
    await fill("Wrong-Password-1", "New-Password-2");

    expect(await screen.findByText("Your current password is incorrect.")).toBeInTheDocument();
    expect(api.clearSession).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  test("a mismatched confirmation never reaches the API", async () => {
    await fill("Old-Password-1", "New-Password-2", "Different-Password-3");

    expect(await screen.findByText("Passwords do not match")).toBeInTheDocument();
    expect(api.changePassword).not.toHaveBeenCalled();
  });
});
