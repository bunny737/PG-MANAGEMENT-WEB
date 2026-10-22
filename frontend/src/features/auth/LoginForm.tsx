"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Mail,
  Lock,
  Phone,
  Eye,
  EyeOff,
  CheckCircle2,
  ArrowLeft,
  Loader2,
  Building2,
  UserCheck,
  ChevronRight,
} from "lucide-react";
import { BrandMark } from "@/components/shared/BrandMark";
import { firstAllowedRoute } from "@/lib/permissions";
import { ApiError, clearSession, login, loginPhone, type CurrentUser } from "@/lib/api";
import { EmailCodeLogin, type CodeRequests } from "./EmailCodeLogin";
import { ResendVerificationPrompt } from "./ResendVerificationPrompt";
import { isValidEmail, normalizeInputPhone } from "./validation";

type LoginView = "choice" | "owner" | "staff";
type FlowState = "login" | "forgot_password";
/** Password is the default; the emailed code is the optional alternative in both views. */
type AuthMethod = "password" | "email_code";

/** Roles each login view admits (the email-code path enforces the same split as the password forms). */
const OWNER_VIEW_ROLES = ["owner"];
const STAFF_VIEW_ROLES = ["manager", "receptionist"];

interface LoginFormProps {
  /** SIGNUP_ENABLED: only decides whether the "Start free trial" link shows (discovery only;
   * /signup itself stays reachable by URL). */
  signupEnabled?: boolean;
}

