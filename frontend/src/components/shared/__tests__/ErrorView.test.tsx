import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { ErrorView } from "../ErrorView";

const COPY = { title: "Something went wrong", body: "Please try again.", retry: "Try again", home: "Go home" };

describe("ErrorView", () => {
  test("shows the copy, retries on click, and links home with a plain anchor", () => {
    const onRetry = vi.fn();
    render(<ErrorView copy={COPY} onRetry={onRetry} />);
    expect(screen.getByRole("heading", { name: COPY.title })).toBeTruthy();
    expect(screen.getByText(COPY.body)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: COPY.retry }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: COPY.home }).getAttribute("href")).toBe("/");
  });

  test("shows a support reference only when there is one", () => {
    const { rerender } = render(<ErrorView copy={COPY} onRetry={() => {}} />);
    expect(screen.queryByText(/Reference:/)).toBeNull();
    rerender(<ErrorView copy={COPY} reference="Reference: 4821" onRetry={() => {}} />);
    expect(screen.getByText("Reference: 4821")).toBeTruthy();
  });
});
