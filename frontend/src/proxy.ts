import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { COOKIE_NAME, isValidLocale } from '@/i18n/locale';
import { DEFAULT_LOCALE } from '@/i18n/config';
import { cspResponseHeaders, newNonce } from '@/lib/csp';
import { SESSION_COOKIE } from '@/lib/server/bff';

// Signed-out visitors may only see these. UX only — the API is the real authority.
const PUBLIC_PATHS = ['/login', '/signup', '/verify-email', '/forgot-password', '/reset-password', '/~offline'];

// The public marketing site. These pages must not hand every anonymous visitor a Set-Cookie:
// they render in the default language until the visitor picks one with the language switcher
// (which writes the cookie itself). They do get the CSP — they are the most exposed pages.
const MARKETING_PATH = /^\/(?:$|(?:features|pricing|app|contact|privacy|terms|refund-policy)(?:\/|$))/;

export function isMarketingPath(pathname: string): boolean {
  return MARKETING_PATH.test(pathname);
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const nonce = newNonce();
  const csp = cspResponseHeaders(nonce);
  const withCsp = (response: NextResponse) => {
    for (const [name, value] of Object.entries(csp)) response.headers.set(name, value);
    return response;
  };

  const marketing = isMarketingPath(pathname);

  // The session marker (set by the login route handlers) carries no secret; it only lets
  // page navigations, which never carry the /api-scoped token cookies, bounce to /login early.
  if (!marketing && !PUBLIC_PATHS.includes(pathname) && !request.cookies.has(SESSION_COOKIE)) {
    return withCsp(NextResponse.redirect(new URL('/login', request.url)));
  }

  // Next reads the nonce from the request's CSP header and applies it to its inline scripts.
  const requestHeaders = new Headers(request.headers);
  for (const [name, value] of Object.entries(csp)) {
    if (name.startsWith('Content-Security-Policy')) requestHeaders.set(name, value);
  }
  const response = withCsp(NextResponse.next({ request: { headers: requestHeaders } }));

  if (!marketing) {
    const localeCookie = request.cookies.get(COOKIE_NAME)?.value;
    if (!localeCookie || !isValidLocale(localeCookie)) {
      response.cookies.set(COOKIE_NAME, DEFAULT_LOCALE, {
        path: '/',
        maxAge: 31536000,
        sameSite: 'lax',
      });
    }
  }

  return response;
}

// Every HTML/document route runs through here (for the CSP), marketing pages included.
// NOTE: marketing responses stay cookie-free but are not CDN-cacheable; pages are rendered per
// request (the locale comes from cookies(), and the CSP nonce is per request).
// `api/` is skipped so the BFF proxy's request bodies (uploads) never pass through here;
// the service worker, manifest, icons and other static files must load for signed-out users.
export const config = {
  matcher: [
    '/((?!api/|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|opengraph-image|icon|apple-icon|sw.js|swe-worker|manifest.webmanifest|icons/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml|js|css|woff2?)$).*)',
  ],
};
