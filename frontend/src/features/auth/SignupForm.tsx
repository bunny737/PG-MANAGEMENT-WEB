"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Building2, Eye, EyeOff, Globe, Loader2, Lock, Mail, Phone, User } from "lucide-react";
import { BrandMark } from "@/components/shared/BrandMark";
import { LOCALES, getLanguageSelectLabel, isActiveLocale } from "@/i18n/config";
import { readLocaleCookie } from "@/i18n/locale";
import { ApiError, signup } from "@/lib/api";
import { CheckEmailPanel } from "./CheckEmailPanel";
import { isValidEmail, normalizeInputPhone } from "./validation";

const ACTIVE_LOCALES = LOCALES.filter((locale) => isActiveLocale(locale.code));

/** Fields the backend may return a (translated) message for; shown under the matching input. */
const SERVER_FIELDS = [
  "business_name",
  "first_name",
  "last_name",
  "email",
  "phone",
  "password",
  "language_code",
] as const;

type Field = (typeof SERVER_FIELDS)[number] | "confirm_password" | "form";

/** Field keys as named constants, so JSX never carries a bare string literal (i18n lint). */
const F = {
  businessName: "business_name",
  firstName: "first_name",
  lastName: "last_name",
  email: "email",
  phone: "phone",
  password: "password",
  confirmPassword: "confirm_password",
  language: "language_code",
} as const satisfies Record<string, Field>;

/** Tenant onboarding: creates the business + Owner, then shows "check your email". Reachable by
 * URL even while SIGNUP_ENABLED hides it from the marketing site (discovery-only flag). */
