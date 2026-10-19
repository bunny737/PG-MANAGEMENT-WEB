import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { formatPhone, getSupportContacts, telHref } from "@/features/marketing/data/support";
import { getSiteConfig } from "@/lib/site-config";
import { Logo } from "./Logo";
import { Container } from "./Section";

const PRODUCT_LINKS = [
  { href: "/features", key: "features" },
  { href: "/pricing", key: "pricing" },
  { href: "/app", key: "app" },
] as const;

export async function MarketingFooter() {
  const [t, support] = await Promise.all([getTranslations("marketing"), getSupportContacts()]);
  const { company } = getSiteConfig();
  const linkClass = "text-sm text-ink-inverse-muted hover:text-ink-inverse";

  return (
    <footer className="bg-surface-inverse text-ink-inverse">
      <Container className="grid gap-10 py-12 md:grid-cols-4">
        <div className="md:col-span-2">
          <Logo name={t("brand.name")} homeLabel={t("nav.home")} inverse />
          <p className="mt-4 max-w-sm text-sm text-ink-inverse-muted">{t("footer.about")}</p>
        </div>

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider">{t("footer.product")}</h2>
          <ul className="mt-4 space-y-2.5">
            {PRODUCT_LINKS.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className={linkClass}>
                  {t(`nav.${item.key}`)}
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider">{t("footer.company")}</h2>
          <ul className="mt-4 space-y-2.5">
            <li>
              <Link href="/contact" className={linkClass}>
                {t("nav.contact")}
              </Link>
            </li>
            {support?.email && (
              <li>
                <a href={`mailto:${support.email}`} className={linkClass}>
                  {support.email}
                </a>
              </li>
            )}
            {support?.phone && (
              <li>
                <a href={telHref(support.phone)} className={linkClass}>
                  {formatPhone(support.phone)}
                </a>
              </li>
            )}
          </ul>
        </div>
      </Container>

      <div className="border-t border-white/10">
        <Container className="flex flex-col gap-3 py-5 text-xs text-ink-inverse-muted sm:flex-row sm:items-center sm:justify-between">
          <p>{t("footer.copyright", { year: new Date().getFullYear(), company: company.name })}</p>
          <ul className="flex gap-5">
            <li>
              <Link href="/privacy" className="hover:text-ink-inverse">
                {t("footer.privacy")}
              </Link>
            </li>
            <li>
              <Link href="/terms" className="hover:text-ink-inverse">
                {t("footer.terms")}
              </Link>
            </li>
          </ul>
        </Container>
      </div>
    </footer>
  );
}
