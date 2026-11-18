import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { DatePicker } from "../DatePicker";

describe("DatePicker", () => {
  test("renders formatted display value in DD-MM-YYYY when given an ISO string", () => {
    render(<DatePicker value="2026-11-01" />);
    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input.value).toBe("01-11-2026");
  });

  test("opens calendar popup when clicking calendar icon button", () => {
    render(<DatePicker value="2026-11-01" />);
    expect(screen.queryByRole("dialog", { name: "Calendar date picker" })).not.toBeInTheDocument();

    const toggleBtn = screen.getByRole("button", { name: "Toggle calendar" });
    fireEvent.click(toggleBtn);

    expect(screen.getByRole("dialog", { name: "Calendar date picker" })).toBeInTheDocument();
  });

  test("selects date from calendar and calls onChange with ISO YYYY-MM-DD", () => {
    const handleChange = vi.fn();
    render(<DatePicker value="2026-11-01" onChange={handleChange} />);

    // Open calendar
    fireEvent.click(screen.getByRole("button", { name: "Toggle calendar" }));

    // Find and click day 15
    const day15 = screen.getByRole("button", { name: "15" });
    fireEvent.click(day15);

    expect(handleChange).toHaveBeenCalledWith("2026-11-15");
    // Calendar closes on select
    expect(screen.queryByRole("dialog", { name: "Calendar date picker" })).not.toBeInTheDocument();
  });

  test("clears date when clicking Clear button", () => {
    const handleChange = vi.fn();
    render(<DatePicker value="2026-11-01" onChange={handleChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Toggle calendar" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(handleChange).toHaveBeenCalledWith("");
    expect(screen.queryByRole("dialog", { name: "Calendar date picker" })).not.toBeInTheDocument();
  });

  test("handles manual typing in DD-MM-YYYY format", () => {
    const handleChange = vi.fn();
    render(<DatePicker value="" onChange={handleChange} />);

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "05-12-2026" } });

    expect(handleChange).toHaveBeenCalledWith("2026-12-05");
  });
});
