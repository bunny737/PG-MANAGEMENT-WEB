"use client";

import React, { useState, useEffect, useRef } from "react";
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
import { useTranslations } from "next-intl";
import {
  getPropertyLayout,
  listProperties,
  listBuildings,
  listFloors,
  listRooms,
  createResident,
  updateResidentStatus,
  createAdmission,
  type DepositMode,
  type Property,
  type Building,
  type Floor,
  type Room,
  type Bed,
  ApiError
} from "@/lib/api";

import { findBedChain, type BedChain } from "@/lib/admissionPreselect";
import { localDateKey } from "@/lib/date";
import { addMoney, compareMoney, formatMoney, isMoneyInput, subtractMoney, toMoneyString, ZERO } from "@/lib/money";

// The local calendar day, not UTC: between midnight and 05:30 IST the UTC date is still yesterday.
const todayISO = () => localDateKey(new Date());

/** The amount as the API's two-place string, "0.00" when blank (an empty input means nothing). */
const moneyOrZero = (value: string) => (value.trim() === "" ? ZERO : toMoneyString(value.trim()));

interface AdmissionWizardProps {
  /** A property, optionally with a bed. A bed picked on the Vacancies screen pre-selects property → building →
   * floor → room → bed for step 2; a property alone (the Getting started checklist) pre-selects just the
   * property. The wizard still starts at step 1, so the resident's details are collected first. */
  preselect?: { propertyId: string; bedId?: string };
}

