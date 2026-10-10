"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Mail, Lock, Phone, Eye, EyeOff, CheckCircle2, ArrowLeft, Loader2, Building2 } from "lucide-react";
import { ApiError, login, loginPhone } from "@/lib/api";

type LoginTab = "password" | "phone";
type FlowState = "login" | "forgot_password";

export function LoginForm() {
  const router = useRouter();
  const t = useTranslations("auth");
  const tCommon = useTranslations("common");

  // Navigation & Flow
  const [activeTab, setActiveTab] = useState<LoginTab>("password");
  const [flowState, setFlowState] = useState<FlowState>("login");

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

  // Form States
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  // Validation
  const validateEmail = (val: string) => {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return regex.test(val);
  };

  const normalizeInputPhone = (val: string) => {
    const digits = val.replace(/\D/g, "");
    if (digits.length === 10 && /^[6-9]/.test(digits)) return digits;
    if (digits.length === 11 && digits.startsWith("0") && /^[6-9]/.test(digits.slice(1))) return digits.slice(1);
    if (digits.length === 12 && digits.startsWith("91") && /^[6-9]/.test(digits.slice(2))) return digits.slice(2);
    return null;
  };

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
    setIsLoading(true);

    try {
      await login(email, password);
      setIsLoading(false);
      setIsSuccess(true);
      setTimeout(() => {
        router.push("/dashboard");
      }, 800);
    } catch (err) {
      setIsLoading(false);
      const message =
        err instanceof ApiError
          ? err.fieldError("detail") ?? t("login.errLoginFallback")
          : t("login.errServerUnreachable");
      setErrors({ password: message });
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
      await loginPhone(phone, phonePassword);
      setIsLoading(false);
      setIsSuccess(true);
      setTimeout(() => {
        router.push("/dashboard");
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
            className="group inline-flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors"
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
                <h3 className="font-semibold text-ink">{t("forgotPassword.sentTitle")}</h3>
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
                className="w-full rounded-xl bg-surface-inverse px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:opacity-90 transition-opacity"
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
                className="flex w-full items-center justify-center rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors disabled:opacity-50"
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
          <span className="flex size-9 items-center justify-center rounded-xl bg-accent text-white">
            <Building2 className="size-5" />
          </span>
          <span className="text-lg font-bold text-ink">{tCommon("appName")}</span>
        </div>

        {/* Welcome Headers */}
        <div className="space-y-2">
          <h2 className="text-3xl font-extrabold tracking-tight text-ink">{t("login.title")}</h2>
          <p className="text-sm text-ink-muted">{t("login.subtitle")}</p>
        </div>

        {/* Slider Tab Switcher */}
        <div className="relative flex rounded-xl bg-surface-page p-1 border border-border">
          <div 
            className={`absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-lg bg-surface-card shadow-sm transition-all duration-300 ${
              activeTab === "phone" ? "left-[calc(50%+2px)]" : "left-1"
            }`}
          />
          <button
            onClick={() => {
              setActiveTab("password");
              setErrors({});
            }}
            className={`relative z-10 w-1/2 py-2 text-center text-sm font-semibold transition-colors duration-200 ${
              activeTab === "password" ? "text-ink" : "text-ink-muted"
            }`}
          >
            {t("login.tabPassword")}
          </button>
          <button
            onClick={() => {
              setActiveTab("phone");
              setErrors({});
            }}
            className={`relative z-10 w-1/2 py-2 text-center text-sm font-semibold transition-colors duration-200 ${
              activeTab === "phone" ? "text-ink" : "text-ink-muted"
            }`}
          >
            {t("login.tabPhone")}
          </button>
        </div>

        {/* Password Tab Form (Email + Password) */}
        {activeTab === "password" && (
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
                  onChange={(e) => setEmail(e.target.value)}
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
                  className="text-xs font-semibold text-accent hover:text-accent-hover transition-colors"
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
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink transition-colors"
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
              } disabled:opacity-60 disabled:pointer-events-none`}
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
        )}

        {/* Phone Tab Form (Phone + Password) */}
        {activeTab === "phone" && (
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
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink transition-colors"
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
              } disabled:opacity-60 disabled:pointer-events-none`}
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
        )}

        {/* Demo Credentials Helper */}
        <div className="rounded-xl border border-border bg-surface-card p-4 text-xs space-y-1">
          <p className="font-semibold text-ink">{t("login.demoTitle")}</p>
          <div className="grid grid-cols-[auto_1fr] gap-x-2 text-ink-muted">
            <span className="font-medium text-ink-faint">{t("login.demoPasswordTab")}</span>
            <span>{t("login.demoPasswordText")}</span>
            <span className="font-medium text-ink-faint">{t("login.demoPhoneTab")}</span>
            <span>{t("login.demoPhoneText")}</span>
          </div>
        </div>

      </div>
    </div>
  );
}
