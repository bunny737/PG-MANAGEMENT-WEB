/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  state: {
    ready: true,
    authenticated: true,
    validated: false,
    role: "owner" as string | null,
    permissions: ["view_dashboard"] as string[],
  },
  ensureFreshSession: vi.fn(),
}));

vi.mock("@/lib/session", () => ({
  useSession: () => session.state,
  ensureFreshSession: session.ensureFreshSession,
}));
vi.mock("@/lib/permissions", () => ({ firstAllowedRoute: () => "/dashboard" }));
vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import { AuthAwareLink } from "../AuthAwareLink";

const link = () => screen.getByRole("link");
// A fresh element per call: re-rendering the same element object is a no-op in React.
const ui = () => <AuthAwareLink loginLabel="Log in" dashboardLabel="Open dashboard" />;

describe("AuthAwareLink", () => {
  beforeEach(() => {
    session.state = {
      ready: true,
      authenticated: true,
      validated: false,
      role: "owner",
      permissions: ["view_dashboard"],
    };
    session.ensureFreshSession.mockReset();
    session.ensureFreshSession.mockResolvedValue(null);
  });

  it("does not trust a cached session that /auth/me/ has not confirmed", () => {
    render(ui());
    expect(link().textContent).toBe("Log in");
    expect(link().getAttribute("href")).toBe("/login");
    expect(session.ensureFreshSession).toHaveBeenCalledTimes(1);
  });

  it("offers the dashboard once the store reports the session as validated", () => {
    session.state = { ...session.state, validated: true };
    render(ui());
    expect(link().textContent).toBe("Open dashboard");
    expect(link().getAttribute("href")).toBe("/dashboard");
    expect(session.ensureFreshSession).not.toHaveBeenCalled();
  });

  it("recovers on the same mounted component when a later refresh succeeds", () => {
    const { rerender } = render(ui());
    expect(link().textContent).toBe("Log in"); // first check failed (mock resolves null)

    // e.g. a focus-triggered refresh succeeds: the shared store flips `validated`.
    session.state = { ...session.state, validated: true };
    rerender(ui());

    expect(link().textContent).toBe("Open dashboard");
    expect(session.ensureFreshSession).toHaveBeenCalledTimes(1); // no retry loop
  });

  it("drops back to Log in when the store loses validation (logout)", () => {
    session.state = { ...session.state, validated: true };
    const { rerender } = render(ui());
    expect(link().textContent).toBe("Open dashboard");

    session.state = { ...session.state, authenticated: false, validated: false, role: null };
    rerender(ui());
    expect(link().textContent).toBe("Log in");
  });

  it("never offers the dashboard to roles without a portal shell", () => {
    session.state = { ...session.state, validated: true, role: "resident" };
    render(ui());
    expect(link().textContent).toBe("Log in");
  });

  it("does not call /auth/me/ for anonymous visitors", () => {
    session.state = { ...session.state, authenticated: false, role: null };
    render(ui());
    expect(session.ensureFreshSession).not.toHaveBeenCalled();
    expect(link().textContent).toBe("Log in");
  });
});
