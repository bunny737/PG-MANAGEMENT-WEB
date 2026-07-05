"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Home,
  CreditCard,
  UserCheck,
  CheckCircle2,
  CheckCircle as SelectedIcon,
  Circle as UnselectedIcon,
  Activity,
  Landmark,
  LoaderCircle
} from "lucide-react";
import {
  listProperties,
  listBuildings,
  listFloors,
  listRooms,
  createResident,
  updateResidentStatus,
  createAdmission,
  type Property,
  type Building,
  type Floor,
  type Room,
  type Bed,
  ApiError
} from "@/lib/api";

export function AdmissionWizard() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [showSuccess, setShowSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Step 1: Personal Info
  const [personalInfo, setPersonalInfo] = useState({
    name: "",
    email: "",
    phone: "",
    emergencyName: "",
    emergencyPhone: ""
  });
  const [errorsStep1, setErrorsStep1] = useState<Record<string, string>>({});

  // Step 2: Room & Bed Selector (Dynamic states)
  const [properties, setProperties] = useState<Property[]>([]);
  const [selectedPropertyId, setSelectedPropertyId] = useState("");
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [selectedBuildingId, setSelectedBuildingId] = useState("");
  const [floors, setFloors] = useState<Floor[]>([]);
  const [selectedFloorId, setSelectedFloorId] = useState("");
  const [rooms, setRooms] = useState<Room[]>([]);
  
  const [selectedRoomId, setSelectedRoomId] = useState("");
  const [selectedBedId, setSelectedBedId] = useState("");
  const [selectedRoomObj, setSelectedRoomObj] = useState<Room | null>(null);
  const [selectedBedObj, setSelectedBedObj] = useState<Bed | null>(null);

  const [isLoadingLayout, setIsLoadingLayout] = useState(false);

  // Step 3: Contract & Fees
  const [leaseTerm, setLeaseTerm] = useState("6_months");
  const [foodPreference, setFoodPreference] = useState<"with_food" | "without_food">("with_food");
  const [overrideRate, setOverrideRate] = useState("0.00");
  const [deposit, setDeposit] = useState("5000.00"); // default deposit amount

  // Step 4: Collection
  const [paymentMode, setPaymentMode] = useState("upi");

  // Load properties on mount
  useEffect(() => {
    listProperties()
      .then((data) => {
        setProperties(data);
        if (data.length > 0) {
          setSelectedPropertyId(data[0].id);
        }
      })
      .catch((err) => console.error("Failed to load properties:", err));
  }, []);

  // Load buildings when property changes
  useEffect(() => {
    if (!selectedPropertyId) return;
    setTimeout(() => setIsLoadingLayout(true), 0);
    listBuildings(selectedPropertyId)
      .then((data) => {
        setBuildings(data);
        if (data.length > 0) {
          setSelectedBuildingId(data[0].id);
        } else {
          setSelectedBuildingId("");
          setFloors([]);
          setSelectedFloorId("");
          setRooms([]);
          setIsLoadingLayout(false);
        }
      })
      .catch((err) => {
        console.error("Failed to load buildings:", err);
        setIsLoadingLayout(false);
      });
  }, [selectedPropertyId]);

  // Load floors when building changes
  useEffect(() => {
    if (!selectedBuildingId) return;
    listFloors(selectedBuildingId)
      .then((data) => {
        setFloors(data);
        if (data.length > 0) {
          setSelectedFloorId(data[0].id);
        } else {
          setSelectedFloorId("");
          setRooms([]);
          setIsLoadingLayout(false);
        }
      })
      .catch((err) => {
        console.error("Failed to load floors:", err);
        setIsLoadingLayout(false);
      });
  }, [selectedBuildingId]);

  // Load rooms when floor changes
  useEffect(() => {
    if (!selectedFloorId) {
      setTimeout(() => {
        setRooms([]);
        setIsLoadingLayout(false);
      }, 0);
      return;
    }
    listRooms(selectedFloorId)
      .then((data) => {
        setRooms(data);
        setIsLoadingLayout(false);
      })
      .catch((err) => {
        console.error("Failed to load rooms:", err);
        setIsLoadingLayout(false);
      });
  }, [selectedFloorId]);

  // Pre-fill rate override when room selection or food preference changes
  useEffect(() => {
    if (selectedRoomObj) {
      const defaultRate =
        foodPreference === "with_food"
          ? selectedRoomObj.rack_rate_with_food
          : selectedRoomObj.rack_rate_without_food;
      setTimeout(() => setOverrideRate(defaultRate), 0);
    }
  }, [foodPreference, selectedRoomObj]);

  const handleSelectBed = (room: Room, bed: Bed) => {
    setSelectedRoomId(room.id);
    setSelectedRoomObj(room);
    setSelectedBedId(bed.id);
    setSelectedBedObj(bed);
  };

  // Step 1 validation
  const validateStep1 = () => {
    const errs: Record<string, string> = {};
    if (!personalInfo.name.trim()) errs.name = "Full Name is required";
    if (!personalInfo.email.trim()) errs.email = "Email is required";
    if (!personalInfo.phone.trim()) errs.phone = "Phone Number is required";
    setErrorsStep1(errs);
    return Object.keys(errs).length === 0;
  };

  const handleNextStep = async () => {
    if (step === 1) {
      if (validateStep1()) setStep(2);
    } else if (step === 2) {
      if (!selectedRoomId || !selectedBedId) {
        alert("Please select an available bed to continue.");
        return;
      }
      setStep(3);
    } else if (step === 3) {
      setStep(4);
    } else if (step === 4) {
      await handleCompleteAdmission();
    }
  };

  const handlePrevStep = () => {
    if (step === 2) setStep(1);
    else if (step === 3) setStep(2);
    else if (step === 4) setStep(3);
  };

  const handleCompleteAdmission = async () => {
    setIsSubmitting(true);
    try {
      // 1. Split full name
      const nameParts = personalInfo.name.trim().split(/\s+/);
      const first_name = nameParts[0] || "Resident";
      const last_name = nameParts.slice(1).join(" ") || "";

      // 2. Create Resident profile
      const residentObj = await createResident({
        property: selectedPropertyId,
        first_name,
        last_name,
        phone: personalInfo.phone.trim(),
        email: personalInfo.email.trim(),
        emergency_contact_name: personalInfo.emergencyName.trim(),
        emergency_contact_phone: personalInfo.emergencyPhone.trim()
      });

      // 3. Update status to 'reserved' (required transition before checking in)
      await updateResidentStatus(residentObj.id, "reserved");

      // 4. Create check-in admission record
      await createAdmission({
        resident: residentObj.id,
        bed: selectedBedId,
        joining_date: new Date().toISOString().split("T")[0],
        billing_mode: "monthly",
        food_preference: foodPreference,
        advance_amount: parseFloat(deposit).toFixed(2),
        advance_mode: paymentMode
      });

      setShowSuccess(true);
    } catch (err) {
      console.error(err);
      alert("Failed to submit admission: " + (err instanceof ApiError ? err.message : "Error"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRedirect = () => {
    setShowSuccess(false);
    router.push("/residents");
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Success Modal */}
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-card p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10 text-emerald-600" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">Admission Complete</h3>
            <p className="text-xs text-ink-muted mb-8 leading-relaxed">
              Resident <strong>{personalInfo.name}</strong> was admitted successfully. Bed <strong>{selectedRoomObj?.room_number}-{selectedBedObj?.bed_number}</strong> has been allocated, and lease contracts have been issued.
            </p>
            <button
              onClick={handleRedirect}
              className="w-full py-3 bg-surface-inverse text-ink-inverse font-bold rounded-xl hover:opacity-90 transition-opacity cursor-pointer text-sm"
            >
              Go to Resident Directory
            </button>
          </div>
        </div>
      )}

      {/* Header and Step Progress Indicators */}
      <div className="bg-surface-card border border-border rounded-2xl overflow-hidden shadow-sm">
        <div className="p-5 flex flex-col sm:flex-row justify-between sm:items-center gap-3">
          <div>
            <h1 className="text-lg font-bold text-ink">Admission Wizard</h1>
            <p className="text-xs text-ink-muted mt-0.5">Onboard a new tenant and allocate room assets.</p>
          </div>
        </div>

        {/* Step Progress Line */}
        <div className="w-full bg-surface-page h-1 flex">
          <div className={`h-full ${step >= 1 ? "bg-accent" : "bg-transparent"} transition-all`} style={{ width: "25%" }} />
          <div className={`h-full ${step >= 2 ? "bg-accent" : "bg-transparent"} transition-all`} style={{ width: "25%" }} />
          <div className={`h-full ${step >= 3 ? "bg-accent" : "bg-transparent"} transition-all`} style={{ width: "25%" }} />
          <div className={`h-full ${step >= 4 ? "bg-accent" : "bg-transparent"} transition-all`} style={{ width: "25%" }} />
        </div>

        {/* Navigation Step Labels */}
        <div className="grid grid-cols-4 px-5 py-3 text-[10px] sm:text-xs font-bold uppercase tracking-wider text-ink-faint">
          <span className={step >= 1 ? "text-accent" : ""}>1. Personal Info</span>
          <span className={step >= 2 ? "text-accent" : ""}>2. Room & Bed</span>
          <span className={step >= 3 ? "text-accent" : ""}>3. Lease Details</span>
          <span className={step >= 4 ? "text-accent" : ""}>4. Collection</span>
        </div>
      </div>

      {/* Step 1: Personal Info */}
      {step === 1 && (
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in max-w-2xl mx-auto">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5">
            Tenant Personal Information
          </h2>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Full Name */}
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="name" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Full Name <span className="text-status-critical">*</span>
              </label>
              <input
                id="name"
                type="text"
                placeholder="e.g. Eleanor Shellstrop"
                value={personalInfo.name}
                onChange={(e) => setPersonalInfo({ ...personalInfo, name: e.target.value })}
                className={`w-full rounded-xl border ${
                  errorsStep1.name ? "border-status-critical" : "border-border"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
              />
              {errorsStep1.name && <p className="text-xs text-status-critical">{errorsStep1.name}</p>}
            </div>

            {/* Email Address */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Email Address <span className="text-status-critical">*</span>
              </label>
              <input
                id="email"
                type="email"
                placeholder="e.g. eleanor@goodplace.com"
                value={personalInfo.email}
                onChange={(e) => setPersonalInfo({ ...personalInfo, email: e.target.value })}
                className={`w-full rounded-xl border ${
                  errorsStep1.email ? "border-status-critical" : "border-border"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
              />
              {errorsStep1.email && <p className="text-xs text-status-critical">{errorsStep1.email}</p>}
            </div>

            {/* Phone Number */}
            <div className="space-y-1.5">
              <label htmlFor="phone" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Phone Number <span className="text-status-critical">*</span>
              </label>
              <input
                id="phone"
                type="text"
                placeholder="e.g. +91 9876543210"
                value={personalInfo.phone}
                onChange={(e) => setPersonalInfo({ ...personalInfo, phone: e.target.value })}
                className={`w-full rounded-xl border ${
                  errorsStep1.phone ? "border-status-critical" : "border-border"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
              />
              {errorsStep1.phone && <p className="text-xs text-status-critical">{errorsStep1.phone}</p>}
            </div>

            {/* Emergency Contact section */}
            <div className="space-y-1.5 sm:col-span-2 pt-2 border-t border-border/50">
              <span className="text-xs font-bold text-ink-faint uppercase tracking-wider flex items-center gap-1">
                <UserCheck className="size-3.5" />
                Emergency contact guardian
              </span>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="emergencyName" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Guardian Name
              </label>
              <input
                id="emergencyName"
                type="text"
                placeholder="e.g. Michael Chidi"
                value={personalInfo.emergencyName}
                onChange={(e) => setPersonalInfo({ ...personalInfo, emergencyName: e.target.value })}
                className="w-full rounded-xl border border-border bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="emergencyPhone" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Guardian Phone
              </label>
              <input
                id="emergencyPhone"
                type="text"
                placeholder="e.g. +91 9876543211"
                value={personalInfo.emergencyPhone}
                onChange={(e) => setPersonalInfo({ ...personalInfo, emergencyPhone: e.target.value })}
                className="w-full rounded-xl border border-border bg-surface-card px-4 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
              />
            </div>
          </div>
        </div>
      )}

      {/* Step 2: Room & Bed Selector */}
      {step === 2 && (
        <div className="space-y-6 animate-fade-in">
          {/* Layout select dropdowns */}
          <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Property Selector */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Property</label>
              <select
                value={selectedPropertyId}
                onChange={(e) => setSelectedPropertyId(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
              >
                <option value="">Select Property</option>
                {properties.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            {/* Building Selector */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Building Block</label>
              <select
                value={selectedBuildingId}
                onChange={(e) => setSelectedBuildingId(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                disabled={!selectedPropertyId}
              >
                <option value="">Select Building</option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>Block {b.name}</option>
                ))}
              </select>
            </div>

            {/* Floor Selector */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Floor Level</label>
              <select
                value={selectedFloorId}
                onChange={(e) => setSelectedFloorId(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                disabled={!selectedBuildingId}
              >
                <option value="">Select Floor</option>
                {floors.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold tracking-tight text-ink">Select a Bed</h2>
              <p className="text-xs text-ink-muted">Choose an available bed for the resident from the selected layout.</p>
            </div>
          </div>

          {isLoadingLayout ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-sm text-ink-muted">
              <LoaderCircle className="size-6 animate-spin text-accent" />
              <p>Retrieving available beds...</p>
            </div>
          ) : rooms.length > 0 ? (
            /* Grid Layout of Room Cards */
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {rooms.map((room) => (
                <div key={room.id} className="bg-surface-card border border-border rounded-2xl flex flex-col overflow-hidden shadow-sm">
                  <div className="px-5 py-3.5 border-b border-border flex justify-between items-center bg-surface-page/40">
                    <div className="flex items-center gap-2">
                      <Home className="size-4.5 text-accent" />
                      <h3 className="font-bold text-ink text-sm">Room {room.room_number}</h3>
                    </div>
                    <span className="text-[10px] font-bold text-ink-muted uppercase bg-surface-page border border-border px-2 py-0.5 rounded">
                      {room.sharing_type}-sharing
                    </span>
                  </div>
                  <div className="p-4 space-y-2">
                    {room.beds && room.beds.map((bed) => {
                      const isSelected = selectedBedId === bed.id;
                      const isAvailable = bed.status === "available";

                      return (
                        <div
                          key={bed.id}
                          onClick={() => isAvailable && handleSelectBed(room, bed)}
                          className={`flex items-center justify-between px-3 py-2 border rounded-xl transition-all ${
                            !isAvailable
                              ? "border-border/40 bg-surface-page/30 opacity-55 cursor-not-allowed text-ink-faint"
                              : isSelected
                              ? "border-accent bg-accent-soft text-accent cursor-pointer"
                              : "border-border hover:bg-surface-page text-ink cursor-pointer"
                          }`}
                        >
                          <div className="flex items-center gap-2.5">
                            <div className="size-6.5 rounded-full bg-surface-page border border-border text-[10px] font-bold flex items-center justify-center shrink-0">
                              {bed.bed_number.split("-").pop() || "Bed"}
                            </div>
                            <div>
                              <p className="text-xs font-bold">Bed {bed.bed_number}</p>
                              <p className="text-[9px] text-ink-muted capitalize">{bed.status}</p>
                            </div>
                          </div>
                          {isSelected ? (
                            <SelectedIcon className="size-3.5 text-accent" />
                          ) : (
                            <UnselectedIcon className="size-3.5 text-ink-faint" />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-16 text-xs text-ink-muted border-2 border-dashed border-border rounded-2xl bg-surface-card">
              No rooms registered on this floor level.
            </div>
          )}
        </div>
      )}

      {/* Step 3: Contract & Fees */}
      {step === 3 && (
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in max-w-2xl mx-auto">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5">
            Lease & Contract Setup
          </h2>

          <div className="space-y-4">
            {/* Lease Term */}
            <div className="space-y-1.5">
              <label htmlFor="lease" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Lease Contract Term
              </label>
              <select
                id="lease"
                value={leaseTerm}
                onChange={(e) => setLeaseTerm(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              >
                <option value="6_months">6-Month Agreement</option>
                <option value="12_months">12-Month Agreement</option>
                <option value="semester">Fall Semester &apos;26</option>
              </select>
            </div>

            {/* Food Preference */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Food Preference
              </label>
              <select
                value={foodPreference}
                onChange={(e) => setFoodPreference(e.target.value as "with_food" | "without_food")}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              >
                <option value="with_food">With Food Included</option>
                <option value="without_food">Without Food</option>
              </select>
            </div>

            {/* Grid for Rate and Deposit */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="rate" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Contract Override Rate
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-4 text-xs font-bold text-ink-muted select-none">
                    ₹
                  </span>
                  <input
                    id="rate"
                    type="number"
                    value={overrideRate}
                    onChange={(e) => setOverrideRate(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-8 pr-4 font-mono text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="deposit" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Required Security Deposit
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-4 text-xs font-bold text-ink-muted select-none">
                    ₹
                  </span>
                  <input
                    id="deposit"
                    type="number"
                    value={deposit}
                    onChange={(e) => setDeposit(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-8 pr-4 font-mono text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>
              </div>
            </div>

            {/* Total due preview card */}
            <div className="bg-surface-page border border-border/80 rounded-xl p-4 text-xs space-y-2">
              <div className="flex justify-between items-center text-ink-muted">
                <span>First Month Rent</span>
                <span className="font-mono font-semibold text-ink">₹{Number(overrideRate).toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center text-ink-muted">
                <span>Security Deposit</span>
                <span className="font-mono font-semibold text-ink">₹{Number(deposit).toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-border font-bold text-sm">
                <span className="text-ink">Total Due at Move-In</span>
                <span className="font-mono text-accent">₹{(Number(overrideRate) + Number(deposit)).toFixed(2)}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Step 4: Collection */}
      {step === 4 && (
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in max-w-2xl mx-auto">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5">
            Collect Initial Dues
          </h2>

          <div className="space-y-4">
            <div className="text-center py-4 bg-accent-soft rounded-xl border border-accent/15">
              <p className="text-xs text-ink-muted font-semibold uppercase tracking-wider">Amount to Collect</p>
              <h3 className="text-3xl font-extrabold text-accent mt-1">₹{(Number(overrideRate) + Number(deposit)).toFixed(2)}</h3>
            </div>

            {/* Payment Modes */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Select Payment Mode
              </label>
              <div className="grid grid-cols-3 gap-3 text-center">
                {[
                  { id: "upi", label: "UPI / QR", icon: Activity },
                  { id: "card", label: "Debit/Credit Card", icon: CreditCard },
                  { id: "cash", label: "Cash Payment", icon: Landmark }
                ].map((mode) => {
                  const selected = paymentMode === mode.id;
                  const Icon = mode.icon;
                  return (
                    <div
                      key={mode.id}
                      onClick={() => setPaymentMode(mode.id)}
                      className={`border rounded-xl p-4.5 cursor-pointer transition-all flex flex-col items-center justify-center gap-2 hover:bg-surface-page ${
                        selected
                          ? "border-accent bg-accent-soft text-accent"
                          : "border-border text-ink-muted"
                      }`}
                    >
                      <Icon className="size-5 shrink-0" />
                      <span className="text-[10px] font-bold uppercase tracking-wide">{mode.label}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Summary Details */}
            <div className="bg-surface-page border border-border/80 rounded-xl p-4.5 text-xs space-y-2 leading-relaxed">
              <p className="font-bold text-ink">Admission Summary</p>
              <ul className="list-disc pl-4 space-y-1 mt-1 text-ink-muted">
                <li>Admitting resident: <span className="font-bold text-ink">{personalInfo.name}</span></li>
                <li>Allocated Bed: <span className="font-bold text-ink">Room {selectedRoomObj?.room_number}, Bed {selectedBedObj?.bed_number}</span></li>
                <li>Monthly Rent: <span className="font-bold text-ink">₹{Number(overrideRate).toFixed(2)}</span></li>
                <li>Lease duration term: <span className="font-bold text-ink">{leaseTerm.replace("_", " ")}</span></li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Step Navigation Action Buttons */}
      <div className="bg-surface-card border border-border rounded-2xl p-4 flex items-center justify-between">
        <button
          onClick={handlePrevStep}
          disabled={step === 1 || isSubmitting}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page px-4 py-2 text-xs font-bold text-ink hover:bg-surface-card hover:text-ink disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
        >
          <ArrowLeft className="size-3.5" /> Back
        </button>

        <button
          onClick={handleNextStep}
          disabled={isSubmitting}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-5 py-2 text-xs font-bold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50"
        >
          {isSubmitting && <LoaderCircle className="size-3.5 animate-spin" />}
          {step === 4 ? "Complete Admission" : "Next Step"}
          <ArrowRight className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
