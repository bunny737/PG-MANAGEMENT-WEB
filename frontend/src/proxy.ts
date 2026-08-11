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

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'],
};
