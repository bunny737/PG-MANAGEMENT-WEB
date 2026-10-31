import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { copy, dayOffset, notice, PROPERTY_A, PROPERTIES, renderWithMessages } from "./testUtils";

const api = vi.hoisted(() => ({
  createNotice: vi.fn(),
  updateNotice: vi.fn(),
  listProperties: vi.fn(),
}));
const refresh = vi.hoisted(() => ({ afterNoticeChange: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/lib/refresh", () => refresh);

import { NoticeFormSheet } from "../NoticeFormSheet";

const form = copy.form;
const onClose = vi.fn();

async function submit(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
  await act(async () => {});
}

beforeEach(() => {
  for (const fn of [...Object.values(api), refresh.afterNoticeChange, onClose]) fn.mockReset();
  api.listProperties.mockResolvedValue(PROPERTIES);
  api.createNotice.mockResolvedValue(notice());
  api.updateNotice.mockResolvedValue(notice());
});

describe("NoticeFormSheet", () => {
  test("an expired notice's text can be edited while it keeps its expiry; only the changed field is sent", async () => {
    const expired = notice({ expires_on: dayOffset(-1) });
    renderWithMessages(<NoticeFormSheet initial={expired} defaultProperty={null} onClose={onClose} />);

    fireEvent.change(screen.getByLabelText(form.body), { target: { value: "Water is back." } });
    await submit(form.save);

    expect(api.updateNotice).toHaveBeenCalledWith(expired.id, { body: "Water is back." });
    expect(onClose).toHaveBeenCalled();
  });

  test("an expired notice's date picker has no 'today' minimum, so its stored date stays valid", async () => {
    renderWithMessages(
      <NoticeFormSheet initial={notice({ expires_on: dayOffset(-1) })} defaultProperty={null} onClose={onClose} />
    );
    expect((screen.getByLabelText(form.expiresOn) as HTMLInputElement).min).toBe("");
  });

  test("moving the expiry to a past day is blocked", async () => {
    renderWithMessages(<NoticeFormSheet initial={notice()} defaultProperty={null} onClose={onClose} />);

    fireEvent.change(screen.getByLabelText(form.expiresOn), { target: { value: dayOffset(-3) } });
    await submit(form.save);

    expect(screen.getByText(form.expiryInPast)).toBeTruthy();
    expect(api.updateNotice).not.toHaveBeenCalled();
  });

  test("a new notice can't expire in the past", async () => {
    renderWithMessages(<NoticeFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);

    fireEvent.change(screen.getByLabelText(form.noticeTitle), { target: { value: "Rules" } });
    fireEvent.change(screen.getByLabelText(form.body), { target: { value: "Quiet after 10pm." } });
    fireEvent.change(screen.getByLabelText(form.expiresOn), { target: { value: dayOffset(-1) } });
    await submit(form.submit);

    expect(screen.getByText(form.expiryInPast)).toBeTruthy();
    expect(api.createNotice).not.toHaveBeenCalled();
  });

  test("posts a new notice with everything entered", async () => {
    renderWithMessages(<NoticeFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);

    fireEvent.change(screen.getByLabelText(form.noticeTitle), { target: { value: " Rules " } });
    fireEvent.change(screen.getByLabelText(form.body), { target: { value: "Quiet after 10pm." } });
    fireEvent.change(screen.getByLabelText(form.category), { target: { value: "rules" } });
    fireEvent.click(screen.getByLabelText(new RegExp(form.pinned)));
    await submit(form.submit);

    expect(api.createNotice).toHaveBeenCalledWith({
      property: PROPERTY_A,
      title: "Rules",
      body: "Quiet after 10pm.",
      category: "rules",
      is_pinned: true,
      expires_on: null,
    });
    expect(refresh.afterNoticeChange).toHaveBeenCalled();
  });

  test("a refresh while open doesn't send back text someone else changed meanwhile", async () => {
    const view = renderWithMessages(
      <NoticeFormSheet initial={notice({ body: "Water off 6-8am." })} defaultProperty={null} onClose={onClose} />
    );
    view.rerenderWith(
      <NoticeFormSheet initial={notice({ body: "Water off 7-9am." })} defaultProperty={null} onClose={onClose} />
    );
    fireEvent.change(screen.getByLabelText(form.noticeTitle), { target: { value: "Water cut on Sunday" } });
    await submit(form.save);

    expect(api.updateNotice).toHaveBeenCalledWith(expect.any(String), { title: "Water cut on Sunday" });
  });

  test("saving without a change sends nothing", async () => {
    renderWithMessages(<NoticeFormSheet initial={notice()} defaultProperty={null} onClose={onClose} />);

    await submit(form.save);

    expect(api.updateNotice).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  test("editing an auto-generated holiday notice warns that it stops following the holiday", async () => {
    const auto = notice({ is_auto_text: true, food_holiday: "h1" });
    renderWithMessages(<NoticeFormSheet initial={auto} defaultProperty={null} onClose={onClose} />);

    expect(screen.queryByText(form.autoTextHint)).toBeNull();
    fireEvent.change(screen.getByLabelText(form.body), { target: { value: "Changed." } });
    expect(screen.getByText(form.autoTextHint)).toBeTruthy();
  });
});
