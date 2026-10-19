import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { COOKIE_NAME, isValidLocale } from '@/i18n/locale';
import { DEFAULT_LOCALE } from '@/i18n/config';
import { SESSION_COOKIE } from '@/lib/server/bff';

// Signed-out visitors may only see these. UX only — the API is the real authority.
const PUBLIC_PATHS = ['/', '/login', '/~offline'];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // The session marker (set by the login route handlers) carries no secret; it only lets
  // page navigations, which never carry the /api-scoped token cookies, bounce to /login early.
  if (!PUBLIC_PATHS.includes(pathname) && !request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

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
// `api/` is skipped so the BFF proxy's request bodies (uploads) never pass through here;
// the service worker, manifest and icons are static and must load for signed-out users.
export const config = {
  matcher: [
    '/((?!$|api/|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|opengraph-image|icon|apple-icon|sw.js|swe-worker|manifest.webmanifest|icons/|(?:features|pricing|app|contact|privacy|terms)(?:/|$)|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
