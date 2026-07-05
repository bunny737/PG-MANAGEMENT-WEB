"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, CloudUpload, X, Camera, Info, CheckCircle2 } from "lucide-react";
import Link from "next/link";

export function AddPropertyForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [type, setType] = useState("PG (Paying Guest)");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [pincode, setPincode] = useState("");
  const [images, setImages] = useState<string[]>([
    "https://lh3.googleusercontent.com/aida-public/AB6AXuCnV0AJ8slF7JjAp8PJekjnXhEtthqLzdlMso6N4J5jHg2EIcK-rskIQmWRDQtRy2ctUL6I70fHtRXGxFvYB8G9jGHhajzCvgsqo5-39FfmgKft7cBB7UtH4i54ClbsvIj5xpiso6jYXAQtCLjpTXl6q187pNrqdGprjgbmulxPl1trnu9eAUpWRdd1PdaLxiVFD8X2o3nJ19eGN0VA_nJXtpYDPDArthRl1aNQCyVVByqgiL4HdQS68g",
    "https://lh3.googleusercontent.com/aida-public/AB6AXuB94TQH7EDXhHmW1uunSUr95qrT_4Yah6Hm1jrd2s8sYSrWApFzSvbVhKEiiXrVYc04krZpnIbEurlQc7eofmYU_wWHqjLTEz4R53gvtEsmrOIoAUzbMzmYsSKTdgSz1RXQaVb-8QnfqHH51K4rPP5Zwy_0g4atVuKHilJ2hwms22fidX6SFsanzg5cpVW0luTToHBaQz9eTTOHL5J_i1YNnc0LUu3yIedaZiDjGfle8lE-I8mNAx7DFQ"
  ]);

  const [isLoading, setIsLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleRemoveImage = (index: number) => {
    setImages(images.filter((_, i) => i !== index));
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!name) newErrors.name = "Property Name is required";
    if (!address) newErrors.address = "Address is required";
    if (!city) newErrors.city = "City is required";
    if (!state) newErrors.state = "State is required";
    if (!pincode) newErrors.pincode = "Pincode is required";

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    setTimeout(() => {
      setIsLoading(false);
      setShowSuccess(true);
    }, 1500);
  };

  const handleCloseModal = () => {
    setShowSuccess(false);
    router.push("/properties");
  };

  return (
    <div className="space-y-6">
      {/* Success Modal Backdrop */}
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-container-lowest p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">Property Registered</h3>
            <p className="text-xs text-ink-muted mb-8 leading-relaxed">
              Your new building hierarchy has been registered successfully. You can now build floors and units.
            </p>
            <button
              onClick={handleCloseModal}
              className="w-full py-3 bg-surface-inverse text-ink-inverse font-bold rounded-xl hover:opacity-90 transition-opacity cursor-pointer text-sm"
            >
              Back to Properties
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href="/properties"
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">Add Property</h1>
          <p className="text-xs text-ink-muted">List a new property asset in your multi-tenant PG directory.</p>
        </div>
      </div>

      {/* Form Content */}
      <form onSubmit={handleFormSubmit} className="grid grid-cols-1 gap-6 lg:grid-cols-12 items-start">
        {/* Left Column Fields */}
        <div className="lg:col-span-7 space-y-6">
          <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-2.5">
              Property Information
            </h2>

            {/* Property Name */}
            <div className="space-y-1.5">
              <label htmlFor="name" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Property Name
              </label>
              <input
                id="name"
                type="text"
                placeholder="e.g. Skyline Residency"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={`w-full rounded-xl border ${
                  errors.name ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                disabled={isLoading}
              />
              {errors.name && <p className="text-xs text-status-critical">{errors.name}</p>}
            </div>

            {/* Property Type */}
            <div className="space-y-1.5">
              <label htmlFor="type" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Property Type
              </label>
              <select
                id="type"
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                disabled={isLoading}
              >
                <option value="Apartment">Apartment</option>
                <option value="Hostel">Hostel</option>
                <option value="PG (Paying Guest)">PG (Paying Guest)</option>
                <option value="Single Family Home">Single Family Home</option>
                <option value="Commercial Space">Commercial Space</option>
              </select>
            </div>

            {/* Address */}
            <div className="space-y-1.5">
              <label htmlFor="address" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Address
              </label>
              <textarea
                id="address"
                placeholder="Street name, building number, block details..."
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                rows={3}
                className={`w-full rounded-xl border ${
                  errors.address ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                disabled={isLoading}
              />
              {errors.address && <p className="text-xs text-status-critical">{errors.address}</p>}
            </div>

            {/* City / State / Pincode grid */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <label htmlFor="city" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  City
                </label>
                <input
                  id="city"
                  type="text"
                  placeholder="City"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  className={`w-full rounded-xl border ${
                    errors.city ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.city && <p className="text-xs text-status-critical">{errors.city}</p>}
              </div>

              <div className="space-y-1.5">
                <label htmlFor="state" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  State
                </label>
                <input
                  id="state"
                  type="text"
                  placeholder="State"
                  value={state}
                  onChange={(e) => setState(e.target.value)}
                  className={`w-full rounded-xl border ${
                    errors.state ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.state && <p className="text-xs text-status-critical">{errors.state}</p>}
              </div>

              <div className="space-y-1.5">
                <label htmlFor="pincode" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Pincode
                </label>
                <input
                  id="pincode"
                  type="text"
                  placeholder="Zip code"
                  value={pincode}
                  onChange={(e) => setPincode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  className={`w-full rounded-xl border ${
                    errors.pincode ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.pincode && <p className="text-xs text-status-critical">{errors.pincode}</p>}
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Image uploads */}
        <div className="lg:col-span-5 space-y-6">
          <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink">Property Images</h2>

            {/* Bento-style Image Grid */}
            <div className="grid grid-cols-2 gap-4">
              {/* Featured Upload Box */}
              <div className="col-span-2 aspect-video bg-surface-page border-2 border-dashed border-border rounded-xl flex flex-col items-center justify-center text-ink-muted hover:bg-surface-card hover:border-accent/40 transition-colors cursor-pointer group">
                <CloudUpload className="size-8 text-ink-faint mb-2 group-hover:scale-110 transition-transform" />
                <p className="text-xs font-semibold text-ink">Upload Featured Photo</p>
                <p className="text-[10px] text-ink-faint mt-0.5">PNG, JPG up to 10MB</p>
              </div>

              {/* Preloaded Photo Preview Cards */}
              {images.map((imgUrl, idx) => (
                <div key={idx} className="aspect-square bg-surface-page rounded-xl overflow-hidden border border-border relative group">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={imgUrl} alt={`Preview ${idx + 1}`} className="size-full object-cover" />
                  <button
                    type="button"
                    onClick={() => handleRemoveImage(idx)}
                    className="absolute top-2 right-2 bg-status-critical/80 hover:bg-status-critical text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}

              {/* Additional Photo placeholder slots */}
              <div className="aspect-square bg-surface-page border border-dashed border-border rounded-xl flex items-center justify-center text-ink-faint hover:bg-surface-card hover:text-ink-muted transition-colors cursor-pointer">
                <Camera className="size-6" />
              </div>
              <div className="aspect-square bg-surface-page border border-dashed border-border rounded-xl flex items-center justify-center text-ink-faint hover:bg-surface-card hover:text-ink-muted transition-colors cursor-pointer">
                <Camera className="size-6" />
              </div>
            </div>

            {/* Operational tip card */}
            <div className="bg-accent-soft border border-accent/15 p-4 rounded-xl flex gap-3.5 mt-2">
              <Info className="size-5 text-accent shrink-0" />
              <div className="space-y-0.5 text-xs">
                <p className="font-bold text-accent">Pro Tip</p>
                <p className="text-ink-muted leading-relaxed">
                  Properties with at least 5 high-quality photos get 40% more lease inquiries within the first week of listing.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Form Action Register Bar (sticky layout) */}
        <div className="lg:col-span-12 border-t border-border bg-surface-card -mx-4 px-4 py-4 md:-mx-8 md:px-8 mt-6 flex justify-end">
          <button
            type="submit"
            disabled={isLoading}
            className="w-full sm:max-w-xs bg-accent text-ink-inverse hover:bg-accent-hover font-semibold py-3 px-6 rounded-xl flex items-center justify-center gap-2 cursor-pointer transition-colors shadow-sm disabled:opacity-50"
          >
            {isLoading ? "Processing Registration..." : "Register Property"}
          </button>
        </div>
      </form>
    </div>
  );
}
