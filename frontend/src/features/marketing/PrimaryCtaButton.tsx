import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { getSiteConfig } from "@/lib/site-config";
import { resolvePrimaryCta } from "./cta";
import { getSupportContacts } from "./data/support";

/** The one main call-to-action. Early access (WhatsApp / email / contact page)
 * until signup exists, then "Start free trial" — flipped by SIGNUP_ENABLED. */
export async function PrimaryCtaButton({
  variant = "primary",
  size = "lg",
  className,
}: {
  variant?: "primary" | "inverse";
  size?: "md" | "lg";
  className?: string;
}) {
  const [t, support] = await Promise.all([getTranslations("marketing.cta"), getSupportContacts()]);
  const { signupEnabled } = getSiteConfig();
  const cta = resolvePrimaryCta({
    signupEnabled,
    support,
    message: t("whatsappMessage"),
    subject: t("emailSubject"),
  });

  return (
    <ButtonLink href={cta.href} external={cta.external} variant={variant} size={size} className={className}>
      {signupEnabled ? t("startTrial") : t("requestAccess")}
    </ButtonLink>
  );
}
