import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { EmptyState } from "@/components/shared/EmptyState";
import type { OnboardingChecklist, OnboardingStep, TutorialVideo } from "@/lib/api";
import { firstAllowedRoute } from "@/lib/permissions";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { Users } from "lucide-react";
import { FallbackLanguageNote } from "../FallbackLanguageNote";
import { GettingStartedCard } from "../GettingStartedCard";
import { HelpPage, videoLanguageOptions } from "../HelpPage";
import { stepHref } from "../routes";
import { VideoPlayerDialog } from "../VideoPlayerDialog";

const state = vi.hoisted(() => ({
  permissions: new Set<string>(),
  propertyId: null as string | null,
  user: { id: "u1", tenant_id: "t1" } as Record<string, unknown>,
  api: {
    getOnboardingChecklist: vi.fn(),
    dismissOnboarding: vi.fn(),
    restoreOnboarding: vi.fn(),
    listTutorialVideos: vi.fn(),
  },
  afterOnboardingDismissChange: vi.fn(),
}));

vi.mock("@/lib/session", () => ({
  useSession: () => ({
    ready: true,
    authenticated: true,
    role: "owner",
    userName: "Owner",
    user: state.user,
    can: (code: string) => state.permissions.has(code),
  }),
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({ propertyId: state.propertyId, properties: [], listLoaded: true }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...state.api,
}));
vi.mock("@/lib/refresh", () => ({
  afterOnboardingDismissChange: state.afterOnboardingDismissChange,
}));

const P = "p1";

function step(key: OnboardingStep["key"], overrides: Partial<OnboardingStep> = {}): OnboardingStep {
  return {
    key,
    required: key !== "record_expense",
    done: false,
    permitted: true,
    blocked_by: null,
    params: { property_id: P },
    video_topic: key === "record_expense" ? "expenses" : key,
    ...overrides,
  };
}

function checklist(overrides: Partial<OnboardingChecklist> = {}): OnboardingChecklist {
  return {
    status: "in_progress",
    dismissed: false,
    target_property: { id: P, name: "Greenwood" },
    progress: { done: 2, total: 5 },
    next_step: "add_floor",
    steps: [
      step("add_property", { done: true, params: {} }),
      step("add_building", { done: true }),
      step("add_floor", { params: { property_id: P, building_id: "b1" } }),
      step("add_room", { blocked_by: "add_floor" }),
      step("admit_resident", { blocked_by: "add_floor" }),
      step("record_expense"),
    ],
    ...overrides,
  };
}

function video(overrides: Partial<TutorialVideo> = {}): TutorialVideo {
  return {
    topic: "add_property",
    language: "en",
    title: "Add your property",
    description: "",
    youtube_id: "dQw4w9WgXcQ",
    duration_seconds: 120,
    ...overrides,
  };
}

const card = () => screen.findByRole("region", { name: /Set up|all set/i });
const linkHrefs = (root: HTMLElement) =>
  within(root).queryAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]);

beforeEach(() => {
  state.permissions = new Set(["manage_properties", "manage_rooms_beds", "manage_admissions", "manage_expenses"]);
  state.propertyId = null;
  state.user = { id: "u1", tenant_id: "t1" };
  Object.values(state.api).forEach((fn) => fn.mockReset());
  state.afterOnboardingDismissChange.mockReset();
  state.api.listTutorialVideos.mockResolvedValue({ requested_language: "en", available_languages: ["en"], videos: [] });
  state.api.dismissOnboarding.mockResolvedValue(undefined);
});

afterEach(() => onlineManager.setOnline(true));

