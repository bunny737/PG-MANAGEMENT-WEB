"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ArrowLeft, ChevronRight, Save, CheckCircle2 } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function PropertySettingsForm({ propertyId }: { propertyId: string }) {
  const property = mockProperties.find((p) => p.id === propertyId) || mockProperties[0];

  // Default state values from specs
  const [rentTiming, setRentTiming] = useState<"next_billing_cycle" | "immediate">("next_billing_cycle");
  const [penaltyType, setPenaltyType] = useState<"none" | "fixed" | "percentage">("none");
  const [penaltyValue, setPenaltyValue] = useState("");
  const [graceDays, setGraceDays] = useState(5);
  const [appliesTo, setAppliesTo] = useState<"full_invoice" | "outstanding_balance">("full_invoice");
  const [compounding, setCompounding] = useState<"one_time" | "monthly">("one_time");

  const [isLoading, setIsLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    // Validate grace days cap
    if (graceDays < 0 || graceDays > 30) {
      newErrors.graceDays = "Grace days must be between 0 and 30 days.";
    }

    // Validate penalty value if penalty type is enabled
    if (penaltyType !== "none") {
      if (!penaltyValue) {
        newErrors.penaltyValue = "Penalty value is required when late payment penalty is active.";
      } else {
        const val = parseFloat(penaltyValue);
        if (isNaN(val) || val <= 0) {
          newErrors.penaltyValue = "Penalty value must be a positive number.";
        } else if (penaltyType === "percentage" && val > 100) {
          newErrors.penaltyValue = "Percentage penalty cannot exceed 100%.";
        }
      }
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    setTimeout(() => {
      setIsLoading(false);
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 4000);
    }, 1200);
  };

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      {/* Success Notification Alert Toast */}
      {showSuccess && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <CheckCircle2 className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold">Settings Saved</span>
            <p className="text-xs text-emerald-700 mt-0.5">
              Property billing behavior updated successfully. Audit log written.
            </p>
          </div>
        </div>
      )}

      {/* Header and Breadcrumbs */}
      <div className="flex items-center gap-3">
        <Link
          href={`/properties/${property.id}/floors`}
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          {/* Breadcrumbs */}
          <nav aria-label="Breadcrumb" className="flex items-center text-xs text-ink-muted mb-1">
            <ol className="inline-flex items-center space-x-1">
              <li>
                <Link href="/properties" className="hover:text-accent font-medium transition-colors">
                  Properties
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <Link href={`/properties/${property.id}/floors`} className="hover:text-accent font-medium transition-colors">
                  {property.name}
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <span className="text-ink font-semibold">Settings</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-xl font-bold tracking-tight text-ink">Property Settings (Module 2B)</h1>
        </div>
      </div>

      <form onSubmit={handleFormSubmit} className="space-y-6">
        {/* Section 1: Billing & Room Transfer Rent Timing */}
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5">
            Billing & Room Transfers
          </h2>
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
              Transfer Rent Effective Date
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div
                onClick={() => setRentTiming("next_billing_cycle")}
                className={`border rounded-xl p-4 cursor-pointer transition-all flex flex-col justify-between ${
                  rentTiming === "next_billing_cycle"
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border hover:bg-surface-page text-ink-muted"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-ink">Next Billing Cycle</span>
                  <input
                    type="radio"
                    checked={rentTiming === "next_billing_cycle"}
                    onChange={() => {}}
                    className="accent-accent"
                  />
                </div>
                <p className="text-[10px] text-ink-muted mt-2 leading-relaxed">
                  Rent adjustments are applied only from the next automated invoice sequence.
                </p>
              </div>

              <div
                onClick={() => setRentTiming("immediate")}
                className={`border rounded-xl p-4 cursor-pointer transition-all flex flex-col justify-between ${
                  rentTiming === "immediate"
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border hover:bg-surface-page text-ink-muted"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-ink">Immediate Timing</span>
                  <input
                    type="radio"
                    checked={rentTiming === "immediate"}
                    onChange={() => {}}
                    className="accent-accent"
                  />
                </div>
                <p className="text-[10px] text-ink-muted mt-2 leading-relaxed">
                  New room rates take effect immediately upon completion of the transfer check.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: Late Payment Penalty configs */}
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5">
            Late Payment Penalty Policy
          </h2>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {/* Penalty Type select */}
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="penaltyType" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Penalty calculation mode
              </label>
              <select
                id="penaltyType"
                value={penaltyType}
                onChange={(e) => {
                  setPenaltyType(e.target.value as typeof penaltyType);
                  if (e.target.value === "none") setPenaltyValue("");
                }}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              >
                <option value="none">No penalty policies active</option>
                <option value="fixed">Fixed Rate penalty ($)</option>
                <option value="percentage">Percentage based penalty (%)</option>
              </select>
            </div>

            {/* Penalty Grace Days */}
            <div className="space-y-1.5">
              <label htmlFor="grace" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Grace Days (0 - 30 days)
              </label>
              <input
                id="grace"
                type="number"
                min="0"
                max="30"
                value={graceDays}
                onChange={(e) => setGraceDays(parseInt(e.target.value) || 0)}
                className={`w-full rounded-xl border ${
                  errors.graceDays ? "border-status-critical" : "border-border"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
              />
              {errors.graceDays && <p className="text-xs text-status-critical">{errors.graceDays}</p>}
            </div>

            {/* Penalty Value (conditional) */}
            {penaltyType !== "none" && (
              <div className="space-y-1.5 animate-fade-in">
                <label htmlFor="penaltyValue" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Penalty rate amount ({penaltyType === "fixed" ? "$" : "%"})
                </label>
                <input
                  id="penaltyValue"
                  type="number"
                  step="0.01"
                  value={penaltyValue}
                  onChange={(e) => setPenaltyValue(e.target.value)}
                  placeholder={penaltyType === "fixed" ? "0.00" : "0.0"}
                  className={`w-full rounded-xl border ${
                    errors.penaltyValue ? "border-status-critical" : "border-border"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
                />
                {errors.penaltyValue && <p className="text-xs text-status-critical">{errors.penaltyValue}</p>}
              </div>
            )}

            {/* Applies To */}
            {penaltyType !== "none" && (
              <div className="space-y-1.5 animate-fade-in">
                <label htmlFor="appliesTo" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Penalty Applies To
                </label>
                <select
                  id="appliesTo"
                  value={appliesTo}
                  onChange={(e) => setAppliesTo(e.target.value as typeof appliesTo)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                >
                  <option value="full_invoice">Full Invoice Amount</option>
                  <option value="outstanding_balance">Outstanding Balance Only</option>
                </select>
              </div>
            )}

            {/* Penalty Compounding */}
            {penaltyType !== "none" && (
              <div className="space-y-1.5 animate-fade-in">
                <label htmlFor="compounding" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Compounding logic
                </label>
                <select
                  id="compounding"
                  value={compounding}
                  onChange={(e) => setCompounding(e.target.value as typeof compounding)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                >
                  <option value="one_time">One-time penalty</option>
                  <option value="monthly">Monthly compounding</option>
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Save button footer */}
        <div className="flex justify-end gap-3 pt-2">
          <Link
            href={`/properties/${property.id}/floors`}
            className="rounded-xl border border-border bg-surface-page px-5 py-2.5 text-xs font-bold text-ink-muted hover:bg-surface-card hover:text-ink transition-colors cursor-pointer"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={isLoading}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50"
          >
            <Save className="size-4" />
            {isLoading ? "Saving Settings..." : "Save Settings"}
          </button>
        </div>
      </form>
    </div>
  );
}
