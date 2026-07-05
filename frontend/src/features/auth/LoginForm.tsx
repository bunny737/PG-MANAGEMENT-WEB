"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Mail, Lock, Phone, KeyRound, Eye, EyeOff, CheckCircle2, ArrowLeft, Loader2, Building2 } from "lucide-react";

type LoginTab = "password" | "otp";
type FlowState = "login" | "forgot_password";

export function LoginForm() {
  const router = useRouter();
  
  // Navigation & Flow
  const [activeTab, setActiveTab] = useState<LoginTab>("password");
  const [flowState, setFlowState] = useState<FlowState>("login");
  
  // Credentials Inputs
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  
  // OTP Inputs
  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [otpCountdown, setOtpCountdown] = useState(30);

  // Deriving canResendOtp to avoid state synchronization side-effects
  const canResendOtp = otpSent && otpCountdown === 0;

  // Forgot Password Input
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotSuccess, setForgotSuccess] = useState(false);

  // Form States
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  // OTP Timer countdown
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (otpSent && otpCountdown > 0) {
      timer = setInterval(() => {
        setOtpCountdown((prev) => prev - 1);
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [otpSent, otpCountdown]);

  // Validation
  const validateEmail = (val: string) => {
    const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return regex.test(val);
  };

  const validatePhone = (val: string) => {
    const regex = /^[6-9]\d{9}$/; // Indian mobile numbers
    return regex.test(val);
  };

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!email) {
      newErrors.email = "Email address is required";
    } else if (!validateEmail(email)) {
      newErrors.email = "Please enter a valid email address";
    }

    if (!password) {
      newErrors.password = "Password is required";
    } else if (password.length < 6) {
      newErrors.password = "Password must be at least 6 characters";
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    // Simulate API Call
    setTimeout(() => {
      setIsLoading(false);
      setIsSuccess(true);
      // Store local authentication state
      localStorage.setItem("isLoggedIn", "true");
      localStorage.setItem("userRole", "owner");
      localStorage.setItem("userName", "Vikram Malhotra");
      setTimeout(() => {
        router.push("/dashboard");
      }, 800);
    }, 1500);
  };

  const handleSendOtp = () => {
    if (!phone) {
      setErrors({ phone: "Phone number is required" });
      return;
    } else if (!validatePhone(phone)) {
      setErrors({ phone: "Please enter a valid 10-digit mobile number" });
      return;
    }

    setErrors({});
    setIsLoading(true);

    // Simulate OTP Send API Call
    setTimeout(() => {
      setIsLoading(false);
      setOtpSent(true);
      setOtpCountdown(30);
    }, 1000);
  };

  const handleResendOtp = () => {
    if (!canResendOtp) return;
    setOtpCountdown(30);
    // Simulate OTP resend
  };

  const handleOtpVerifySubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!otpCode || otpCode.length !== 6) {
      setErrors({ otpCode: "Please enter a valid 6-digit OTP code" });
      return;
    }

    setErrors({});
    setIsLoading(true);

    // Simulate Verification
    setTimeout(() => {
      setIsLoading(false);
      setIsSuccess(true);
      localStorage.setItem("isLoggedIn", "true");
      localStorage.setItem("userRole", "owner");
      localStorage.setItem("userName", "Vikram Malhotra");
      setTimeout(() => {
        router.push("/dashboard");
      }, 800);
    }, 1500);
  };

  const handleForgotSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!forgotEmail) {
      setErrors({ forgotEmail: "Email address is required" });
      return;
    } else if (!validateEmail(forgotEmail)) {
      setErrors({ forgotEmail: "Please enter a valid email address" });
      return;
    }

    setErrors({});
    setIsLoading(true);

    // Simulate Password Reset Request API Call
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
            Back to login
          </button>

          <div className="space-y-2">
            <h2 className="text-2xl font-bold tracking-tight text-ink">Reset password</h2>
            <p className="text-sm text-ink-muted">
              Enter your email address and we&apos;ll send you a link to reset your password.
            </p>
          </div>

          {forgotSuccess ? (
            <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-6 text-center space-y-4">
              <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <CheckCircle2 className="size-6" />
              </div>
              <div className="space-y-1">
                <h3 className="font-semibold text-ink">Reset Link Sent</h3>
                <p className="text-xs text-ink-muted">
                  We&apos;ve sent password reset instructions to <span className="font-medium text-ink">{forgotEmail}</span>. Please check your inbox.
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
                Back to Login
              </button>
            </div>
          ) : (
            <form onSubmit={handleForgotSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="forgot-email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Email Address
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Mail className="size-4.5" />
                  </span>
                  <input
                    id="forgot-email"
                    type="email"
                    placeholder="name@example.com"
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
                    <Loader2 className="mr-2 size-4.5 animate-spin" /> Sending reset link...
                  </>
                ) : (
                  "Send Reset Link"
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
          <span className="text-lg font-bold text-ink">PropManager</span>
        </div>

        {/* Welcome Headers */}
        <div className="space-y-2">
          <h2 className="text-3xl font-extrabold tracking-tight text-ink">Welcome back</h2>
          <p className="text-sm text-ink-muted">Sign in to your PropManager dashboard to manage your tenants and properties.</p>
        </div>

        {/* Slider Tab Switcher */}
        <div className="relative flex rounded-xl bg-surface-page p-1 border border-border">
          <div 
            className={`absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-lg bg-surface-card shadow-sm transition-all duration-300 ${
              activeTab === "otp" ? "left-[calc(50%+2px)]" : "left-1"
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
            Password
          </button>
          <button
            onClick={() => {
              setActiveTab("otp");
              setErrors({});
            }}
            className={`relative z-10 w-1/2 py-2 text-center text-sm font-semibold transition-colors duration-200 ${
              activeTab === "otp" ? "text-ink" : "text-ink-muted"
            }`}
          >
            OTP Code
          </button>
        </div>

        {/* Password Tab Form */}
        {activeTab === "password" && (
          <form onSubmit={handlePasswordSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Email Address
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                  <Mail className="size-4.5" />
                </span>
                <input
                  id="email"
                  type="email"
                  placeholder="name@example.com"
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
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => setFlowState("forgot_password")}
                  className="text-xs font-semibold text-accent hover:text-accent-hover transition-colors"
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                  <Lock className="size-4.5" />
                </span>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
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
                Keep me signed in
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
                  <Loader2 className="mr-2 size-4.5 animate-spin" /> Verifying...
                </>
              ) : isSuccess ? (
                <>
                  <CheckCircle2 className="mr-2 size-4.5 animate-bounce" /> Signed in successfully!
                </>
              ) : (
                "Sign In"
              )}
            </button>
          </form>
        )}

        {/* OTP Tab Form */}
        {activeTab === "otp" && (
          <div className="space-y-5">
            {!otpSent ? (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label htmlFor="phone" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Mobile Number
                  </label>
                  <div className="relative">
                    <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                      <Phone className="size-4.5" />
                    </span>
                    <input
                      id="phone"
                      type="tel"
                      placeholder="98765 43210"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
                      className={`w-full rounded-xl border ${
                        errors.phone ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                      } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
                      disabled={isLoading}
                    />
                  </div>
                  {errors.phone && <p className="text-xs text-status-critical">{errors.phone}</p>}
                </div>

                <button
                  type="button"
                  onClick={handleSendOtp}
                  disabled={isLoading}
                  className="flex w-full items-center justify-center rounded-xl bg-accent py-3 text-sm font-semibold text-ink-inverse hover:bg-accent-hover active:scale-[0.98] transition-all disabled:opacity-50"
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 size-4.5 animate-spin" /> Sending OTP...
                    </>
                  ) : (
                    "Send Verification Code"
                  )}
                </button>
              </div>
            ) : (
              <form onSubmit={handleOtpVerifySubmit} className="space-y-5">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label htmlFor="otpCode" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                      Verification Code
                    </label>
                    <button
                      type="button"
                      onClick={() => setOtpSent(false)}
                      className="text-xs font-semibold text-accent hover:text-accent-hover transition-colors"
                    >
                      Change number
                    </button>
                  </div>
                  <div className="relative">
                    <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                      <KeyRound className="size-4.5" />
                    </span>
                    <input
                      id="otpCode"
                      type="text"
                      placeholder="6-digit OTP code"
                      value={otpCode}
                      onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      className={`w-full rounded-xl border ${
                        errors.otpCode ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                      } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4 tracking-widest`}
                      disabled={isLoading || isSuccess}
                    />
                  </div>
                  {errors.otpCode && <p className="text-xs text-status-critical">{errors.otpCode}</p>}
                </div>

                <div className="flex items-center justify-between text-sm">
                  <span className="text-ink-muted">
                    {otpCountdown > 0 ? (
                      `Resend OTP in ${otpCountdown}s`
                    ) : (
                      "Didn't receive the code?"
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={handleResendOtp}
                    disabled={!canResendOtp}
                    className={`font-semibold text-accent transition-colors ${
                      canResendOtp ? "hover:text-accent-hover cursor-pointer" : "opacity-40 cursor-not-allowed"
                    }`}
                  >
                    Resend Code
                  </button>
                </div>

                <button
                  type="submit"
                  disabled={isLoading || isSuccess}
                  className={`flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition-all duration-300 ${
                    isSuccess 
                      ? "bg-emerald-500 text-white" 
                      : "bg-accent text-ink-inverse hover:bg-accent-hover active:scale-[0.98]"
                  } disabled:opacity-60`}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 size-4.5 animate-spin" /> Verifying...
                    </>
                  ) : isSuccess ? (
                    <>
                      <CheckCircle2 className="mr-2 size-4.5 animate-bounce" /> Verified! Redirecting...
                    </>
                  ) : (
                    "Verify & Sign In"
                  )}
                </button>
              </form>
            )}
          </div>
        )}

        {/* Demo Credentials Helper */}
        <div className="rounded-xl border border-border bg-surface-card p-4 text-xs space-y-1">
          <p className="font-semibold text-ink">Demo Credentials:</p>
          <div className="grid grid-cols-[auto_1fr] gap-x-2 text-ink-muted">
            <span className="font-medium text-ink-faint">Email:</span>
            <span>admin@propmanager.com</span>
            <span className="font-medium text-ink-faint">Password:</span>
            <span>admin123</span>
            <span className="font-medium text-ink-faint">Phone:</span>
            <span>9876543210 (any 6-digit OTP works)</span>
          </div>
        </div>

      </div>
    </div>
  );
}