describe("GettingStartedCard visibility", () => {
  test("in_progress shows the checklist with server progress", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(checklist());
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    expect(within(region).getByText("Set up Greenwood")).toBeTruthy();
    expect(within(region).getByText("2 of 5 steps done")).toBeTruthy();
    expect(within(region).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("40");
  });

  test.each([
    ["dismissed", checklist({ dismissed: true })],
    ["dismissed and completed", checklist({ dismissed: true, status: "completed" })],
    ["no_actions", checklist({ status: "no_actions", next_step: null })],
  ])("%s renders nothing", async (_label, data) => {
    state.api.getOnboardingChecklist.mockResolvedValue(data);
    const { container } = renderWithIntl(<GettingStartedCard />);
    await waitFor(() => expect(state.api.getOnboardingChecklist).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.textContent).toBe("");
  });

  test("completed (e.g. restored after finishing) shows All set until the user hides it", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(
      checklist({ status: "completed", next_step: null, progress: { done: 5, total: 5 } })
    );
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    expect(within(region).getByText("You're all set")).toBeTruthy();
    expect(state.api.dismissOnboarding).not.toHaveBeenCalled();
    fireEvent.click(within(region).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(state.api.dismissOnboarding).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(state.afterOnboardingDismissChange).toHaveBeenCalled());
  });

  test("a profile already marked dismissed never fetches", () => {
    state.user = { id: "u1", tenant_id: "t1", onboarding_dismissed: true };
    const { container } = renderWithIntl(<GettingStartedCard />);
    expect(container.textContent).toBe("");
    expect(state.api.getOnboardingChecklist).not.toHaveBeenCalled();
  });

  test("hiding asks first, then dismisses and refreshes", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(checklist());
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    fireEvent.click(within(region).getByRole("button", { name: "Hide checklist" }));
    expect(state.api.dismissOnboarding).not.toHaveBeenCalled();
    fireEvent.click(within(region).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(state.api.dismissOnboarding).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(state.afterOnboardingDismissChange).toHaveBeenCalled());
  });
});

describe("GettingStartedCard rows", () => {
  test("All properties: the request has no property and CTAs come from the response params", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(checklist());
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    expect(state.api.getOnboardingChecklist).toHaveBeenCalledWith(null);
    expect(linkHrefs(region)).toEqual([
      ["Add floor", `/properties/${P}/buildings/b1/floors/add`],
      ["Add expense", `/expenses?property=${P}`], // open before the first admission
    ]);
  });

  test("blocked steps say what they wait for and have no CTA", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(checklist());
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    expect(within(region).getAllByText("After: Add a floor")).toHaveLength(2);
    expect(within(region).queryByRole("link", { name: "Add room" })).toBeNull();
  });

  test("not permitted: Ask your owner when not done, a plain tick when done", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(
      checklist({
        progress: { done: 1, total: 4 },
        steps: [
          step("add_property", { done: true, permitted: false, params: {} }),
          step("add_building", { done: true }),
          step("add_floor", { params: { property_id: P, building_id: "b1" } }),
          step("add_room", { blocked_by: "add_floor", permitted: false }),
          step("admit_resident", { blocked_by: "add_floor" }),
          step("record_expense"),
        ],
      })
    );
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    expect(within(region).getAllByText("Ask your owner")).toHaveLength(1); // add_room only
    const propertyRow = within(region).getByText("Add your property").closest("li")!;
    expect(within(propertyRow).queryByText("Ask your owner")).toBeNull();
  });

  test("generic heading without a target property", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(
      checklist({
        target_property: null,
        progress: { done: 0, total: 5 },
        next_step: "add_property",
        steps: [
          step("add_property", { params: {} }),
          ...(["add_building", "add_floor", "add_room", "admit_resident", "record_expense"] as const).map((key) =>
            step(key, { blocked_by: "add_property", params: {} })
          ),
        ],
      })
    );
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    expect(within(region).getByText("Set up your PG")).toBeTruthy();
    expect(linkHrefs(region)).toEqual([["Add property", "/properties/add"]]);
  });

  test("a done row still offers its tutorial", async () => {
    state.api.listTutorialVideos.mockResolvedValue({ requested_language: "en", available_languages: ["en"], videos: [video()] });
    state.api.getOnboardingChecklist.mockResolvedValue(checklist());
    renderWithIntl(<GettingStartedCard />);
    const region = await card();
    const propertyRow = within(region).getByText("Add your property").closest("li")!;
    expect(await within(propertyRow).findByRole("button", { name: "Watch how (2 min)" })).toBeTruthy();
  });
});

