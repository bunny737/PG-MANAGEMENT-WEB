"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Home, Wifi, Sparkles, CheckCircle2 } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function AddRoomForm({ propertyId, floorId }: { propertyId: string; floorId: string }) {
  const router = useRouter();
  const property = mockProperties.find((p) => p.id === propertyId) || mockProperties[0];
  const floor = property.floors.find((f) => f.id === floorId) || property.floors[0] || { id: floorId, level: floorId, name: `Floor ${floorId}` };

  const [selectedFloor, setSelectedFloor] = useState(floor.id);
  const [roomNumber, setRoomNumber] = useState("");
  const [sharingType, setSharingType] = useState("double");
  const [category, setCategory] = useState("ac");
  const [rent, setRent] = useState("");
  
  // Amenities checklist
  const [amenities, setAmenities] = useState<string[]>(["Wi-Fi", "Cleaning"]);

  const [isLoading, setIsLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const toggleAmenity = (name: string) => {
    if (amenities.includes(name)) {
      setAmenities(amenities.filter((a) => a !== name));
    } else {
      setAmenities([...amenities, name]);
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!selectedFloor) newErrors.floor = "Floor Selection is required";
    if (!roomNumber) newErrors.roomNumber = "Room Number is required";
    if (!rent) newErrors.rent = "Monthly Rent is required";

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    setTimeout(() => {
      setIsLoading(false);
      setShowSuccess(true);
    }, 1200);
  };

  const handleCloseModal = () => {
    setShowSuccess(false);
    router.push(`/properties/${property.id}/floors/${floor.id}/rooms`);
  };

  return (
    <div className="space-y-6 max-w-md mx-auto">
      {/* Success Modal Backdrop */}
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-container-lowest p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">Room Created</h3>
            <p className="text-xs text-ink-muted mb-8 leading-relaxed">
              Your new unit has been successfully registered on the floor layout. You can now allocate beds.
            </p>
            <button
              onClick={handleCloseModal}
              className="w-full py-3 bg-surface-inverse text-ink-inverse font-bold rounded-xl hover:opacity-90 transition-opacity cursor-pointer text-sm"
            >
              Back to Room List
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href={`/properties/${property.id}/floors/${floor.id}/rooms`}
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">Add Room</h1>
          <p className="text-xs text-ink-muted">Create a new living unit under floor level: {floor.name}.</p>
        </div>
      </div>

      {/* Form Fields */}
      <form onSubmit={handleFormSubmit} className="space-y-5">
        {/* Floor Selection */}
        <div className="space-y-1.5">
          <label htmlFor="floor" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Floor Selection
          </label>
          <select
            id="floor"
            value={selectedFloor}
            onChange={(e) => setSelectedFloor(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            disabled={isLoading}
          >
            {property.floors.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </div>

        {/* Room Number */}
        <div className="space-y-1.5">
          <label htmlFor="room_number" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Room Number / Name
          </label>
          <div className="relative">
            <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
              <Home className="size-4.5" />
            </span>
            <input
              id="room_number"
              type="text"
              placeholder="e.g. 104-A"
              value={roomNumber}
              onChange={(e) => setRoomNumber(e.target.value)}
              className={`w-full rounded-xl border ${
                errors.roomNumber ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
              } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
              disabled={isLoading}
            />
          </div>
          {errors.roomNumber && <p className="text-xs text-status-critical">{errors.roomNumber}</p>}
        </div>

        {/* Sharing Type & Category grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label htmlFor="sharing" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
              Sharing Type
            </label>
            <select
              id="sharing"
              value={sharingType}
              onChange={(e) => setSharingType(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              disabled={isLoading}
            >
              <option value="single">Single Sharing</option>
              <option value="double">Double Sharing</option>
              <option value="triple">Triple Sharing</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="category" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
              Category
            </label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              disabled={isLoading}
            >
              <option value="ac">Air Conditioned (AC)</option>
              <option value="non-ac">Non-AC</option>
            </select>
          </div>
        </div>

        {/* Monthly Rent */}
        <div className="space-y-1.5">
          <label htmlFor="rent" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Monthly Rent (₹)
          </label>
          <div className="relative">
            <span className="absolute inset-y-0 left-0 flex items-center pl-4 text-sm font-bold text-ink-muted select-none">
              ₹
            </span>
            <input
              id="rent"
              type="number"
              placeholder="0.00"
              value={rent}
              onChange={(e) => setRent(e.target.value)}
              className={`w-full rounded-xl border ${
                errors.rent ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
              } bg-surface-card py-2.5 pl-8 pr-4 font-mono text-sm text-ink outline-none transition-all focus:ring-4`}
              disabled={isLoading}
            />
          </div>
          {errors.rent && <p className="text-xs text-status-critical">{errors.rent}</p>}
          <p className="text-[10px] text-ink-faint italic ml-1">Excludes local utility bills and deposit.</p>
        </div>

        {/* Amenities Selection (Toggles) */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Included Amenities
          </label>
          <div className="flex flex-wrap gap-2">
            {[
              { name: "Wi-Fi", icon: Wifi },
              { name: "Cleaning", icon: Sparkles },
              { name: "Laundry", icon: Sparkles },
            ].map((amenity) => {
              const selected = amenities.includes(amenity.name);
              const Icon = amenity.icon;
              return (
                <button
                  key={amenity.name}
                  type="button"
                  onClick={() => toggleAmenity(amenity.name)}
                  className={`rounded-xl border px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1 cursor-pointer transition-colors ${
                    selected
                      ? "bg-accent-soft text-accent border-accent/30"
                      : "bg-surface-card text-ink-muted border-border hover:bg-surface-page"
                  }`}
                  disabled={isLoading}
                >
                  <Icon className="size-3.5" />
                  {amenity.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Action button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full bg-accent text-ink-inverse hover:bg-accent-hover font-semibold py-3 px-6 rounded-xl flex items-center justify-center gap-2 cursor-pointer transition-colors shadow-sm disabled:opacity-50"
        >
          {isLoading ? "Registering Room..." : "Add Room"}
        </button>

        <p className="text-center text-[10px] text-ink-faint">
          Registered units will default to the Available status.
        </p>
      </form>
    </div>
  );
}
