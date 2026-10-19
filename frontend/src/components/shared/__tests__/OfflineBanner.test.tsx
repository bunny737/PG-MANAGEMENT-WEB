import { act, render, screen } from "@testing-library/react";
import { onlineManager } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, test } from "vitest";
import en from "@/messages/en/pwa.json";
import { OfflineBanner } from "../OfflineBanner";

const LOCALE = "en";

function renderBanner() {
  return render(
    <NextIntlClientProvider locale={LOCALE} messages={{ pwa: en }}>
      <OfflineBanner />
    </NextIntlClientProvider>
  );
}

describe("OfflineBanner", () => {
  afterEach(() => {
    act(() => onlineManager.setOnline(true));
  });

  test("renders nothing while online", () => {
    renderBanner();
    expect(screen.queryByRole("status")).toBeNull();
  });

  test("appears when the connection drops and disappears when it returns", () => {
    renderBanner();
    act(() => onlineManager.setOnline(false));
    expect(screen.getByRole("status").textContent).toContain(en.offline.banner);

    act(() => onlineManager.setOnline(true));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