describe("EmptyState", () => {
  test("hides the CTA without the permission", () => {
    state.permissions = new Set();
    renderWithIntl(
      <EmptyState icon={Users} title="Nothing" cta={{ label: "Admit", href: "/admissions", permission: "manage_admissions" }} />
    );
    expect(screen.queryByRole("link")).toBeNull();
  });

  test("shows the CTA with the permission", () => {
    state.permissions = new Set(["manage_admissions"]);
    renderWithIntl(
      <EmptyState icon={Users} title="Nothing" cta={{ label: "Admit", href: "/admissions", permission: "manage_admissions" }} />
    );
    expect(screen.getByRole("link", { name: "Admit" }).getAttribute("href")).toBe("/admissions");
  });
});

describe("VideoPlayerDialog", () => {
  test("embeds the privacy-enhanced player online", () => {
    renderWithIntl(<VideoPlayerDialog video={video()} requestedLanguage="en" onClose={() => {}} />);
    const frame = screen.getByTitle("Add your property");
    expect(frame.getAttribute("src")).toContain("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ");
  });

  test("offline shows a notice instead of the iframe", () => {
    onlineManager.setOnline(false);
    renderWithIntl(<VideoPlayerDialog video={video()} requestedLanguage="en" onClose={() => {}} />);
    expect(screen.queryByTitle("Add your property")).toBeNull();
    expect(screen.getByText("Videos play when you're back online.")).toBeTruthy();
  });
});

describe("FallbackLanguageNote", () => {
  test("names both languages when English stands in", () => {
    renderWithIntl(<FallbackLanguageNote shown="en" requested="te" />);
    expect(screen.getByText("Shown in English — తెలుగు version coming soon.")).toBeTruthy();
  });

  test("nothing when the language matches", () => {
    const { container } = renderWithIntl(<FallbackLanguageNote shown="te" requested="te" />);
    expect(container.textContent).toBe("");
  });
});

describe("routes", () => {
  test("each step maps to its screen from the server params", () => {
    expect(stepHref(step("add_property", { params: {} }))).toBe("/properties/add");
    expect(stepHref(step("add_building"))).toBe(`/properties/${P}/buildings/add`);
    expect(stepHref(step("add_floor", { params: { property_id: P, building_id: "b1" } }))).toBe(
      `/properties/${P}/buildings/b1/floors/add`
    );
    expect(stepHref(step("add_room", { params: { property_id: P, floor_id: "f1" } }))).toBe(
      `/properties/${P}/floors/f1/rooms/add`
    );
    expect(stepHref(step("admit_resident"))).toBe(`/admissions?property=${P}`);
    expect(stepHref(step("record_expense"))).toBe(`/expenses?property=${P}`);
    expect(stepHref(step("add_floor"))).toBeNull(); // no building id yet
  });

  test("Help is never a landing page", () => {
    expect(firstAllowedRoute([])).toBe("/profile");
  });
});

describe("Help video languages", () => {
  test("options follow the catalog, not which UI translations are live", () => {
    // hi and ta have videos but no live UI; te is live but has no videos and isn't the UI language here.
    expect(videoLanguageOptions(["en", "hi", "ta"], "en").map((o) => o.code)).toEqual(["en", "hi", "ta"]);
    // The UI language and English are always offered (English stands in for missing topics).
    expect(videoLanguageOptions([], "te").map((o) => o.code)).toEqual(["en", "te"]);
  });

  test("a language with videos is selectable and fetched even though its UI isn't live", async () => {
    state.api.getOnboardingChecklist.mockResolvedValue(checklist());
    state.api.listTutorialVideos.mockImplementation(async (language: string) => ({
      requested_language: language,
      available_languages: ["en", "hi"],
      videos: [video({ language: language === "hi" ? "hi" : "en", title: `Video ${language}` })],
    }));
    renderWithIntl(<HelpPage />);
    const picker = await screen.findByRole("combobox");
    await waitFor(() => expect(within(picker).getByRole("option", { name: "हिंदी" })).toBeTruthy());
    fireEvent.change(picker, { target: { value: "hi" } });
    await waitFor(() => expect(state.api.listTutorialVideos).toHaveBeenCalledWith("hi"));
    expect(await screen.findByText("Video hi")).toBeTruthy();
  });
});
