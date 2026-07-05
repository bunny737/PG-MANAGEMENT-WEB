"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Building2, CheckCircle2, LoaderCircle } from "lucide-react";
import { getProperty, createBuilding, type Property, type Building, ApiError } from "@/lib/api";

export function AddBuildingForm({ propertyId }: { propertyId: string }) {
  const router = useRouter();

  const [property, setProperty] = useState<Property | null>(null);
  const [buildingName, setBuildingName] = useState("");
  const [numberOfFloors, setNumberOfFloors] = useState("0");

  const [isLoading, setIsLoading] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [showSuccess, setShowSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [createdBuilding, setCreatedBuilding] = useState<Building | null>(null);

  useEffect(() => {
    let cancelled = false;

    getProperty(propertyId)
      .then((prop) => {
        if (cancelled) return;
        setProperty(prop);
        setIsPageLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("Failed to load property details:", err);
        setIsPageLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [propertyId]);

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!buildingName.trim()) newErrors.buildingName = "Building name is required";
    const floors = Number(numberOfFloors);
    if (numberOfFloors !== "" && (!Number.isInteger(floors) || floors < 0)) {
      newErrors.numberOfFloors = "Enter a whole number of floors (0 or more)";
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    try {
      const result = await createBuilding({
        property: propertyId,
        name: buildingName.trim(),
        number_of_floors: numberOfFloors === "" ? 0 : floors,
      });
      setCreatedBuilding(result);
      setIsLoading(false);
      setShowSuccess(true);
    } catch (err) {
      console.error(err);
      setIsLoading(false);
      if (err instanceof ApiError) {
        const nameErr = err.fieldError("name");
        const floorsErr = err.fieldError("number_of_floors");
        const detailErr = err.message;

        setErrors({
          ...(nameErr ? { buildingName: nameErr } : {}),
          ...(floorsErr ? { numberOfFloors: floorsErr } : {}),
          ...(!nameErr && !floorsErr ? { global: detailErr } : {}),
        });
      } else {
        setErrors({ global: "An unexpected error occurred. Please try again." });
      }
    }
  };

  const handleCloseModal = () => {
    setShowSuccess(false);
    if (createdBuilding) {
      router.push(`/properties/${propertyId}/buildings/${createdBuilding.id}/floors`);
    } else {
      router.push(`/properties/${propertyId}/buildings`);
    }
  };

  if (isPageLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading property details...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-md mx-auto">
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-container-lowest p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">Building Created</h3>
            <p className="text-xs text-ink-muted mb-4 leading-relaxed">
              {createdBuilding && createdBuilding.floors_count > 0
                ? `${createdBuilding.floors_count} floor(s) were created automatically.`
                : "You can add floors to this building next."}
            </p>

            {createdBuilding && (
              <div className="bg-surface-page border border-border rounded-xl p-4 mb-6 text-left space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Building Name:</span>
                  <span className="font-bold text-ink">{createdBuilding.name}</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Property:</span>
                  <span className="font-semibold text-ink text-right max-w-[180px] truncate">
                    {property?.name || "Selected Property"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Floors Created:</span>
                  <span className="font-mono font-bold text-accent">{createdBuilding.floors_count}</span>
                </div>
              </div>
            )}

            <button
              onClick={handleCloseModal}
              className="w-full py-3 bg-surface-inverse text-ink-inverse font-bold rounded-xl hover:opacity-90 transition-opacity cursor-pointer text-sm"
            >
              View Floors
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Link
          href={`/properties/${propertyId}/buildings`}
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">Add Building</h1>
          <p className="text-xs text-ink-muted">
            {property ? `Add another block to ${property.name}.` : "Add another block to this property."}
          </p>
        </div>
      </div>

      <div className="bg-surface-card p-5 rounded-2xl border border-border shadow-sm flex items-start gap-4">
        <div className="size-11 rounded-lg bg-accent-soft text-accent border border-accent/15 flex items-center justify-center shrink-0">
          <Building2 className="size-5.5" />
        </div>
        <div className="space-y-0.5 text-xs">
          <p className="font-bold text-accent uppercase tracking-wider">Property Management</p>
          <h2 className="text-sm font-bold text-ink">Building Registration</h2>
          <p className="text-ink-muted leading-relaxed mt-1">
            Use this for a physically separate block (e.g. &quot;Block A&quot;, &quot;Block B&quot;) — not for floors
            within the same building.
          </p>
        </div>
      </div>

      <form onSubmit={handleFormSubmit} className="space-y-5">
        {errors.global && (
          <div className="p-3 bg-status-critical-soft border border-status-critical/15 text-status-critical rounded-xl text-xs font-medium">
            {errors.global}
          </div>
        )}

        <div className="space-y-1.5">
          <label htmlFor="building_name" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Building Name <span className="text-status-critical">*</span>
          </label>
          <input
            id="building_name"
            type="text"
            placeholder="e.g. Block A, Main Building"
            value={buildingName}
            onChange={(e) => setBuildingName(e.target.value)}
            className={`w-full rounded-xl border ${
              errors.buildingName ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
            } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
            disabled={isLoading}
          />
          {errors.buildingName && <p className="text-xs text-status-critical ml-1">{errors.buildingName}</p>}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="number_of_floors" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Number of Floors
          </label>
          <input
            id="number_of_floors"
            type="number"
            min={0}
            max={100}
            step={1}
            placeholder="0"
            value={numberOfFloors}
            onChange={(e) => setNumberOfFloors(e.target.value)}
            className={`w-full rounded-xl border ${
              errors.numberOfFloors ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
            } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
            disabled={isLoading}
          />
          {errors.numberOfFloors ? (
            <p className="text-xs text-status-critical ml-1">{errors.numberOfFloors}</p>
          ) : (
            <p className="text-xs text-ink-muted ml-1">
              We&apos;ll create these automatically — Ground Floor, 1st Floor, 2nd Floor, and so on.
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={isLoading}
          className="w-full bg-accent text-ink-inverse hover:bg-accent-hover font-semibold py-3 px-6 rounded-xl flex items-center justify-center gap-2 cursor-pointer transition-colors shadow-sm disabled:opacity-50"
        >
          {isLoading ? "Creating Building..." : "Add Building"}
        </button>
      </form>
    </div>
  );
}
