"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Building2, DoorOpen, BedDouble } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import {
  ApiError,
  createTransfer,
  getPropertyLayout,
  type LayoutBed,
  type LayoutRoom,
  type Resident,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { queryKeys } from "@/lib/queryKeys";
import { afterTransfer } from "@/lib/refresh";

interface TransferRoomDialogProps {
  resident: Resident;
  onClose: () => void;
  /** Called after the transfer succeeds, before the dialog closes. */
  onTransferred: () => void;
}

interface RoomOption {
  room: LayoutRoom;
  building: string;
  floor: string;
  availableBeds: LayoutBed[];
}

const FIELD =
  "w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15";
const LABEL = "text-xs font-semibold uppercase tracking-wider text-ink-muted";

/** Today as YYYY-MM-DD in the user's local timezone (toISOString would give the UTC date). */
function todayLocal() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Moves a resident to another bed in their own property (Module 06). The
 * backend rejects cross-property moves (bed_property_mismatch), so the
 * destination property is shown but not selectable. */
export function TransferRoomDialog({ resident, onClose, onTransferred }: TransferRoomDialogProps) {
  const t = useTranslations("residents.transfer");
  const propertyId = resident.property;

  const layoutQuery = useQuery({
    queryKey: queryKeys.properties.layout(propertyId),
    queryFn: () => getPropertyLayout(propertyId),
  });

  const [roomId, setRoomId] = useState("");
  const [bedId, setBedId] = useState("");
  const [transferDate, setTransferDate] = useState(todayLocal);
  const [isTemporary, setIsTemporary] = useState(false);
  const [expectedMoveDate, setExpectedMoveDate] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const layout = layoutQuery.data;

  const roomOptions = useMemo<RoomOption[]>(() => {
    if (!layout) return [];
    return layout.buildings.flatMap((building) =>
      building.floors.flatMap((floor) =>
        floor.rooms
          .map((room) => ({
            room,
            building: building.name,
            floor: floor.name,
            availableBeds: room.beds.filter((bed) => bed.availability === "available"),
          }))
          .filter((option) => option.availableBeds.length > 0)
      )
    );
  }, [layout]);

  const multiBuilding = (layout?.buildings.length ?? 0) > 1;
  const selectedOption = roomOptions.find((option) => option.room.id === roomId);
  const selectedBed = selectedOption?.availableBeds.find((bed) => bed.id === bedId);
  const rackRate = selectedBed
    ? resident.food_preference === "without_food"
      ? selectedBed.rack_rate_without_food
      : selectedBed.rack_rate_with_food
    : null;

  const roomLabel = ({ room, building, floor }: RoomOption) =>
    t("roomOption", {
      room: room.room_number,
      place: multiBuilding ? `${building} · ${floor}` : floor,
      sharing: room.sharing_type,
      category: room.category === "ac" ? t("categoryAc") : t("categoryNonAc"),
    });

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!bedId) {
      setError(t("errSelectBed"));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await createTransfer({
        resident: resident.id,
        new_bed: bedId,
        transfer_date: transferDate,
        is_temporary: isTemporary,
        reason: reason.trim() || undefined,
        expected_move_date: isTemporary && expectedMoveDate ? expectedMoveDate : undefined,
        temporary_note: isTemporary && note.trim() ? note.trim() : undefined,
      });
      await afterTransfer({ residentId: resident.id, fromPropertyId: propertyId });
      onTransferred();
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.fieldError("new_bed") ??
            err.fieldError("resident") ??
            err.fieldError("transfer_date") ??
            err.message ??
            t("errFailed")
        );
      } else {
        setError(t("errFailed"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open onClose={onClose} title={t("title")} className="max-w-md">
      {layoutQuery.isLoading ? (
        <SectionSkeleton className="h-56" />
      ) : layoutQuery.isError || !layout ? (
        <SectionError onRetry={() => layoutQuery.refetch()} />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {resident.contracted_rent != null && (
            <p className="text-sm text-ink">{t("currentRent", { amount: formatMoney(resident.contracted_rent) })}</p>
          )}

          <div className="space-y-1.5">
            <span className={LABEL}>{t("destinationProperty")}</span>
            <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-page px-3 py-2 text-sm text-ink">
              <Building2 className="size-4 text-ink-faint" aria-hidden />
              {layout.property.name}
            </div>
            <p className="text-[11px] text-ink-muted">{t("sameProperty")}</p>
          </div>

          {roomOptions.length === 0 ? (
            <p role="status" className="rounded-xl bg-surface-page p-3 text-sm text-ink-muted">
              {t("noRooms")}
            </p>
          ) : (
            <>
              <div className="space-y-1.5">
                <label htmlFor="transfer-room" className={LABEL}>
                  {t("destinationRoom")} *
                </label>
                <div className="relative">
                  <DoorOpen className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
                  <select
                    id="transfer-room"
                    value={roomId}
                    onChange={(event) => {
                      setRoomId(event.target.value);
                      setBedId("");
                    }}
                    className={`${FIELD} ps-9`}
                  >
                    <option value="">{t("selectRoom")}</option>
                    {roomOptions.map((option) => (
                      <option key={option.room.id} value={option.room.id}>
                        {roomLabel(option)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="transfer-bed" className={LABEL}>
                  {t("destinationBed")} *
                </label>
                <div className="relative">
                  <BedDouble className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
                  <select
                    id="transfer-bed"
                    value={bedId}
                    onChange={(event) => setBedId(event.target.value)}
                    disabled={!selectedOption}
                    className={`${FIELD} ps-9 disabled:opacity-60`}
                  >
                    <option value="">{t("selectBed")}</option>
                    {selectedOption?.availableBeds.map((bed) => (
                      <option key={bed.id} value={bed.id}>
                        {t("bedOption", { bed: bed.bed_number })}
                      </option>
                    ))}
                  </select>
                </div>
                {rackRate != null && (
                  <p className="text-xs text-ink-muted">
                    {t(resident.food_preference === "without_food" ? "rackRateWithoutFood" : "rackRateWithFood", {
                      amount: formatMoney(rackRate),
                    })}
                  </p>
                )}
              </div>
            </>
          )}

          <div className="space-y-1.5">
            <label htmlFor="transfer-date" className={LABEL}>
              {t("effectiveDate")}
            </label>
            <input
              id="transfer-date"
              type="date"
              required
              value={transferDate}
              onChange={(event) => setTransferDate(event.target.value)}
              className={FIELD}
            />
          </div>

          <label className="flex items-start gap-2 text-sm text-ink cursor-pointer">
            <input
              type="checkbox"
              checked={isTemporary}
              onChange={(event) => setIsTemporary(event.target.checked)}
              className="mt-0.5 size-4 accent-accent"
            />
            <span>
              {t("temporary")}
              <span className="block text-[11px] text-ink-muted">{t("temporaryHint")}</span>
            </span>
          </label>

          {isTemporary && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="transfer-expected" className={LABEL}>
                  {t("expectedMoveDate")}
                </label>
                <input
                  id="transfer-expected"
                  type="date"
                  min={transferDate}
                  value={expectedMoveDate}
                  onChange={(event) => setExpectedMoveDate(event.target.value)}
                  className={FIELD}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="transfer-note" className={LABEL}>
                  {t("temporaryNote")}
                </label>
                <input
                  id="transfer-note"
                  type="text"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  className={FIELD}
                />
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="transfer-reason" className={LABEL}>
              {t("reason")}
            </label>
            <input
              id="transfer-reason"
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={FIELD}
            />
          </div>

          <p className="rounded-xl bg-surface-page p-3 text-xs italic text-ink-muted">
            {isTemporary ? t("noteTemporary") : t("notePermanent")}
          </p>

          {error && (
            <p role="alert" className="text-sm text-status-critical">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl px-4 py-2.5 text-sm font-semibold text-accent hover:bg-surface-page transition-colors cursor-pointer"
            >
              {t("cancel")}
            </button>
            <button
              type="submit"
              disabled={submitting || !bedId}
              className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer disabled:cursor-not-allowed"
            >
              {submitting ? t("submitting") : t("confirm")}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
