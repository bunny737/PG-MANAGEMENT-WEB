import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import common from "@/messages/en/common.json";
import dashboard from "@/messages/en/dashboard.json";
import properties from "@/messages/en/properties.json";
import pwa from "@/messages/en/pwa.json";
import residents from "@/messages/en/residents.json";
import status from "@/messages/en/status.json";
import vacancies from "@/messages/en/vacancies.json";

const LOCALE = "en";

export const EN_MESSAGES = { common, dashboard, properties, pwa, residents, status, vacancies };

/** Renders with the English catalogs and a fresh, non-retrying TanStack client. */
export function renderWithIntl(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale={LOCALE} messages={EN_MESSAGES}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}
