import Link from "next/link";
import { Menu, X } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { PrimaryCtaButton } from "@/features/marketing/PrimaryCtaButton";
import { AuthAwareLink } from "./AuthAwareLink";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { Logo } from "./Logo";
import { Container } from "./Section";

const NAV = [
  { href: "/features", key: "features" },
  { href: "/pricing", key: "pricing" },
  { href: "/app", key: "app" },
  { href: "/contact", key: "contact" },
] as const;

export async function MarketingHeader() {
  const t = await getTranslations("marketing");

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-surface-card/90 backdrop-blur">
      <Container className="flex h-16 items-center justify-between gap-4">
        <Logo name={t("brand.name")} homeLabel={t("nav.home")} />

        <nav aria-label={t("nav.primary")} className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-lg px-3 py-2 text-sm font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink"
            >
              {t(`nav.${item.key}`)}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <LanguageSwitcher label={t("nav.language")} />
          <AuthAwareLink loginLabel={t("nav.login")} dashboardLabel={t("nav.openDashboard")} />
          <PrimaryCtaButton size="md" />
        </div>

        {/* No-JS mobile menu: a <details> keeps the header a server component. */}
        <details className="group relative md:hidden">
          <summary
            aria-label={t("nav.menu")}
            className="flex size-10 cursor-pointer list-none items-center justify-center rounded-xl border border-border-strong text-ink [&::-webkit-details-marker]:hidden"
          >
            <Menu className="size-5 group-open:hidden" aria-hidden="true" />
            <X className="hidden size-5 group-open:block" aria-hidden="true" />
          </summary>
          <div className="absolute right-0 mt-2 w-72 rounded-2xl border border-border bg-surface-card p-4 shadow-lg">
            <nav aria-label={t("nav.primary")} className="flex flex-col">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-lg px-3 py-2.5 text-sm font-medium text-ink hover:bg-surface-subtle"
                >
                  {t(`nav.${item.key}`)}
                </Link>
              ))}
            </nav>
            <div className="mt-3 flex flex-col gap-3 border-t border-border pt-3">
              <LanguageSwitcher label={t("nav.language")} />
              <AuthAwareLink
                loginLabel={t("nav.login")}
                dashboardLabel={t("nav.openDashboard")}
                className="px-3"
              />
              <PrimaryCtaButton size="md" className="w-full" />
            </div>
          </div>
        </details>
      </Container>
    </header>
  );
}