export function LoginForm({ signupEnabled = false }: LoginFormProps) {
  const router = useRouter();
  const t = useTranslations("auth");
  const tCommon = useTranslations("common");

  // Navigation & Flow
  const [loginView, setLoginView] = useState<LoginView>("choice");
  const [flowState, setFlowState] = useState<FlowState>("login");
  const [authMethod, setAuthMethod] = useState<AuthMethod>("password");
  // Lives here, not in EmailCodeLogin, so resend cooldowns survive switching views or methods.
  const [codeRequests, setCodeRequests] = useState<CodeRequests>({});
  const recordCodeRequest = (address: string, sentAt: number) =>
    setCodeRequests((prev) => ({ ...prev, [address]: sentAt }));

  // Email + Password Credentials
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);

  // Phone + Password Credentials
  const [phone, setPhone] = useState("");
  const [phonePassword, setPhonePassword] = useState("");
  const [showPhonePassword, setShowPhonePassword] = useState(false);

  // Forgot Password Input
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotSuccess, setForgotSuccess] = useState(false);

  // Set when password login answered EMAIL_NOT_VERIFIED: offers a resend for this address.
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);

  // Form States
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const validateEmail = isValidEmail;

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!email) {
      newErrors.email = t("login.errEmailRequired");
    } else if (!validateEmail(email)) {
      newErrors.email = t("login.errEmailInvalid");
    }

    if (!password) {
      newErrors.password = t("login.errPasswordRequired");
    } else if (password.length < 6) {
      newErrors.password = t("login.errPasswordLength");
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setUnverifiedEmail(null);
    setIsLoading(true);

    try {
      const me = await login(email, password);
      if (me.role !== "owner") {
        await clearSession();
        setIsLoading(false);
        setErrors({ password: t("login.errRoleMismatchOwner") });
        return;
      }
      setIsLoading(false);
      setIsSuccess(true);
      setTimeout(() => {
        // Access is Owner-configured per person, so land on the first screen it allows.
        router.push(firstAllowedRoute(me.permissions ?? []));
      }, 800);
    } catch (err) {
      setIsLoading(false);
      const message =
        err instanceof ApiError
          ? err.fieldError("detail") ?? t("login.errLoginFallback")
          : t("login.errServerUnreachable");
      setErrors({ password: message });
      // Branch on the machine code, never on the (translated) message.
      if (err instanceof ApiError && err.code === "EMAIL_NOT_VERIFIED") setUnverifiedEmail(email.trim());
    }
  };

  const handlePhoneSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!phone.trim()) {
      newErrors.phone = t("login.errPhoneRequired");
    } else if (!normalizeInputPhone(phone)) {
      newErrors.phone = t("login.errPhoneInvalid");
    }

    if (!phonePassword) {
      newErrors.phonePassword = t("login.errPasswordRequired");
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    try {
      const me = await loginPhone(phone, phonePassword);
      if (me.role !== "manager" && me.role !== "receptionist") {
        await clearSession();
        setIsLoading(false);
        setErrors({ phonePassword: t("login.errRoleMismatchStaff") });
        return;
      }
      setIsLoading(false);
      setIsSuccess(true);
      setTimeout(() => {
        router.push(firstAllowedRoute(me.permissions ?? []));
      }, 800);
    } catch (err) {
      setIsLoading(false);
      const message =
        err instanceof ApiError
          ? err.fieldError("detail") ?? err.fieldError("phone") ?? err.fieldError("password") ?? t("login.errLoginFallback")
          : t("login.errServerUnreachable");
      setErrors({ phonePassword: message });
    }
  };

  const handleEmailCodeSuccess = (me: CurrentUser) => {
    setTimeout(() => {
      router.push(firstAllowedRoute(me.permissions ?? []));
    }, 800);
  };

  const usePasswordInstead = () => setAuthMethod("password");

  const backToChoice = () => {
    setLoginView("choice");
    setAuthMethod("password");
    setUnverifiedEmail(null);
    setErrors({});
  };

  const useEmailCodeLink = (
    <button
      type="button"
      onClick={() => {
        setAuthMethod("email_code");
        setErrors({});
      }}
      disabled={isLoading || isSuccess}
      className="w-full text-center text-sm font-semibold text-accent hover:text-accent-hover transition-colors cursor-pointer disabled:opacity-60"
    >
      {t("login.useEmailCode")}
    </button>
  );

  const handleForgotSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!forgotEmail) {
      setErrors({ forgotEmail: t("login.errEmailRequired") });
      return;
    } else if (!validateEmail(forgotEmail)) {
      setErrors({ forgotEmail: t("login.errEmailInvalid") });
      return;
    }

    setErrors({});
    setIsLoading(true);

    setTimeout(() => {
      setIsLoading(false);
      setForgotSuccess(true);
    }, 1500);
  };

  if (flowState === "forgot_password") {
    return (
      <div className="flex w-full flex-col justify-center px-4 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
        <div className="mx-auto w-full max-w-md space-y-6">
          <button
            onClick={() => {
              setFlowState("login");
              setForgotSuccess(false);
              setForgotEmail("");
              setErrors({});
            }}
            className="group inline-flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors cursor-pointer"
          >
            <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
            {t("forgotPassword.backToLogin")}
          </button>

          <div className="space-y-2">
            <h2 className="text-2xl font-bold tracking-tight text-ink">{t("forgotPassword.title")}</h2>
            <p className="text-sm text-ink-muted">
              {t("forgotPassword.subtitle")}
            </p>
          </div>

          {forgotSuccess ? (
            <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-6 text-center space-y-4">
              <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <CheckCircle2 className="size-6" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-ink">{t("forgotPassword.sentTitle")}</h3>
                <p className="text-xs text-ink-muted">
                  {t("forgotPassword.sentSubtitle", { email: forgotEmail })}
                </p>
              </div>
              <button
                onClick={() => {
                  setFlowState("login");
                  setForgotSuccess(false);
                  setForgotEmail("");
                }}
                className="w-full rounded-xl bg-accent py-2 text-xs font-semibold text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer"
              >
                {t("forgotPassword.backToLogin")}
              </button>
            </div>
          ) : (
            <form onSubmit={handleForgotSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="forgot-email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("login.emailLabel")}
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Mail className="size-4.5" />
                  </span>
                  <input
                    id="forgot-email"
                    type="email"
                    placeholder={t("login.emailPlaceholder")}
                    value={forgotEmail}
                    onChange={(e) => setForgotEmail(e.target.value)}
                    className={`w-full rounded-xl border ${
                      errors.forgotEmail ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                    } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
                    disabled={isLoading}
                  />
                </div>
                {errors.forgotEmail && <p className="text-xs text-status-critical">{errors.forgotEmail}</p>}
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="flex w-full items-center justify-center rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("forgotPassword.sending")}
                  </>
                ) : (
                  t("forgotPassword.submit")
                )}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
      <div className="mx-auto w-full max-w-md space-y-8">
        {/* Mobile Brand Indicator */}
        <div className="flex items-center gap-2.5 lg:hidden">
          <BrandMark />
          <span className="text-lg font-bold text-ink">{tCommon("appName")}</span>
        </div>

        {/* 1. INITIAL CHOICE VIEW */}
        {loginView === "choice" && (
          <div className="space-y-6">
            <div className="space-y-2">
              <h2 className="text-3xl font-extrabold tracking-tight text-ink">
                {t("login.chooseTitle")}
              </h2>
              <p className="text-sm text-ink-muted">
                {t("login.chooseSubtitle")}
              </p>
            </div>

            <div className="space-y-3.5">
              <button
                onClick={() => {
                  setLoginView("owner");
                  setErrors({});
                }}
                className="group flex w-full items-center justify-between rounded-2xl border border-border bg-surface-card p-5 text-left shadow-sm transition-all hover:border-accent/40 hover:bg-surface-subtle hover:shadow-md cursor-pointer active:scale-[0.99]"
              >
                <div className="flex items-center gap-4">
                  <div className="flex size-12 items-center justify-center rounded-xl bg-accent-soft text-accent transition-colors group-hover:bg-accent group-hover:text-ink-inverse">
                    <Building2 className="size-6" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-ink group-hover:text-accent transition-colors">
                      {t("login.ownerOptionTitle")}
                    </h3>
                    <p className="text-xs text-ink-muted mt-0.5">
                      {t("login.ownerOptionDesc")}
                    </p>
                  </div>
                </div>
                <ChevronRight className="size-5 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
              </button>

              <button
                onClick={() => {
                  setLoginView("staff");
                  setErrors({});
                }}
                className="group flex w-full items-center justify-between rounded-2xl border border-border bg-surface-card p-5 text-left shadow-sm transition-all hover:border-accent/40 hover:bg-surface-subtle hover:shadow-md cursor-pointer active:scale-[0.99]"
              >
                <div className="flex items-center gap-4">
                  <div className="flex size-12 items-center justify-center rounded-xl bg-surface-subtle text-ink-muted transition-colors group-hover:bg-accent group-hover:text-ink-inverse">
                    <UserCheck className="size-6" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-ink group-hover:text-accent transition-colors">
                      {t("login.staffOptionTitle")}
                    </h3>
                    <p className="text-xs text-ink-muted mt-0.5">
                      {t("login.staffOptionDesc")}
                    </p>
                  </div>
                </div>
                <ChevronRight className="size-5 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
              </button>
            </div>
          </div>
        )}

        {/* 2. OWNER LOGIN FORM (Email + Password) */}
        {loginView === "owner" && (
          <div className="space-y-6">
            <button
              onClick={backToChoice}
              className="group inline-flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors cursor-pointer"
            >
              <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
              {t("login.backToSelection")}
            </button>

            <div className="space-y-2">
              <h2 className="text-2xl font-extrabold tracking-tight text-ink">
                {t("login.ownerOptionTitle")}
              </h2>
              <p className="text-sm text-ink-muted">
                {t("login.ownerOptionDesc")}
              </p>
            </div>

            {authMethod === "email_code" ? (
              <EmailCodeLogin
                expectedRoles={OWNER_VIEW_ROLES}
                initialEmail={email}
                codeRequests={codeRequests}
                onCodeRequested={recordCodeRequest}
                roleMismatchMessage={t("login.errRoleMismatchOwner")}
                onSuccess={handleEmailCodeSuccess}
                onUsePassword={usePasswordInstead}
              />
            ) : (
            <>
            <form onSubmit={handlePasswordSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label htmlFor="email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("login.emailLabel")}
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Mail className="size-4.5" />
                  </span>
                  <input
                    id="email"
                    type="email"
                    placeholder={t("login.emailPlaceholder")}
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      // The resend offer is for the address that failed; never send to a stale one.
                      setUnverifiedEmail(null);
                    }}
                    className={`w-full rounded-xl border ${
                      errors.email ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                    } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
                    disabled={isLoading || isSuccess}
                  />
                </div>
                {errors.email && <p className="text-xs text-status-critical">{errors.email}</p>}
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label htmlFor="password" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    {t("login.passwordLabel")}
                  </label>
                  <button
                    type="button"
                    onClick={() => setFlowState("forgot_password")}
                    className="text-xs font-semibold text-accent hover:text-accent-hover transition-colors cursor-pointer"
                  >
                    {t("login.forgotPassword")}
                  </button>
                </div>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Lock className="size-4.5" />
                  </span>
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder={t("login.passwordPlaceholder")}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`w-full rounded-xl border ${
                      errors.password ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                    } bg-surface-card py-2.5 pl-10 pr-10 text-sm text-ink outline-none transition-all focus:ring-4`}
                    disabled={isLoading || isSuccess}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink transition-colors cursor-pointer"
                  >
                    {showPassword ? <EyeOff className="size-4.5" /> : <Eye className="size-4.5" />}
                  </button>
                </div>
                {errors.password && <p className="text-xs text-status-critical">{errors.password}</p>}
              </div>

              <div className="flex items-center">
                <input
                  id="remember-me"
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="size-4 rounded border-border text-accent focus:ring-accent bg-surface-card"
                  disabled={isLoading || isSuccess}
                />
                <label htmlFor="remember-me" className="ml-2.5 text-sm font-medium text-ink-muted select-none">
                  {t("login.rememberMe")}
                </label>
              </div>

              <button
                type="submit"
                disabled={isLoading || isSuccess}
                className={`flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition-all duration-300 ${
                  isSuccess 
                    ? "bg-emerald-500 text-white" 
                    : "bg-accent text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98]"
                } disabled:opacity-60 disabled:pointer-events-none cursor-pointer`}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("login.verifying")}
                  </>
                ) : isSuccess ? (
                  <>
                    <CheckCircle2 className="mr-2 size-4.5 animate-bounce" /> {t("login.success")}
                  </>
                ) : (
                  t("login.submitPassword")
                )}
              </button>
            </form>
            {/* Outside the password form: the prompt is a form of its own. Keyed by address so a
                different unverified address starts fresh. */}
            {unverifiedEmail && <ResendVerificationPrompt key={unverifiedEmail} email={unverifiedEmail} />}
            {useEmailCodeLink}
            </>
            )}
          </div>
        )}

        {/* 3. STAFF LOGIN FORM (Phone + Password) */}
        {loginView === "staff" && (
          <div className="space-y-6">
            <button
              onClick={backToChoice}
              className="group inline-flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors cursor-pointer"
            >
              <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
              {t("login.backToSelection")}
            </button>

            <div className="space-y-2">
              <h2 className="text-2xl font-extrabold tracking-tight text-ink">
                {t("login.staffOptionTitle")}
              </h2>
              <p className="text-sm text-ink-muted">
                {t("login.staffOptionDesc")}
              </p>
            </div>

            {authMethod === "email_code" ? (
              <EmailCodeLogin
                expectedRoles={STAFF_VIEW_ROLES}
                codeRequests={codeRequests}
                onCodeRequested={recordCodeRequest}
                roleMismatchMessage={t("login.errRoleMismatchStaff")}
                onSuccess={handleEmailCodeSuccess}
                onUsePassword={usePasswordInstead}
              />
            ) : (
            <>
            <form onSubmit={handlePhoneSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <label htmlFor="phone" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("login.phoneLabel")}
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Phone className="size-4.5" />
                  </span>
                  <input
                    id="phone"
                    type="tel"
                    placeholder={t("login.phonePlaceholder")}
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className={`w-full rounded-xl border ${
                      errors.phone ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                    } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
                    disabled={isLoading || isSuccess}
                  />
                </div>
                {errors.phone && <p className="text-xs text-status-critical">{errors.phone}</p>}
              </div>

              <div className="space-y-1.5">
                <label htmlFor="phone-password" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("login.passwordLabel")}
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Lock className="size-4.5" />
                  </span>
                  <input
                    id="phone-password"
                    type={showPhonePassword ? "text" : "password"}
                    placeholder={t("login.passwordPlaceholder")}
                    value={phonePassword}
                    onChange={(e) => setPhonePassword(e.target.value)}
                    className={`w-full rounded-xl border ${
                      errors.phonePassword ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                    } bg-surface-card py-2.5 pl-10 pr-10 text-sm text-ink outline-none transition-all focus:ring-4`}
                    disabled={isLoading || isSuccess}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPhonePassword(!showPhonePassword)}
                    className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink transition-colors cursor-pointer"
                  >
                    {showPhonePassword ? <EyeOff className="size-4.5" /> : <Eye className="size-4.5" />}
                  </button>
                </div>
                {errors.phonePassword && <p className="text-xs text-status-critical">{errors.phonePassword}</p>}
              </div>

              <div className="flex items-center">
                <input
                  id="remember-me-phone"
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="size-4 rounded border-border text-accent focus:ring-accent bg-surface-card"
                  disabled={isLoading || isSuccess}
                />
                <label htmlFor="remember-me-phone" className="ml-2.5 text-sm font-medium text-ink-muted select-none">
                  {t("login.rememberMe")}
                </label>
              </div>

              <button
                type="submit"
                disabled={isLoading || isSuccess}
                className={`flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition-all duration-300 ${
                  isSuccess 
                    ? "bg-emerald-500 text-white" 
                    : "bg-accent text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98]"
                } disabled:opacity-60 disabled:pointer-events-none cursor-pointer`}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("login.verifying")}
                  </>
                ) : isSuccess ? (
                  <>
                    <CheckCircle2 className="mr-2 size-4.5 animate-bounce" /> {t("login.success")}
                  </>
                ) : (
                  t("login.submitPhone")
                )}
              </button>
            </form>
            {useEmailCodeLink}
            </>
            )}
          </div>
        )}

        {signupEnabled && (
          <p className="text-center text-sm text-ink-muted">
            {t("login.signupPrompt")}{" "}
            <Link href="/signup" className="font-semibold text-accent hover:text-accent-hover">
              {t("login.signupLink")}
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
