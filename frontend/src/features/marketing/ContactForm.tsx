"use client";

import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ApiError, apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Every string the form shows, translated by the server component that renders it
 * (marketing messages are not in the client provider; same approach as LanguageSwitcher). */
export interface ContactFormLabels {
  name: string;
  email: string;
  phone: string;
  phoneOptional: string;
  message: string;
  submit: string;
  submitting: string;
  successTitle: string;
  successBody: string;
  sendAnother: string;
  errorThrottled: string;
  errorNetwork: string;
  errorGeneric: string;
  honeypotLabel: string;
  validation: {
    nameRequired: string;
    emailInvalid: string;
    phoneInvalid: string;
    messageShort: string;
    messageLong: string;
  };
}

export const CONTACT_LIMITS = { nameMin: 2, nameMax: 100, messageMin: 10, messageMax: 2000 } as const;
const PHONE_SHAPE = /^\+?[0-9 ]{7,20}$/;

/** Mirrors the backend ContactMessageSerializer, so most mistakes are caught before a request. */
export function buildContactSchema(v: ContactFormLabels["validation"]) {
  return z.object({
    name: z.string().trim().min(CONTACT_LIMITS.nameMin, v.nameRequired).max(CONTACT_LIMITS.nameMax, v.nameRequired),
    email: z.string().trim().email(v.emailInvalid).max(254, v.emailInvalid),
    phone: z
      .string()
      .trim()
      .refine((value) => {
        if (value === "") return true;
        const digits = value.replace(/ /g, "").replace(/^\+/, "");
        return PHONE_SHAPE.test(value) && digits.length >= 7 && digits.length <= 15;
      }, v.phoneInvalid),
    message: z
      .string()
      .trim()
      .min(CONTACT_LIMITS.messageMin, v.messageShort)
      .max(CONTACT_LIMITS.messageMax, v.messageLong),
  });
}

type FieldName = "name" | "email" | "phone" | "message";
/** `type` of an error that came from the API, as opposed to the client-side schema. */
const SERVER_ERROR = "server";
const FIELDS: FieldName[] = ["name", "email", "phone", "message"];
type FormValues = z.infer<ReturnType<typeof buildContactSchema>>;

const inputClass =
  "w-full rounded-xl border border-border bg-surface-card px-3 py-2.5 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15 aria-[invalid=true]:border-status-critical";
const labelClass = "text-xs font-semibold uppercase tracking-wider text-ink-muted";

type FormErrorKind = "errorNetwork" | "errorThrottled" | "errorGeneric";