export function SignupForm() {
  const t = useTranslations("auth");
  const tCommon = useTranslations("common");

  const [businessName, setBusinessName] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [language, setLanguage] = useState(() => {
    const current = readLocaleCookie();
    return isActiveLocale(current) ? current : "en";
  });

  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [sent, setSent] = useState<{ email: string; at: number } | null>(null);

  if (sent) {
    return (
      <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
        <div className="mx-auto w-full max-w-md">
          <CheckEmailPanel email={sent.email} sentAt={sent.at} />
        </div>
      </div>
    );
  }

  const validate = () => {
    const next: Partial<Record<Field, string>> = {};
    if (!businessName.trim()) next.business_name = t("signup.errBusinessNameRequired");
    if (!firstName.trim()) next.first_name = t("signup.errFirstNameRequired");
    if (!email.trim()) next.email = t("login.errEmailRequired");
    else if (!isValidEmail(email.trim())) next.email = t("login.errEmailInvalid");
    if (phone.trim() && !normalizeInputPhone(phone)) next.phone = t("login.errPhoneInvalid");
    if (!password) next.password = t("login.errPasswordRequired");
    if (password && confirmPassword !== password) next.confirm_password = t("signup.errPasswordMismatch");
    return next;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const clientErrors = validate();
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    setErrors({});
    setIsLoading(true);
    const address = email.trim();
    try {
      await signup({
        business_name: businessName.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: address,
        phone: phone.trim() ? normalizeInputPhone(phone) : null,
        password,
        language_code: language,
      });
      setSent({ email: address, at: Date.now() });
    } catch (err) {
      if (!(err instanceof ApiError) || err.status === 0) {
        setErrors({ form: t("login.errServerUnreachable") });
      } else if (err.status === 429) {
        setErrors({ form: t("checkEmail.errThrottled") });
      } else {
        // Field messages come from the backend already translated (Accept-Language).
        const serverErrors: Partial<Record<Field, string>> = {};
        for (const field of SERVER_FIELDS) {
          const message = err.fieldError(field);
          if (message) serverErrors[field] = message;
        }
        if (Object.keys(serverErrors).length === 0) {
          serverErrors.form = err.fieldError("non_field_errors") ?? err.fieldError("detail") ?? t("signup.errSignupFallback");
        }
        setErrors(serverErrors);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const inputClass = (field: Field) =>
    `w-full rounded-xl border ${
      errors[field] ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
    } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`;
  const labelClass = "text-xs font-semibold uppercase tracking-wider text-ink-muted";
  const iconClass = "absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint";
  const fieldError = (field: Field) =>
    errors[field] ? <p className="text-xs text-status-critical">{errors[field]}</p> : null;

  return (
    <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
      <div className="mx-auto w-full max-w-md space-y-8">
        <div className="flex items-center gap-2.5 lg:hidden">
          <BrandMark />
          <span className="text-lg font-bold text-ink">{tCommon("appName")}</span>
        </div>

        <div className="space-y-2">
          <h2 className="text-3xl font-extrabold tracking-tight text-ink">{t("signup.title")}</h2>
          <p className="text-sm text-ink-muted">{t("signup.subtitle")}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <label htmlFor="signup-business" className={labelClass}>{t("signup.businessNameLabel")}</label>
            <div className="relative">
              <span className={iconClass}><Building2 className="size-4.5" /></span>
              <input
                id="signup-business"
                autoComplete="organization"
                placeholder={t("signup.businessNamePlaceholder")}
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
                className={inputClass("business_name")}
                disabled={isLoading}
              />
            </div>
            {fieldError(F.businessName)}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="signup-first-name" className={labelClass}>{t("signup.firstNameLabel")}</label>
              <div className="relative">
                <span className={iconClass}><User className="size-4.5" /></span>
                <input
                  id="signup-first-name"
                  autoComplete="given-name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  className={inputClass("first_name")}
                  disabled={isLoading}
                />
              </div>
              {fieldError(F.firstName)}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="signup-last-name" className={labelClass}>{t("signup.lastNameLabel")}</label>
              <div className="relative">
                <span className={iconClass}><User className="size-4.5" /></span>
                <input
                  id="signup-last-name"
                  autoComplete="family-name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  className={inputClass("last_name")}
                  disabled={isLoading}
                />
              </div>
              {fieldError(F.lastName)}
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="signup-email" className={labelClass}>{t("login.emailLabel")}</label>
            <div className="relative">
              <span className={iconClass}><Mail className="size-4.5" /></span>
              <input
                id="signup-email"
                type="email"
                autoComplete="email"
                placeholder={t("login.emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass("email")}
                disabled={isLoading}
              />
            </div>
            {fieldError(F.email)}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="signup-phone" className={labelClass}>{t("signup.phoneLabel")}</label>
            <div className="relative">
              <span className={iconClass}><Phone className="size-4.5" /></span>
              <input
                id="signup-phone"
                type="tel"
                autoComplete="tel"
                placeholder={t("login.phonePlaceholder")}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className={inputClass("phone")}
                disabled={isLoading}
              />
            </div>
            {fieldError(F.phone)}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="signup-password" className={labelClass}>{t("login.passwordLabel")}</label>
            <div className="relative">
              <span className={iconClass}><Lock className="size-4.5" /></span>
              <input
                id="signup-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={`${inputClass("password")} pr-10`}
                disabled={isLoading}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={t("signup.togglePassword")}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink transition-colors cursor-pointer"
              >
                {showPassword ? <EyeOff className="size-4.5" /> : <Eye className="size-4.5" />}
              </button>
            </div>
            {fieldError(F.password)}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="signup-confirm-password" className={labelClass}>{t("signup.confirmPasswordLabel")}</label>
            <div className="relative">
              <span className={iconClass}><Lock className="size-4.5" /></span>
              <input
                id="signup-confirm-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={inputClass("confirm_password")}
                disabled={isLoading}
              />
            </div>
            {fieldError(F.confirmPassword)}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="signup-language" className={labelClass}>{t("signup.languageLabel")}</label>
            <div className="relative">
              <span className={iconClass}><Globe className="size-4.5" /></span>
              <select
                id="signup-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className={inputClass("language_code")}
                disabled={isLoading}
              >
                {ACTIVE_LOCALES.map((locale) => (
                  <option key={locale.code} value={locale.code}>
                    {getLanguageSelectLabel(locale)}
                  </option>
                ))}
              </select>
            </div>
            {fieldError(F.language)}
          </div>

          {errors.form && <p role="alert" className="text-xs text-status-critical">{errors.form}</p>}

          <button
            type="submit"
            disabled={isLoading}
            className="flex w-full items-center justify-center rounded-xl bg-accent py-3 text-sm font-semibold text-ink-inverse transition-all duration-300 hover:bg-accent-hover active:scale-[0.98] disabled:opacity-60 disabled:pointer-events-none cursor-pointer"
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("signup.submitting")}
              </>
            ) : (
              t("signup.submit")
            )}
          </button>
        </form>

        <p className="text-center text-sm text-ink-muted">
          {t("signup.haveAccount")}{" "}
          <Link href="/login" className="font-semibold text-accent hover:text-accent-hover">
            {t("signup.signIn")}
          </Link>
        </p>
      </div>
    </div>
  );
}
