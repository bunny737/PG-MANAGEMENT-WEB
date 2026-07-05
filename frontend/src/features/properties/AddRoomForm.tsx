"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Home, CheckCircle2, LoaderCircle } from "lucide-react";
import { getFloor, listFloors, createRoom, createBed, type Floor, type Room, ApiError } from "@/lib/api";

export function AddRoomForm({ propertyId, floorId }: { propertyId: string; floorId: string }) {
  const router = useRouter();

  const [floors, setFloors] = useState<Floor[]>([]);
  const [selectedFloor, setSelectedFloor] = useState(floorId);
  const [roomNumber, setRoomNumber] = useState("");
  const [sharingType, setSharingType] = useState("double");
  const [category, setCategory] = useState("ac");
  const [rentWithFood, setRentWithFood] = useState("");
  const [rentWithoutFood, setRentWithoutFood] = useState("");

  const [isLoading, setIsLoading] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [showSuccess, setShowSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [createdRoom, setCreatedRoom] = useState<Room | null>(null);
  const [generatedBeds, setGeneratedBeds] = useState<string[]>([]);

  // Track propertyId / floorId changes to reset page loading state (React render-time adjustment pattern)
  const [prevIds, setPrevIds] = useState({ propertyId, floorId });
  if (propertyId !== prevIds.propertyId || floorId !== prevIds.floorId) {
    setPrevIds({ propertyId, floorId });
    setIsPageLoading(true);
  }

  useEffect(() => {
    let cancelled = false;

    getFloor(floorId)
      .then((floorData) => {
        if (cancelled) return;
        setSelectedFloor(floorId);
        return listFloors(floorData.building);
      })
      .then((floorsList) => {
        if (cancelled || !floorsList) return;
        setFloors(floorsList);
        setIsPageLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("Failed to load layout details:", err);
        setIsPageLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [propertyId, floorId]);

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!selectedFloor) newErrors.floor = "Floor Selection is required";
    if (!roomNumber.trim()) newErrors.roomNumber = "Room Number is required";
    if (!rentWithFood) newErrors.rentWithFood = "Monthly Rent (With Food) is required";
    if (!rentWithoutFood) newErrors.rentWithoutFood = "Monthly Rent (Without Food) is required";

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    // Map sharing type string to backend integer
    const capacityMap: Record<string, number> = {
      single: 1,
      double: 2,
      triple: 3,
      quad: 4,
      five: 5,
      six: 6,
      seven: 7,
      eight: 8,
    };
    const capacity = capacityMap[sharingType] || 2;

    try {
      const room = await createRoom({
        floor: selectedFloor,
        room_number: roomNumber.trim(),
        sharing_type: capacity,
        category: category as "ac" | "non_ac",
        rack_rate_with_food: parseFloat(rentWithFood).toFixed(2),
        rack_rate_without_food: parseFloat(rentWithoutFood).toFixed(2),
      });

      // Automatically create beds for the room
      const bedLabels = ["A", "B", "C", "D", "E", "F", "G", "H"];
      const bedPromises = [];
      const generatedNames: string[] = [];

      for (let i = 0; i < capacity; i++) {
        const suffix = capacity === 1 ? "A" : bedLabels[i];
        const bedName = `${room.room_number}-${suffix}`;
        generatedNames.push(bedName);

        bedPromises.push(
          createBed({
            room: room.id,
            bed_number: bedName,
          })
        );
      }

      await Promise.all(bedPromises);

      setCreatedRoom(room);
      setGeneratedBeds(generatedNames);
      setIsLoading(false);
      setShowSuccess(true);
    } catch (err) {
      console.error(err);
      setIsLoading(false);
      if (err instanceof ApiError) {
        // Handle field level validation errors
        const roomNumErr = err.fieldError("room_number");
        const withFoodErr = err.fieldError("rack_rate_with_food");
        const withoutFoodErr = err.fieldError("rack_rate_without_food");
        const floorErr = err.fieldError("floor");
        const capacityErr = err.fieldError("sharing_type");
        const detailErr = err.message;

        setErrors({
          ...(roomNumErr ? { roomNumber: roomNumErr } : {}),
          ...(withFoodErr ? { rentWithFood: withFoodErr } : {}),
          ...(withoutFoodErr ? { rentWithoutFood: withoutFoodErr } : {}),
          ...(floorErr ? { floor: floorErr } : {}),
          ...(capacityErr ? { sharingType: capacityErr } : {}),
          ...(!roomNumErr && !withFoodErr && !withoutFoodErr && !floorErr && !capacityErr ? { global: detailErr } : {}),
        });
      } else {
        setErrors({ global: "An unexpected error occurred. Please try again." });
      }
    }
  };

  const handleCloseModal = () => {
    setShowSuccess(false);
    router.push(`/properties/${propertyId}/floors/${selectedFloor}/rooms`);
  };

  if (isPageLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading floor details...</p>
      </div>
    );
  }

  const activeFloor = floors.find((f) => f.id === selectedFloor);

  return (
    <div className="space-y-6 max-w-md mx-auto">
      {/* Success Modal Backdrop */}
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-container-lowest p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">Room & Beds Created</h3>
            <p className="text-xs text-ink-muted mb-4 leading-relaxed">
              Your new unit and its bed layout have been successfully registered.
            </p>

            {/* Added Details Card */}
            {createdRoom && (
              <div className="bg-surface-page border border-border rounded-xl p-4 mb-6 text-left space-y-2.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Room Number:</span>
                  <span className="font-bold text-ink">{createdRoom.room_number}</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Floor Level:</span>
                  <span className="font-semibold text-ink">{activeFloor?.name || "Selected Floor"}</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Sharing Type:</span>
                  <span className="font-semibold text-ink capitalize">{sharingType} Sharing</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-muted font-medium">Monthly Rates:</span>
                  <span className="font-mono font-semibold text-ink text-right">
                    ₹{createdRoom.rack_rate_with_food} (Food)<br />
                    ₹{createdRoom.rack_rate_without_food} (No Food)
                  </span>
                </div>
                <div className="border-t border-border/60 pt-2 flex flex-col gap-1 text-xs">
                  <span className="text-ink-muted font-medium">Generated Beds:</span>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {generatedBeds.map((bedNum) => (
                      <span key={bedNum} className="px-2 py-0.5 rounded bg-accent-soft text-accent text-[10px] font-bold border border-accent/10">
                        {bedNum}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

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
          href={`/properties/${propertyId}/floors/${floorId}/rooms`}
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">Add Room</h1>
          <p className="text-xs text-ink-muted">Create a new living unit under floor level: {activeFloor?.name || "Floor"}.</p>
        </div>
      </div>

      {/* Form Fields */}
      <form onSubmit={handleFormSubmit} className="space-y-5">
        {errors.global && (
          <div className="p-3 bg-status-critical-soft border border-status-critical/15 text-status-critical rounded-xl text-xs font-medium">
            {errors.global}
          </div>
        )}

        {/* Floor Selection */}
        <div className="space-y-1.5">
          <label htmlFor="floor" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Floor Selection <span className="text-status-critical">*</span>
          </label>
          <select
            id="floor"
            value={selectedFloor}
            onChange={(e) => setSelectedFloor(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            disabled={isLoading}
          >
            {floors.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          {errors.floor && <p className="text-xs text-status-critical ml-1">{errors.floor}</p>}
        </div>

        {/* Room Number */}
        <div className="space-y-1.5">
          <label htmlFor="room_number" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Room Number / Name <span className="text-status-critical">*</span>
          </label>
          <div className="relative">
            <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
              <Home className="size-4.5" />
            </span>
            <input
              id="room_number"
              type="text"
              placeholder="e.g. 104, 201-A"
              value={roomNumber}
              onChange={(e) => setRoomNumber(e.target.value)}
              className={`w-full rounded-xl border ${
                errors.roomNumber ? "border-status-critical/20 focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
              } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
              disabled={isLoading}
            />
          </div>
          {errors.roomNumber && <p className="text-xs text-status-critical ml-1">{errors.roomNumber}</p>}
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
              <option value="quad">Four Sharing</option>
              <option value="five">Five Sharing</option>
              <option value="six">Six Sharing</option>
              <option value="seven">Seven Sharing</option>
              <option value="eight">Eight Sharing</option>
            </select>
            {errors.sharingType && <p className="text-xs text-status-critical ml-1">{errors.sharingType}</p>}
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
              <option value="non_ac">Non-AC</option>
            </select>
          </div>
        </div>

        {/* Monthly Rents Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label htmlFor="rent_with_food" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
              Rent (With Food) <span className="text-status-critical">*</span>
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-4 text-sm font-bold text-ink-muted select-none">
                ₹
              </span>
              <input
                id="rent_with_food"
                type="number"
                placeholder="0.00"
                value={rentWithFood}
                onChange={(e) => setRentWithFood(e.target.value)}
                className={`w-full rounded-xl border ${
                  errors.rentWithFood ? "border-status-critical/20 focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                } bg-surface-card py-2.5 pl-8 pr-4 font-mono text-sm text-ink outline-none transition-all focus:ring-4`}
                disabled={isLoading}
              />
            </div>
            {errors.rentWithFood && <p className="text-xs text-status-critical ml-1">{errors.rentWithFood}</p>}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="rent_without_food" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
              Rent (No Food) <span className="text-status-critical">*</span>
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-4 text-sm font-bold text-ink-muted select-none">
                ₹
              </span>
              <input
                id="rent_without_food"
                type="number"
                placeholder="0.00"
                value={rentWithoutFood}
                onChange={(e) => setRentWithoutFood(e.target.value)}
                className={`w-full rounded-xl border ${
                  errors.rentWithoutFood ? "border-status-critical/20 focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                } bg-surface-card py-2.5 pl-8 pr-4 font-mono text-sm text-ink outline-none transition-all focus:ring-4`}
                disabled={isLoading}
              />
            </div>
            {errors.rentWithoutFood && <p className="text-xs text-status-critical ml-1">{errors.rentWithoutFood}</p>}
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
