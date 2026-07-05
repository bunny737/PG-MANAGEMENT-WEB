"use client";

import React, { useState } from "react";
import { User, Mail, Phone, Building, Camera, CheckCircle2, Shield } from "lucide-react";

export function UserProfile() {
  const [name, setName] = useState("Owner Portal Administrator");
  const [email, setEmail] = useState("admin@propmanager.com");
  const [phone, setPhone] = useState("+1 (555) 019-2834");
  const [company, setCompany] = useState("Proton Management");
  const [isLoading, setIsLoading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const avatar = "https://lh3.googleusercontent.com/aida-public/AB6AXuB-hUJwnr_qkCBBMeA5bZXB5UIFI1GeWn3lSzJs4VwB1HwY4Dn-HSwOXieVMRF5g9UUZyg6ejGZjWqTsV-7pRCI-3FL7jNVkoY-94TzL5J6Zz8Al6aCVOUSjDlrZ0mQF8dGYgPlHCIAAJufHfzYcMkh9I5OzBpAak2pPZgrE7LRDdGux0LVx8qehAV-SR00tFH9BE5RQbFzUF5zLOoEM65UVxMdPFA8Q8XIbnwHVXQmdzWLFvffAB0YBA";

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      setShowToast(true);
      setTimeout(() => setShowToast(false), 4000);
    }, 1000);
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Toast alert */}
      {showToast && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <CheckCircle2 className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold">Profile Updated</span>
            <p className="text-xs text-emerald-700 mt-0.5">Your owner profile settings have been saved successfully.</p>
          </div>
        </div>
      )}

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">User Profile</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Manage your personal information, role details, and associated company parameters.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-12 items-start">
        {/* Left Column: Avatar & Summary details */}
        <div className="md:col-span-4 bg-surface-card border border-border rounded-2xl p-5 shadow-sm flex flex-col items-center text-center">
          {avatar ? (
            <div className="size-24 rounded-full overflow-hidden border border-border mb-4 shadow-sm bg-surface-page relative group">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={avatar} alt="Profile Avatar" className="size-full object-cover" />
              <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer text-white">
                <Camera className="size-5" />
              </div>
            </div>
          ) : (
            <div className="size-24 rounded-full bg-slate-100 border border-border text-slate-800 flex items-center justify-center font-bold text-3xl mb-4 shadow-inner relative group">
              OP
              <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer text-white rounded-full">
                <Camera className="size-5" />
              </div>
            </div>
          )}

          <h2 className="text-base font-bold text-ink">{name}</h2>
          <span className="mt-1 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100 text-[10px] font-bold uppercase tracking-wider">
            <Shield className="size-3" /> System Owner
          </span>

          {/* Quick specs details card */}
          <div className="w-full mt-5 rounded-xl bg-surface-page p-3 border border-border/60 text-left text-xs space-y-2.5">
            <div className="flex justify-between items-center text-ink-muted">
              <span>Account State</span>
              <span className="font-semibold text-emerald-600 flex items-center gap-1">
                <span className="size-1.5 rounded-full bg-emerald-500" /> Active Verified
              </span>
            </div>
            <div className="flex justify-between items-center text-ink-muted">
              <span>Tenant System</span>
              <span className="font-semibold text-ink">{company}</span>
            </div>
            <div className="flex justify-between items-center text-ink-muted">
              <span>Assigned Scope</span>
              <span className="font-semibold text-ink">All Properties (Owner)</span>
            </div>
          </div>
        </div>

        {/* Right Column: Profile Edit Form */}
        <form onSubmit={handleSave} className="md:col-span-8 bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5">
            Personal Information Details
          </h3>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Full Name */}
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="fullName" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Full Name
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                  <User className="size-4" />
                </span>
                <input
                  id="fullName"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Email Address */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Email Address
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                  <Mail className="size-4" />
                </span>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-xl border border-border bg-slate-50 py-2.5 pl-10 pr-4 text-xs text-ink-muted outline-none cursor-not-allowed"
                  disabled
                />
              </div>
              <p className="text-[9px] text-ink-faint italic ml-1">Email changes require secondary security OTP validation.</p>
            </div>

            {/* Phone Number */}
            <div className="space-y-1.5">
              <label htmlFor="phone" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Phone Number
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                  <Phone className="size-4" />
                </span>
                <input
                  id="phone"
                  type="text"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Company Name */}
            <div className="space-y-1.5 sm:col-span-2 pt-2.5 border-t border-border/55">
              <label htmlFor="company" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Associated Company Name
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                  <Building className="size-4" />
                </span>
                <input
                  id="company"
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                />
              </div>
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-bold py-2.5 rounded-xl cursor-pointer transition-colors shadow-sm disabled:opacity-50 mt-4"
          >
            {isLoading ? "Saving Profile..." : "Save Profile Settings"}
          </button>
        </form>
      </div>
    </div>
  );
}
