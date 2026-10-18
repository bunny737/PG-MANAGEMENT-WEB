"use client";

import { MessageCircle, MessageSquare, Phone } from "lucide-react";
import { useTranslations } from "next-intl";
import { normalizePhoneE164, toDialDigits } from "@/lib/phone";
import { cn } from "@/lib/utils";

interface ContactActionsProps {
  /** Raw phone number as stored (e.g. "9876543210"); normalized here. */
  phone: string | null | undefined;
  className?: string;
}

/** Call / WhatsApp / SMS, next to a resident's phone number (Phase 1).
 * An invalid or missing number disables every action rather than hiding
 * them, so the row layout stays stable. */
export function ContactActions({ phone, className }: ContactActionsProps) {
  const t = useTranslations("common");
  const e164 = phone ? normalizePhoneE164(phone) : null;
  const disabled = !e164;
  const digits = e164 ? toDialDigits(e164) : "";

  const actions = [
    { key: "call", Icon: Phone, href: e164 ? `tel:${e164}` : undefined, external: false },
    { key: "whatsapp", Icon: MessageCircle, href: e164 ? `https://wa.me/${digits}` : undefined, external: true },
    { key: "sms", Icon: MessageSquare, href: e164 ? `sms:${e164}` : undefined, external: false },
  ] as const;

  return (
    <div className={cn("flex items-center gap-1.5", className)} role="group" aria-label={t("contactActions.group")}>
      {actions.map(({ key, Icon, href, external }) => (
        <a
          key={key}
          href={href}
          target={external ? "_blank" : undefined}
          rel={external ? "noopener noreferrer" : undefined}
          aria-disabled={disabled}
          onClick={disabled ? (event) => event.preventDefault() : undefined}
          title={t(`contactActions.${key}`)}
          className={cn(
            "flex size-8 items-center justify-center rounded-lg border border-border text-ink-muted transition-colors",
            disabled
              ? "cursor-not-allowed opacity-40"
              : "hover:bg-surface-subtle hover:text-ink cursor-pointer"
          )}
        >
          <Icon className="size-4" aria-hidden />
        </a>
      ))}
    </div>
  );
}