export function ContactForm({ labels }: { labels: ContactFormLabels }) {
  // Rebuilt when the language changes: router.refresh() keeps this component's state
  // but hands it new translated labels, so a schema frozen at mount would keep
  // producing messages in the previous language.
  const { nameRequired, emailInvalid, phoneInvalid, messageShort, messageLong } = labels.validation;
  const schema = useMemo(
    () => buildContactSchema({ nameRequired, emailInvalid, phoneInvalid, messageShort, messageLong }),
    [nameRequired, emailInvalid, phoneInvalid, messageShort, messageLong]
  );
  const [sent, setSent] = useState(false);
  // Kept as a key, not a string, so it follows the language too.
  const [formError, setFormError] = useState<FormErrorKind | null>(null);
  // Honeypot, kept outside react-hook-form: a real visitor never sees or fills it.
  // The input name is deliberately not "website"/"url", which browsers autofill.
  const [trap, setTrap] = useState("");

  const {
    register,
    handleSubmit,
    reset,
    setError,
    trigger,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", phone: "", message: "" },
  });

  // Errors already on screen were produced by the old schema; re-run the fields that
  // show one so their text switches to the new language straight away. Errors the
  // server returned are left alone: re-running the client schema would find the value
  // acceptable and silently clear a rejection the server still stands by.
  const erroredFields = FIELDS.filter((field) => errors[field] && errors[field]?.type !== SERVER_ERROR).join(",");
  useEffect(() => {
    if (erroredFields) void trigger(erroredFields.split(",") as FieldName[]);
    // Only when the schema (i.e. the language) changes, not on every error change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, trigger]);

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await apiFetch("/api/v1/public/contact/", {
        method: "POST",
        body: JSON.stringify({ ...values, website: trap }),
        skipAuth: true,
      });
      reset();
      setTrap("");
      setSent(true);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status === 0) {
        setFormError("errorNetwork");
      } else if (error.status === 429) {
        setFormError("errorThrottled");
      } else {
        let mapped = false;
        for (const field of FIELDS) {
          const message = error.fieldError(field);
          if (message) {
            setError(field, { type: SERVER_ERROR, message });
            mapped = true;
          }
        }
        if (!mapped) setFormError("errorGeneric");
      }
    }
  });

  if (sent) {
    return (
      <div role="status" className="rounded-2xl border border-status-good/30 bg-status-good-soft p-6">
        <h3 className="text-lg font-bold text-status-good">{labels.successTitle}</h3>
        <p className="mt-2 text-sm text-ink">{labels.successBody}</p>
        <button
          type="button"
          onClick={() => setSent(false)}
          className="mt-4 rounded-xl border border-border-strong bg-surface-card px-4 py-2 text-sm font-semibold text-ink hover:bg-surface-subtle"
        >
          {labels.sendAnother}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor="contact-name" className={labelClass}>
            {labels.name}
          </label>
          <input
            id="contact-name"
            autoComplete="name"
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? "contact-name-error" : undefined}
            className={inputClass}
            {...register("name")}
          />
          {errors.name && (
            <p id="contact-name-error" className="text-xs text-status-critical">
              {errors.name.message}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="contact-email" className={labelClass}>
            {labels.email}
          </label>
          <input
            id="contact-email"
            type="email"
            autoComplete="email"
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? "contact-email-error" : undefined}
            className={inputClass}
            {...register("email")}
          />
          {errors.email && (
            <p id="contact-email-error" className="text-xs text-status-critical">
              {errors.email.message}
            </p>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="contact-phone" className={labelClass}>
          {labels.phone} <span className="font-normal normal-case tracking-normal">({labels.phoneOptional})</span>
        </label>
        <input
          id="contact-phone"
          type="tel"
          autoComplete="tel"
          aria-invalid={Boolean(errors.phone)}
          aria-describedby={errors.phone ? "contact-phone-error" : undefined}
          className={inputClass}
          {...register("phone")}
        />
        {errors.phone && (
          <p id="contact-phone-error" className="text-xs text-status-critical">
            {errors.phone.message}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <label htmlFor="contact-message" className={labelClass}>
          {labels.message}
        </label>
        <textarea
          id="contact-message"
          rows={5}
          maxLength={CONTACT_LIMITS.messageMax}
          aria-invalid={Boolean(errors.message)}
          aria-describedby={errors.message ? "contact-message-error" : undefined}
          className={cn(inputClass, "resize-y")}
          {...register("message")}
        />
        {errors.message && (
          <p id="contact-message-error" className="text-xs text-status-critical">
            {errors.message.message}
          </p>
        )}
      </div>

      {/* Honeypot: off-screen, unreachable by keyboard, hidden from assistive tech. */}
      <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
        <label htmlFor="contact-extra">{labels.honeypotLabel}</label>
        <input
          id="contact-extra"
          name="contact-extra"
          tabIndex={-1}
          autoComplete="off"
          value={trap}
          onChange={(event) => setTrap(event.target.value)}
        />
      </div>

      {formError && (
        <p role="alert" className="rounded-xl bg-status-critical-soft px-4 py-3 text-sm font-medium text-status-critical">
          {labels[formError]}
        </p>
      )}

      <button
        type="submit"
        disabled={isSubmitting}
        className="inline-flex h-12 w-full items-center justify-center rounded-xl bg-accent px-6 text-base font-semibold text-ink-inverse shadow-sm hover:bg-accent-hover disabled:opacity-60 sm:w-auto"
      >
        {isSubmitting ? labels.submitting : labels.submit}
      </button>
    </form>
  );
}