export function AdmissionWizard({ preselect }: AdmissionWizardProps = {}) {
  const router = useRouter();
  const t = useTranslations("admissions");

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

  // Step 4: Collection. A resident often pays only part on joining, so staff enter what was actually
  // received now. `null` means not edited yet: the full agreed amount is shown (and sent), so it also follows a
  // later change of food plan. The rest of the rent stays on the first invoice and the
  // rest of the deposit is recorded later from the resident's profile.
  const [rentPaid, setRentPaid] = useState<string | null>(null);
  const [depositPaid, setDepositPaid] = useState<string | null>(null);
  const [paymentMode, setPaymentMode] = useState<DepositMode>("upi");
  const [collectedOn, setCollectedOn] = useState(todayISO);
  const [step3Error, setStep3Error] = useState("");
  const [step4Errors, setStep4Errors] = useState<{ rent?: string; deposit?: string; date?: string }>({});

  // The requested bed's chain, resolved BEFORE any "pick the first one" default below runs and consumed as
  // each level loads. Without this, those defaults (each loader's data[0]) would overwrite the requested bed
  // as their async responses arrive.
  const chainRef = useRef<BedChain | null>(null);
  const preselectPropertyId = preselect?.propertyId;
  const preselectBedId = preselect?.bedId;

  // Load properties on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listProperties();
        if (cancelled) return;
        setProperties(data);
        let propertyId = data[0]?.id ?? "";
        if (preselectPropertyId && data.some((property) => property.id === preselectPropertyId)) {
          // A property the user can see is kept even when its bed can't be resolved below.
          propertyId = preselectPropertyId;
          if (preselectBedId) {
            try {
              const chain = findBedChain(await getPropertyLayout(preselectPropertyId), preselectBedId);
              if (chain) chainRef.current = chain;
            } catch {
              // No layout access or a stale bed link: the property's normal first-of-each defaults apply.
            }
          }
        }
        if (!cancelled && propertyId) setSelectedPropertyId(propertyId);
      } catch (err) {
        console.error("Failed to load properties:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [preselectPropertyId, preselectBedId]);

  // Load buildings when property changes
  useEffect(() => {
    if (!selectedPropertyId) return;
    setTimeout(() => setIsLoadingLayout(true), 0);
    listBuildings(selectedPropertyId)
      .then((data) => {
        setBuildings(data);
        if (data.length > 0) {
          const wanted = data.find((building) => building.id === chainRef.current?.buildingId);
          if (!wanted) chainRef.current = null;
          setSelectedBuildingId((wanted ?? data[0]).id);
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
          const wanted = data.find((floor) => floor.id === chainRef.current?.floorId);
          if (!wanted) chainRef.current = null;
          setSelectedFloorId((wanted ?? data[0]).id);
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
        const chain = chainRef.current;
        chainRef.current = null;
        const room = chain ? data.find((candidate) => candidate.id === chain.roomId) : undefined;
        const bed = room?.beds?.find((candidate) => candidate.id === chain?.bedId);
        if (room && bed && bed.status === "available") {
          setSelectedRoomId(room.id);
          setSelectedRoomObj(room);
          setSelectedBedId(bed.id);
          setSelectedBedObj(bed);
        }
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
    if (!personalInfo.name.trim()) errs.name = t("step1.errName");
    if (!personalInfo.email.trim()) errs.email = t("step1.errEmail");
    if (!personalInfo.phone.trim()) errs.phone = t("step1.errPhone");
    setErrorsStep1(errs);
    return Object.keys(errs).length === 0;
  };

  const handleNextStep = async () => {
    if (step === 1) {
      if (validateStep1()) setStep(2);
    } else if (step === 2) {
      if (!selectedRoomId || !selectedBedId) {
        alert(t("step2.selectBedAlert"));
        return;
      }
      setStep(3);
    } else if (step === 3) {
      if (!isMoneyInput(moneyOrZero(deposit)) || !isMoneyInput(moneyOrZero(overrideRate))) {
        setStep3Error(t("step3.errAmount"));
        return;
      }
      setStep3Error("");
      setStep4Errors({});
      setStep(4);
    } else if (step === 4) {
      if (!validateStep4()) return;
      await handleCompleteAdmission();
    }
  };

  // What the resident owes: the room rate for the chosen food plan (the server snapshots it as the contracted
  // rent) and the agreed deposit. Rent paid now may be less (shortfall due on first invoice) or more (e.g.
  // two months' advance: first invoice uses what it needs and the rest stays as held advance).
  const agreedRent = moneyOrZero(overrideRate);
  const agreedDeposit = moneyOrZero(deposit);
  const rentPaidText = rentPaid ?? agreedRent;
  const depositPaidText = depositPaid ?? agreedDeposit;
  const rentPaidAmount = moneyOrZero(rentPaidText);
  const depositPaidAmount = moneyOrZero(depositPaidText);
  const isOverRent = compareMoney(rentPaidAmount, agreedRent) === 1;
  const rentPending = isOverRent ? ZERO : (subtractMoney(agreedRent, rentPaidAmount) ?? ZERO);
  const estimatedAdvanceAfterFirstInvoice = isOverRent ? (subtractMoney(rentPaidAmount, agreedRent) ?? ZERO) : ZERO;
  const depositPending = subtractMoney(agreedDeposit, depositPaidAmount) ?? ZERO;
  const totalPaidNow = addMoney(rentPaidAmount, depositPaidAmount) ?? ZERO;
  const totalPending = addMoney(rentPending, depositPending) ?? ZERO;
  const paidSomething = compareMoney(totalPaidNow, ZERO) === 1;

  const validateStep4 = () => {
    const errs: { rent?: string; deposit?: string; date?: string } = {};
    if (rentPaidText.trim() !== "" && !isMoneyInput(rentPaidText.trim())) {
      errs.rent = t("step4.errInvalidAmount");
    }
    if (depositPaidText.trim() !== "" && !isMoneyInput(depositPaidText.trim())) {
      errs.deposit = t("step4.errInvalidAmount");
    } else if (compareMoney(moneyOrZero(depositPaidText), agreedDeposit) === 1) {
      errs.deposit = t("step4.errDepositExceeds");
    }
    if (paidSomething && (!collectedOn || collectedOn > todayISO())) errs.date = t("step4.errDate");
    setStep4Errors(errs);
    return !errs.rent && !errs.deposit && !errs.date;
  };

  const handlePrevStep = () => {
    if (step === 2) setStep(1);
    else if (step === 3) setStep(2);
    else if (step === 4) setStep(3);
  };

  const handleCompleteAdmission = async () => {
    setIsSubmitting(true);
    try {
      // 1. Split full name into first and last
      const nameParts = personalInfo.name.trim().split(" ");
      const firstName = nameParts[0] || personalInfo.name.trim();
      const lastName = nameParts.slice(1).join(" ") || "";

      // 2. Create Resident record
      const residentObj = await createResident({
        property: selectedPropertyId,
        first_name: firstName,
        last_name: lastName,
        email: personalInfo.email,
        phone: personalInfo.phone,
        emergency_contact_name: personalInfo.emergencyName,
        emergency_contact_phone: personalInfo.emergencyPhone
      });

      // 3. Reserve the resident: the status graph is Inquiry -> Reserved -> Active, and a new
      // resident starts as Inquiry. Creating the admission below performs Reserved -> Active
      // (Check-In), so the wizard must never set "active" itself.
      await updateResidentStatus(residentObj.id, "reserved");

      // 4. Create Admission record (checks the resident in)
      // Rent/advance paid now is applied to the first invoice up to what it needs; any surplus stays held on the
      // admission for later invoices or exit refund, and any shortfall stays due on it. The deposit is its own
      // amount, with the agreed total so the rest can be recorded later. The API needs a date and mode whenever
      // an amount is collected, so they are sent only for amounts actually paid.
      const paidRent = compareMoney(rentPaidAmount, ZERO) === 1;
      const paidDeposit = compareMoney(depositPaidAmount, ZERO) === 1;
      await createAdmission({
        resident: residentObj.id,
        bed: selectedBedId,
        joining_date: todayISO(),
        billing_mode: "monthly",
        expected_stay_duration: leaseTerm,
        food_preference: foodPreference,
        advance_amount: rentPaidAmount,
        ...(paidRent ? { advance_collected_date: collectedOn, advance_mode: paymentMode } : {}),
        security_deposit_agreed: agreedDeposit,
        security_deposit_amount: depositPaidAmount,
        ...(paidDeposit ? { security_deposit_collected_date: collectedOn, security_deposit_mode: paymentMode } : {}),
      });

      setShowSuccess(true);
    } catch (err) {
      console.error("Admission onboarding failed:", err);
      alert(err instanceof ApiError ? err.message : "Failed to complete admission. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (showSuccess) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-6 text-center animate-fade-in">
        <div className="flex size-20 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 border border-emerald-200 shadow-lg">
          <CheckCircle2 className="size-10" />
        </div>
        <h2 className="mt-6 text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">
          {t("controls.successTitle")}
        </h2>
        <p className="mt-2 text-sm text-ink-muted max-w-md">
          {t("controls.successSub")}
        </p>

        <div className="mt-8 flex flex-col sm:flex-row gap-3">
          <button
            onClick={() => router.push("/residents")}
            className="rounded-xl border border-border bg-surface-card px-5 py-3 text-xs font-bold text-ink hover:bg-surface-page transition-colors cursor-pointer shadow-sm"
          >
            {t("controls.goToDirectory")}
          </button>
          <button
            onClick={() => router.push("/residents")}
            className="rounded-xl bg-accent px-5 py-3 text-xs font-bold text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer shadow-md"
          >
            {t("controls.viewProfile")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Wizard Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">
          {t("title")}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          {t("subtitle")}
        </p>
      </div>

      {/* Stepper Progress Bar */}
      <div className="bg-surface-card border border-border rounded-2xl p-4 shadow-sm">
        <div className="grid grid-cols-4 gap-2 text-center text-xs">
          {[
            { num: 1, title: t("steps.step1"), icon: UserCheck },
            { num: 2, title: t("steps.step2"), icon: Home },
            { num: 3, title: t("steps.step3"), icon: Activity },
            { num: 4, title: t("steps.step4"), icon: CreditCard },
          ].map((s) => {
            const isActive = step === s.num;
            const isCompleted = step > s.num;
            const Icon = s.icon;
            return (
              <div
                key={s.num}
                className={`flex flex-col sm:flex-row items-center justify-center gap-2 p-2.5 rounded-xl transition-all ${
                  isActive
                    ? "bg-accent-soft text-accent font-bold border border-accent/20"
                    : isCompleted
                    ? "text-emerald-600 font-semibold"
                    : "text-ink-faint font-medium"
                }`}
              >
                <div
                  className={`size-6 rounded-full flex items-center justify-center text-xs font-bold border ${
                    isActive
                      ? "bg-accent text-ink-inverse border-accent"
                      : isCompleted
                      ? "bg-emerald-100 text-emerald-700 border-emerald-300"
                      : "bg-surface-page text-ink-faint border-border"
                  }`}
                >
                  {isCompleted ? <CheckCircle2 className="size-3.5 text-emerald-700" /> : s.num}
                </div>
                <div className="hidden sm:flex items-center gap-1.5 text-left truncate">
                  <Icon className="size-3.5 shrink-0" />
                  <p className="text-[11px] truncate">{s.title}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Step Contents Container */}
      <div className="bg-surface-card border border-border rounded-2xl p-6 shadow-sm">
        {/* STEP 1: Personal Details */}
        {step === 1 && (
          <div className="space-y-6 animate-fade-in">
            <div className="border-b border-border pb-4">
              <h2 className="text-lg font-bold text-ink">{t("step1.heading")}</h2>
              <p className="text-xs text-ink-muted mt-0.5">
                {t("step1.subheading")}
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">
                  {t("step1.fullName")} <span className="text-status-critical">*</span>
                </label>
                <input
                  type="text"
                  placeholder={t("step1.placeholderName")}
                  value={personalInfo.name}
                  onChange={(e) => setPersonalInfo({ ...personalInfo, name: e.target.value })}
                  className={`w-full rounded-xl border ${
                    errorsStep1.name ? "border-status-critical" : "border-border"
                  } bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent`}
                />
                {errorsStep1.name && <p className="text-[11px] text-status-critical">{errorsStep1.name}</p>}
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">
                  {t("step1.email")} <span className="text-status-critical">*</span>
                </label>
                <input
                  type="email"
                  placeholder={t("step1.placeholderEmail")}
                  value={personalInfo.email}
                  onChange={(e) => setPersonalInfo({ ...personalInfo, email: e.target.value })}
                  className={`w-full rounded-xl border ${
                    errorsStep1.email ? "border-status-critical" : "border-border"
                  } bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent`}
                />
                {errorsStep1.email && <p className="text-[11px] text-status-critical">{errorsStep1.email}</p>}
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">
                  {t("step1.phone")} <span className="text-status-critical">*</span>
                </label>
                <input
                  type="text"
                  placeholder={t("step1.placeholderPhone")}
                  value={personalInfo.phone}
                  onChange={(e) => setPersonalInfo({ ...personalInfo, phone: e.target.value })}
                  className={`w-full rounded-xl border ${
                    errorsStep1.phone ? "border-status-critical" : "border-border"
                  } bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent`}
                />
                {errorsStep1.phone && <p className="text-[11px] text-status-critical">{errorsStep1.phone}</p>}
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">{t("step1.emergencyName")}</label>
                <input
                  type="text"
                  placeholder={t("step1.placeholderEmergencyName")}
                  value={personalInfo.emergencyName}
                  onChange={(e) => setPersonalInfo({ ...personalInfo, emergencyName: e.target.value })}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">{t("step1.emergencyPhone")}</label>
                <input
                  type="text"
                  placeholder={t("step1.placeholderEmergencyPhone")}
                  value={personalInfo.emergencyPhone}
                  onChange={(e) => setPersonalInfo({ ...personalInfo, emergencyPhone: e.target.value })}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
            </div>
          </div>
        )}

        {/* STEP 2: Room & Bed Selector */}
        {step === 2 && (
          <div className="space-y-6 animate-fade-in">
            <div className="border-b border-border pb-4">
              <h2 className="text-lg font-bold text-ink">{t("step2.heading")}</h2>
              <p className="text-xs text-ink-muted mt-0.5">
                {t("step2.subheading")}
              </p>
            </div>

            {/* Dropdowns row */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div className="space-y-1">
                <label className="font-semibold text-ink-muted">{t("step2.propertySelect")}</label>
                <select
                  value={selectedPropertyId}
                  onChange={(e) => setSelectedPropertyId(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                >
                  {properties.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-ink-muted">{t("step2.buildingSelect")}</label>
                <select
                  value={selectedBuildingId}
                  onChange={(e) => setSelectedBuildingId(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  disabled={buildings.length === 0}
                >
                  {buildings.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-ink-muted">{t("step2.floorSelect")}</label>
                <select
                  value={selectedFloorId}
                  onChange={(e) => setSelectedFloorId(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  disabled={floors.length === 0}
                >
                  {floors.map((fl) => (
                    <option key={fl.id} value={fl.id}>
                      {fl.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Layout Matrix */}
            <div className="space-y-3 pt-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">
                {t("step2.availableRooms")}
              </h3>

              {isLoadingLayout ? (
                <div className="flex items-center justify-center gap-2 py-12 text-xs text-ink-muted">
                  <LoaderCircle className="size-5 animate-spin text-accent" />
                  <span>{t("step2.loadingLayout")}</span>
                </div>
              ) : rooms.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {rooms.map((room) => (
                    <div
                      key={room.id}
                      className="border border-border rounded-xl p-4 bg-surface-page/40 space-y-3"
                    >
                      <div className="flex justify-between items-center text-xs">
                        <span className="font-bold text-ink">{t("step2.roomNumber", { number: room.room_number })}</span>
                        <span className="text-[10px] font-bold text-accent uppercase tracking-wider bg-accent-soft px-2 py-0.5 rounded-full">
                          {t("step2.roomSharing", { type: room.sharing_type })}
                        </span>
                      </div>

                      {/* Beds list */}
                      <div className="grid grid-cols-2 gap-2">
                        {room.beds?.map((bed) => {
                          const isSelected = selectedBedId === bed.id;
                          const isOccupied = bed.status === "occupied";
                          const isMaintenance = bed.status === "maintenance";

                          return (
                            <button
                              key={bed.id}
                              disabled={isOccupied || isMaintenance}
                              onClick={() => handleSelectBed(room, bed)}
                              className={`flex items-center justify-between p-2.5 rounded-lg text-xs font-semibold border transition-all cursor-pointer ${
                                isSelected
                                  ? "bg-accent text-ink-inverse border-accent shadow-md scale-[1.02]"
                                  : isOccupied
                                  ? "bg-surface-subtle text-ink-faint border-border/50 cursor-not-allowed opacity-60"
                                  : isMaintenance
                                  ? "bg-amber-50 text-amber-700 border-amber-200 cursor-not-allowed opacity-60"
                                  : "bg-surface-card text-ink border-border hover:border-accent hover:text-accent"
                              }`}
                            >
                              <div className="flex items-center gap-1.5">
                                {isSelected ? (
                                  <SelectedIcon className="size-3.5 text-ink-inverse" />
                                ) : (
                                  <UnselectedIcon className="size-3.5 text-ink-faint" />
                                )}
                                <span>{t("step2.bedNumber", { number: bed.bed_number })}</span>
                              </div>
                              <span className="text-[10px] font-mono opacity-80">
                                {isOccupied ? t("step2.bedOccupied") : isMaintenance ? t("step2.bedMaintenance") : t("step2.bedAvailable")}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 border border-dashed border-border rounded-xl text-center text-xs text-ink-muted">
                  {t("step2.noRooms")}
                </div>
              )}
            </div>

            {/* Selected bed summary badge */}
            {selectedBedObj && selectedRoomObj && (
              <div className="p-3.5 rounded-xl bg-accent-soft border border-accent/20 flex items-center justify-between text-xs text-accent font-semibold">
                <span>
                  {t("step2.selectedSlotDetail", { room: selectedRoomObj.room_number, bed: selectedBedObj.bed_number })}
                </span>
                <span className="font-mono font-bold">
                  {t("step2.slotRate", { amount: foodPreference === "with_food" ? selectedRoomObj.rack_rate_with_food : selectedRoomObj.rack_rate_without_food })}
                </span>
              </div>
            )}
          </div>
        )}

        {/* STEP 3: Lease & Contract Rates */}
        {step === 3 && (
          <div className="space-y-6 animate-fade-in">
            <div className="border-b border-border pb-4">
              <h2 className="text-lg font-bold text-ink">{t("step3.heading")}</h2>
              <p className="text-xs text-ink-muted mt-0.5">
                {t("step3.subheading")}
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">{t("step3.leaseDuration")}</label>
                <select
                  value={leaseTerm}
                  onChange={(e) => setLeaseTerm(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent"
                >
                  <option value="3_months">{t("step3.term3")}</option>
                  <option value="6_months">{t("step3.term6")}</option>
                  <option value="12_months">{t("step3.term12")}</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">{t("step3.foodPlan")}</label>
                <select
                  value={foodPreference}
                  onChange={(e) => setFoodPreference(e.target.value as "with_food" | "without_food")}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent"
                >
                  <option value="with_food">{t("step3.withFood")}</option>
                  <option value="without_food">{t("step3.withoutFood")}</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">{t("step3.agreedRent")}</label>
                {/* Read-only: the contracted rent is the room's rate for the chosen food plan, snapshotted
                    by the server at admission (invariant 2). Discounts are set separately (Module 07). */}
                <input
                  type="text"
                  value={overrideRate}
                  readOnly
                  aria-readonly="true"
                  className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2.5 font-mono text-ink-muted outline-none"
                />
                <p className="text-[11px] text-ink-faint">{t("step3.agreedRentHint")}</p>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-muted">{t("step3.securityDeposit")}</label>
                <input
                  type="number"
                  min="0"
                  value={deposit}
                  onChange={(e) => setDeposit(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 font-mono text-ink outline-none focus:ring-2 focus:ring-accent"
                />
                {step3Error && <p className="text-[11px] text-status-critical">{step3Error}</p>}
              </div>
            </div>
          </div>
        )}

        {/* STEP 4: Initial Dues Collection */}
        {step === 4 && (
          <div className="space-y-6 animate-fade-in">
            <div className="border-b border-border pb-4">
              <h2 className="text-lg font-bold text-ink">{t("step4.heading")}</h2>
              <p className="text-xs text-ink-muted mt-0.5">
                {t("step4.subheading")}
              </p>
            </div>

            {/* What is owed vs what is received now. Residents often pay part on joining; the rest of the rent
                stays due on the first invoice and the rest of the deposit is recorded later. */}
            <div className="bg-surface-page/60 border border-border rounded-2xl p-5 space-y-5 text-xs">
              <h3 className="font-bold text-ink uppercase tracking-wider text-[11px]">
                {t("step4.summaryTitle")}
              </h3>

              {(
                [
                  { key: "rent", label: t("step4.advanceRent"), agreed: agreedRent, value: rentPaidText, set: setRentPaid, pending: rentPending, error: step4Errors.rent },
                  { key: "deposit", label: t("step4.depositHolding"), agreed: agreedDeposit, value: depositPaidText, set: setDepositPaid, pending: depositPending, error: step4Errors.deposit },
                ] as const
              ).map((row) => (
                <div key={row.key} className="space-y-2 border-b border-border/50 pb-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-semibold text-ink">{row.label}</span>
                    <span className="text-ink-muted">
                      {t("step4.agreed")} <span className="font-mono font-semibold text-ink">{formatMoney(row.agreed)}</span>
                    </span>
                  </div>
                  <div className="flex items-end gap-3">
                    <div className="flex-1 space-y-1">
                      <label htmlFor={`paid-now-${row.key}`} className="font-semibold text-ink-muted">
                        {t("step4.paidNow")}
                      </label>
                      <input
                        id={`paid-now-${row.key}`}
                        type="text"
                        inputMode="decimal"
                        value={row.value}
                        onChange={(e) => row.set(e.target.value)}
                        className={`w-full rounded-xl border ${
                          row.error ? "border-status-critical" : "border-border"
                        } bg-surface-card px-3.5 py-2.5 font-mono text-ink outline-none focus:ring-2 focus:ring-accent`}
                      />
                    </div>
                    <div className="pb-2.5 text-right">
                      <p className="text-ink-muted">{t("step4.pending")}</p>
                      <p className="font-mono font-semibold text-ink">{formatMoney(row.pending)}</p>
                    </div>
                  </div>
                  {row.error && <p className="text-[11px] text-status-critical">{row.error}</p>}
                </div>
              ))}

              <div className="space-y-1.5 pt-1 font-bold text-sm text-ink">
                <div className="flex justify-between items-center">
                  <span>{t("step4.totalPaidNow")}</span>
                  <span className="font-mono text-accent text-base">{formatMoney(totalPaidNow)}</span>
                </div>
                <div className="flex justify-between items-center text-xs font-semibold text-ink-muted">
                  <span>{t("step4.totalPending")}</span>
                  <span className="font-mono">{formatMoney(totalPending)}</span>
                </div>
              </div>
              {compareMoney(estimatedAdvanceAfterFirstInvoice, ZERO) === 1 && (
                <div
                  role="note"
                  className="rounded-xl border border-accent/25 bg-accent-soft/40 p-3.5 space-y-1 text-xs"
                >
                  <div className="flex justify-between items-center gap-3 font-semibold text-ink">
                    <span>{t("step4.estimatedAdvanceLabel")}</span>
                    <span className="font-mono text-accent">{formatMoney(estimatedAdvanceAfterFirstInvoice)}</span>
                  </div>
                  <p className="text-[11px] text-ink-muted leading-relaxed">{t("step4.estimatedAdvanceNote")}</p>
                </div>
              )}
              <p className="text-[11px] text-ink-faint">{t("step4.pendingNote")}</p>
            </div>

            {/* Payment mode and date: only meaningful when something is received now */}
            {paidSomething && (
              <div className="space-y-4 text-xs">
                <div className="space-y-2">
                  <label className="font-semibold text-ink-muted">{t("step4.paymentMethod")}</label>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { id: "upi", label: t("step4.modeUpi"), icon: Activity },
                      { id: "cash", label: t("step4.modeCash"), icon: Landmark },
                      { id: "bank_transfer", label: t("step4.modeBank"), icon: CreditCard },
                    ].map((mode) => {
                      const isSelected = paymentMode === mode.id;
                      const Icon = mode.icon;
                      return (
                        <button
                          key={mode.id}
                          type="button"
                          onClick={() => setPaymentMode(mode.id as DepositMode)}
                          className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center gap-1.5 transition-all cursor-pointer ${
                            isSelected
                              ? "bg-accent text-ink-inverse border-accent shadow-md"
                              : "bg-surface-card text-ink border-border hover:bg-surface-page"
                          }`}
                        >
                          <Icon className="size-4" />
                          <span className="font-bold text-[11px]">{mode.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="space-y-1">
                  <label htmlFor="collected-on" className="font-semibold text-ink-muted">
                    {t("step4.paymentDate")}
                  </label>
                  <input
                    id="collected-on"
                    type="date"
                    value={collectedOn}
                    max={todayISO()}
                    onChange={(e) => setCollectedOn(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                  {step4Errors.date && <p className="text-[11px] text-status-critical">{step4Errors.date}</p>}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Wizard Action Footer Controls */}
        <div className="flex justify-between items-center pt-6 border-t border-border mt-6">
          {step > 1 ? (
            <button
              type="button"
              onClick={handlePrevStep}
              disabled={isSubmitting}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-surface-page px-4 py-2.5 text-xs font-bold text-ink-muted hover:bg-surface-card transition-colors cursor-pointer disabled:opacity-50"
            >
              <ArrowLeft className="size-3.5" />
              {t("controls.back")}
            </button>
          ) : (
            <div />
          )}

          <button
            type="button"
            onClick={handleNextStep}
            disabled={isSubmitting}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer shadow-md disabled:opacity-50"
          >
            {isSubmitting ? (
              <>
                <LoaderCircle className="size-4 animate-spin" />
                <span>{t("controls.processing")}</span>
              </>
            ) : step === 4 ? (
              <span>{t("controls.complete")}</span>
            ) : (
              <>
                <span>{t("controls.next")}</span>
                <ArrowRight className="size-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
