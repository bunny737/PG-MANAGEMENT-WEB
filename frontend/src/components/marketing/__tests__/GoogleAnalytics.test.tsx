import type { ComponentProps } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GoogleAnalytics } from "../GoogleAnalytics";

vi.mock("@/lib/site-config", () => ({
  getGaMeasurementId: () => "G-BT7QG7CBZN",
}));

vi.mock("next/script", () => ({
  default: ({ strategy, ...props }: ComponentProps<"script"> & { strategy?: string }) => (
    <script {...props} data-strategy={strategy} />
  ),
}));

describe("GoogleAnalytics", () => {
  it("defers both GA scripts until browser idle time", () => {
    const { container } = render(<GoogleAnalytics />);
    const scripts = [...container.querySelectorAll("script")];

    expect(scripts).toHaveLength(2);
    expect(scripts.map((script) => script.dataset.strategy)).toEqual(["lazyOnload", "lazyOnload"]);
  });
});
