import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { COOKIE_NAME, isValidLocale } from '@/i18n/locale';
import { DEFAULT_LOCALE } from '@/i18n/config';

export function proxy(request: NextRequest) {
  const response = NextResponse.next();
  const localeCookie = request.cookies.get(COOKIE_NAME)?.value;

  if (!localeCookie || !isValidLocale(localeCookie)) {
    response.cookies.set(COOKIE_NAME, DEFAULT_LOCALE, {
      path: '/',
      maxAge: 31536000,
      sameSite: 'lax',
    });
  }

  return response;
}

// The public marketing pages are skipped: they must not hand every anonymous
// visitor a Set-Cookie. They render in the default language until the visitor
// picks one with the language switcher (which writes the cookie itself).
// NOTE: this keeps responses cookie-free but does not make them CDN-cacheable;
// pages are still rendered per request because the locale comes from cookies().
export const config = {
  matcher: [
    '/((?!$|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|opengraph-image|icon|apple-icon|(?:features|pricing|app|contact|privacy|terms)(?:/|$)|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
