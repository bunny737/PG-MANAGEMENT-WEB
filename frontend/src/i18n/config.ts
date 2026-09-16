export interface LanguageOption {
  code: 'en' | 'hi' | 'te' | 'ta' | 'ml';
  name: string;
  nativeName: string;
  region: string;
  script: string;
  status: 'active' | 'v2' | 'v3';
}

export const DEFAULT_LOCALE = 'en';

export const LOCALES: LanguageOption[] = [
  {
    code: 'en',
    name: 'English',
    nativeName: 'English',
    region: 'Default / All',
    script: 'Latin',
    status: 'active',
  },
  {
    code: 'hi',
    name: 'Hindi',
    nativeName: 'हिंदी',
    region: 'North India',
    script: 'Devanagari',
    status: 'v2',
  },
  {
    code: 'te',
    name: 'Telugu',
    nativeName: 'తెలుగు',
    region: 'Andhra Pradesh, Telangana',
    script: 'Telugu',
    status: 'active',
  },
  {
    code: 'ta',
    name: 'Tamil',
    nativeName: 'தமிழ்',
    region: 'Tamil Nadu',
    script: 'Tamil',
    status: 'v3',
  },
  {
    code: 'ml',
    name: 'Malayalam',
    nativeName: 'മലയാളം',
    region: 'Kerala',
    script: 'Malayalam',
    status: 'v3',
  },
];

export const SUPPORTED_LANGUAGES = LOCALES;

export function isActiveLocale(code: string): boolean {
  const lang = LOCALES.find((l) => l.code === code);
  return lang ? lang.status === 'active' : false;
}

export function getLocaleDirection(locale: string): 'ltr' | 'rtl' {
  const rtlLocales = ['ar', 'he', 'fa', 'ur', 'dv', 'ps', 'sd', 'yi'];
  return rtlLocales.includes(locale.toLowerCase()) ? 'rtl' : 'ltr';
}

export function getLanguageSelectLabel(lang: LanguageOption): string {
  if (lang.code === 'en') {
    return lang.name;
  }
  const statusBadge = lang.status !== 'active' ? ` - ${lang.status.toUpperCase()} (Coming Soon)` : '';
  return `${lang.nativeName} (${lang.name})${statusBadge}`;
}
