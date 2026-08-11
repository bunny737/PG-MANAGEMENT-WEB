import { getRequestConfig } from 'next-intl/server';
import { cookies } from 'next/headers';
import { COOKIE_NAME, isValidLocale } from './locale';
import { DEFAULT_LOCALE } from './config';

export const MODULES = [
  'common',
  'auth',
  'settings',
  'properties',
  'residents',
  'admissions',
  'billing',
  'payments',
  'complaints',
  'dashboard',
  'status',
];

async function loadMessages(locale: string) {
  const messages: Record<string, Record<string, unknown>> = {};

  for (const mod of MODULES) {
    let enModule: Record<string, unknown> = {};
    try {
      enModule = (await import(`../messages/en/${mod}.json`)).default;
    } catch {
      enModule = {};
    }

    let targetModule: Record<string, unknown> = {};
    if (locale !== 'en') {
      try {
        targetModule = (await import(`../messages/${locale}/${mod}.json`)).default;
      } catch {
        targetModule = {};
      }
    }

    messages[mod] = { ...enModule, ...targetModule };
  }

  return messages;
}

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const rawLocale = cookieStore.get(COOKIE_NAME)?.value;
  const locale = rawLocale && isValidLocale(rawLocale) ? rawLocale : DEFAULT_LOCALE;

  return {
    locale,
    messages: await loadMessages(locale),
  };
});
