import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { copy, NOTICE_ID, notice, OWNER, renderWithMessages } from "./testUtils";

const api = vi.hoisted(() => ({
  listNotices: vi.fn(),
  getNotice: vi.fn(),
  markNoticeCurrent: vi.fn(),
  deleteNotice: vi.fn(),
  createNotice: vi.fn(),
  updateNotice: vi.fn(),
  listProperties: vi.fn(),
}));
const session = vi.hoisted(() => ({ permissions: new Set<string>() }));
const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
const refresh = vi.hoisted(() => ({ afterNoticeChange: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => session.permissions.has(code) }),
}));
vi.mock("@/lib/refresh", () => refresh);
vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({ propertyId: null }),
  PropertyFilter: () => null,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => nav.params,
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { NoticesList } from "../NoticesList";

const OUTDATED = notice({ id: "n-outdated", title: "Dasara: no food", food_holiday: "h1", notice_outdated: true });

beforeEach(() => {
  for (const fn of [...Object.values(api), nav.replace, refresh.afterNoticeChange]) fn.mockReset();
  nav.params = new URLSearchParams();
  session.permissions = new Set(OWNER);
  api.listProperties.mockResolvedValue([]);
  api.listNotices.mockResolvedValue([]);
});

describe("Notices tab", () => {
  test("lists notices in the order the API returns them (pinned first is the server's job)", async () => {
    api.listNotices.mockResolvedValue([
      notice({ id: "a", title: "Pinned rules", is_pinned: true }),
      notice({ id: "b", title: "Water supply cut" }),
    ]);
    renderWithMessages(<NoticesList />);

    const titles = (await screen.findAllByRole("heading", { level: 3 })).map((h) => h.textContent);
    expect(titles).toEqual(["Pinned rules", "Water supply cut"]);
    expect(api.listNotices).toHaveBeenCalledWith(expect.objectContaining({ active: "true" }));
  });

  test("an outdated holiday notice can be dismissed with 'Looks right'", async () => {
    api.listNotices.mockResolvedValue([OUTDATED]);
    api.markNoticeCurrent.mockResolvedValue({ ...OUTDATED, notice_outdated: false });
    renderWithMessages(<NoticesList />);

    expect(await screen.findByText(copy.outdated.title)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy.outdated.dismiss }));
    await act(async () => {});

    expect(api.markNoticeCurrent).toHaveBeenCalledWith("n-outdated");
    expect(refresh.afterNoticeChange).toHaveBeenCalled();
  });

  test("without manage_notices: no add, edit, delete, and neither banner button, only the warning", async () => {
    session.permissions = new Set(["view_notices"]);
    api.listNotices.mockResolvedValue([OUTDATED]);
    renderWithMessages(<NoticesList />);

    expect(await screen.findByText(copy.outdated.title)).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy.notice.add })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.notice.edit })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.notice.delete })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.outdated.edit })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.outdated.dismiss })).toBeNull();
  });

  test("a deep link shows an expired notice the Active filter would hide", async () => {
    nav.params = new URLSearchParams(`tab=notices&notice=${NOTICE_ID}`);
    api.listNotices.mockResolvedValue([notice({ id: "other", title: "Wi-Fi password changed" })]);
    api.getNotice.mockResolvedValue(notice({ title: "Old festival notice", expires_on: "2026-01-01" }));
    renderWithMessages(<NoticesList />);

    const linked = await screen.findByRole("region", { name: copy.linked.title });
    expect(await within(linked).findByText("Old festival notice")).toBeTruthy();
    expect(api.getNotice).toHaveBeenCalledWith(NOTICE_ID);
    // Still listed once, not twice.
    expect(screen.getAllByText("Wi-Fi password changed")).toHaveLength(1);
  });

  test("a deep link to a deleted notice says so", async () => {
    nav.params = new URLSearchParams(`tab=notices&notice=${NOTICE_ID}`);
    api.getNotice.mockRejectedValue(new ApiError(404, { detail: "Not found." }));
    renderWithMessages(<NoticesList />);

    expect(await screen.findByText(copy.linked.deleted)).toBeTruthy();
  });
});
