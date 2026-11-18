/* eslint-disable i18next/no-literal-string -- UI primitive default labels */
"use client";

import { useEffect, useRef, useState, useId } from "react";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface DatePickerProps {
  /** Value in ISO format (YYYY-MM-DD) or empty string. */
  value?: string;
  /** Callback returning ISO format (YYYY-MM-DD) or empty string. */
  onChange?: (value: string) => void;
  /** Placeholder text, defaults to "DD-MM-YYYY". */
  placeholder?: string;
  disabled?: boolean;
  min?: string; // YYYY-MM-DD
  max?: string; // YYYY-MM-DD
  id?: string;
  name?: string;
  className?: string;
  error?: boolean;
  required?: boolean;
  autoFocus?: boolean;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

const DAYS_OF_WEEK = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function parseIsoDate(iso?: string): { year: number; month: number; day: number } | null {
  if (!iso || typeof iso !== "string") return null;
  const parts = iso.trim().split("-");
  if (parts.length !== 3) return null;
  const year = parseInt(parts[0], 10);
  const month = parseInt(parts[1], 10);
  const day = parseInt(parts[2], 10);
  if (isNaN(year) || isNaN(month) || isNaN(day)) return null;
  return { year, month, day };
}

function parseDisplayDate(display: string): { year: number; month: number; day: number } | null {
  if (!display || typeof display !== "string") return null;
  const parts = display.trim().split("-");
  if (parts.length !== 3) return null;
  const day = parseInt(parts[0], 10);
  const month = parseInt(parts[1], 10);
  const year = parseInt(parts[2], 10);
  if (isNaN(year) || isNaN(month) || isNaN(day)) return null;
  return { year, month, day };
}

function formatToDisplay(iso?: string): string {
  const parsed = parseIsoDate(iso);
  if (!parsed) return "";
  const dd = String(parsed.day).padStart(2, "0");
  const mm = String(parsed.month).padStart(2, "0");
  const yyyy = String(parsed.year);
  return `${dd}-${mm}-${yyyy}`;
}

function formatToIso(day: number, month: number, year: number): string {
  const dd = String(day).padStart(2, "0");
  const mm = String(month).padStart(2, "0");
  const yyyy = String(year);
  return `${yyyy}-${mm}-${dd}`;
}

function isValidCalendarDate(day: number, month: number, year: number): boolean {
  if (month < 1 || month > 12) return false;
  if (year < 1900 || year > 2100) return false;
  const maxDays = new Date(year, month, 0).getDate();
  return day >= 1 && day <= maxDays;
}

function autoFormatInput(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}-${digits.slice(2)}`;
  return `${digits.slice(0, 2)}-${digits.slice(2, 4)}-${digits.slice(4)}`;
}

export function DatePicker({
  value = "",
  onChange,
  placeholder = "DD-MM-YYYY",
  disabled = false,
  min,
  max,
  id,
  name,
  className,
  error = false,
  required = false,
  autoFocus = false,
}: DatePickerProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [isOpen, setIsOpen] = useState(false);
  const [userInput, setUserInput] = useState<string | null>(null);

  // Calendar view state (month: 0-11, year: full year)
  const today = new Date();
  const todayYear = today.getFullYear();
  const todayMonth = today.getMonth(); // 0-11
  const todayDay = today.getDate();
  const todayIso = formatToIso(todayDay, todayMonth + 1, todayYear);

  const initialParsed = parseIsoDate(value);
  const [viewYear, setViewYear] = useState<number>(initialParsed?.year ?? todayYear);
  const [viewMonth, setViewMonth] = useState<number>(initialParsed ? initialParsed.month - 1 : todayMonth);

  // Derive current display value without redundant setState in effects
  const displayValue = userInput !== null ? userInput : formatToDisplay(value);

  // Click outside and escape key handling
  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  function syncCalendarViewToValue() {
    const parsed = parseIsoDate(value);
    if (parsed) {
      setViewYear(parsed.year);
      setViewMonth(parsed.month - 1);
    } else {
      setViewYear(todayYear);
      setViewMonth(todayMonth);
    }
  }

  function handleInputClick() {
    if (!disabled) {
      syncCalendarViewToValue();
      setIsOpen(true);
    }
  }

  function handleToggleCalendar() {
    if (disabled) return;
    if (!isOpen) {
      syncCalendarViewToValue();
      setIsOpen(true);
    } else {
      setIsOpen(false);
    }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    // Allow deleting smoothly
    if (raw.length < displayValue.length) {
      setUserInput(raw);
      if (!raw) {
        onChange?.("");
      }
      return;
    }

    const formatted = autoFormatInput(raw);
    setUserInput(formatted);

    if (formatted.length === 10) {
      const parsed = parseDisplayDate(formatted);
      if (parsed && isValidCalendarDate(parsed.day, parsed.month, parsed.year)) {
        const iso = formatToIso(parsed.day, parsed.month, parsed.year);
        if ((!min || iso >= min) && (!max || iso <= max)) {
          onChange?.(iso);
          setViewYear(parsed.year);
          setViewMonth(parsed.month - 1);
        }
      }
    }
  }

  function handleBlur() {
    if (displayValue && displayValue.length === 10) {
      const parsed = parseDisplayDate(displayValue);
      if (parsed && isValidCalendarDate(parsed.day, parsed.month, parsed.year)) {
        const iso = formatToIso(parsed.day, parsed.month, parsed.year);
        if ((!min || iso >= min) && (!max || iso <= max)) {
          onChange?.(iso);
          setUserInput(null);
          return;
        }
      }
    }
    // Revert to valid value if incomplete or invalid
    setUserInput(null);
  }

  function handlePrevMonth() {
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear((prev) => prev - 1);
    } else {
      setViewMonth((prev) => prev - 1);
    }
  }

  function handleNextMonth() {
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear((prev) => prev + 1);
    } else {
      setViewMonth((prev) => prev + 1);
    }
  }

  function handleSelectDate(day: number) {
    const iso = formatToIso(day, viewMonth + 1, viewYear);
    if (min && iso < min) return;
    if (max && iso > max) return;
    setUserInput(null);
    onChange?.(iso);
    setIsOpen(false);
  }

  function handleSelectToday() {
    if (min && todayIso < min) return;
    if (max && todayIso > max) return;
    setViewYear(todayYear);
    setViewMonth(todayMonth);
    setUserInput(null);
    onChange?.(todayIso);
    setIsOpen(false);
  }

  function handleClear() {
    setUserInput(null);
    onChange?.("");
    setIsOpen(false);
  }

  // Generate grid days for the month
  const firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay(); // 0 is Sunday
  const daysInCurrentMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const daysInPrevMonth = new Date(viewYear, viewMonth, 0).getDate();

  // Selected date parsed
  const selectedParsed = parseIsoDate(value);
  const isSelectedDateInView =
    selectedParsed &&
    selectedParsed.year === viewYear &&
    selectedParsed.month === viewMonth + 1;

  // Year options for dropdown (current year - 15 to current year + 15)
  const currentBaseYear = todayYear;
  const yearOptions: number[] = [];
  for (let y = currentBaseYear - 15; y <= currentBaseYear + 15; y++) {
    yearOptions.push(y);
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="relative flex items-center">
        <input
          ref={inputRef}
          type="text"
          id={inputId}
          name={name}
          disabled={disabled}
          required={required}
          autoFocus={autoFocus}
          value={displayValue}
          placeholder={placeholder}
          onChange={handleInputChange}
          onBlur={handleBlur}
          onClick={handleInputClick}
          className={cn(
            "w-full rounded-xl border bg-surface-card px-3 py-2 pr-10 text-sm text-ink outline-none transition-colors",
            "focus:border-accent focus:ring-4 focus:ring-accent/15",
            error
              ? "border-status-critical focus:border-status-critical focus:ring-status-critical/15"
              : "border-border",
            disabled && "cursor-not-allowed bg-surface-page text-ink-muted opacity-70",
            className
          )}
        />
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          onClick={handleToggleCalendar}
          className="absolute right-2.5 flex h-7 w-7 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink disabled:opacity-50 cursor-pointer"
          aria-label="Toggle calendar"
        >
          <CalendarIcon className="h-4 w-4" />
        </button>
      </div>

      {isOpen && (
        <div
          role="dialog"
          aria-label="Calendar date picker"
          className="absolute left-0 top-full z-[60] mt-1.5 w-72 rounded-2xl border border-border bg-surface-card p-3.5 shadow-2xl animate-fade-in"
        >
          {/* Calendar Header with Navigation and Month/Year Dropdowns */}
          <div className="mb-3 flex items-center justify-between gap-1">
            <button
              type="button"
              onClick={handlePrevMonth}
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-border text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink cursor-pointer"
              aria-label="Previous month"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>

            <div className="flex items-center gap-1.5">
              <select
                value={viewMonth}
                onChange={(e) => setViewMonth(parseInt(e.target.value, 10))}
                className="rounded-lg border border-border bg-surface-card px-1.5 py-1 text-xs font-semibold text-ink outline-none cursor-pointer hover:bg-surface-subtle"
              >
                {MONTH_NAMES.map((name, idx) => (
                  <option key={name} value={idx}>
                    {name}
                  </option>
                ))}
              </select>

              <select
                value={viewYear}
                onChange={(e) => setViewYear(parseInt(e.target.value, 10))}
                className="rounded-lg border border-border bg-surface-card px-1.5 py-1 text-xs font-semibold text-ink outline-none cursor-pointer hover:bg-surface-subtle"
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              onClick={handleNextMonth}
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-border text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink cursor-pointer"
              aria-label="Next month"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* Weekday Labels */}
          <div className="mb-1 grid grid-cols-7 text-center">
            {DAYS_OF_WEEK.map((day) => (
              <span key={day} className="text-[11px] font-semibold text-ink-muted py-0.5">
                {day}
              </span>
            ))}
          </div>

          {/* Days Grid */}
          <div className="grid grid-cols-7 gap-1">
            {/* Trailing days from previous month */}
            {Array.from({ length: firstDayOfWeek }).map((_, i) => {
              const dayNum = daysInPrevMonth - firstDayOfWeek + i + 1;
              return (
                <div
                  key={`prev-${i}`}
                  className="flex h-8 w-8 items-center justify-center text-xs text-ink-muted/35 select-none"
                >
                  {dayNum}
                </div>
              );
            })}

            {/* Current month days */}
            {Array.from({ length: daysInCurrentMonth }).map((_, i) => {
              const day = i + 1;
              const iso = formatToIso(day, viewMonth + 1, viewYear);
              const isSelected = isSelectedDateInView && selectedParsed?.day === day;
              const isToday =
                viewYear === todayYear &&
                viewMonth === todayMonth &&
                day === todayDay;

              const isOutOfMin = min ? iso < min : false;
              const isOutOfMax = max ? iso > max : false;
              const isDateDisabled = isOutOfMin || isOutOfMax;

              return (
                <button
                  key={day}
                  type="button"
                  disabled={isDateDisabled}
                  onClick={() => handleSelectDate(day)}
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-lg text-xs transition-all cursor-pointer",
                    isSelected
                      ? "bg-accent font-semibold text-ink-inverse shadow-sm hover:bg-accent-hover"
                      : isToday
                      ? "border border-accent text-accent font-semibold hover:bg-surface-subtle"
                      : "text-ink hover:bg-surface-subtle font-medium",
                    isDateDisabled && "opacity-25 cursor-not-allowed hover:bg-transparent"
                  )}
                >
                  {day}
                </button>
              );
            })}
          </div>

          {/* Footer Quick Actions */}
          <div className="mt-3 flex items-center justify-between border-t border-border pt-2 text-xs">
            <button
              type="button"
              onClick={handleClear}
              className="text-ink-muted transition-colors hover:text-status-critical cursor-pointer"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={handleSelectToday}
              className="font-medium text-accent transition-colors hover:text-accent-hover cursor-pointer"
            >
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
