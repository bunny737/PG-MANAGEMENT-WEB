"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  getStaffModuleAccess,
  saveStaffModuleAccess,
  type ModuleLevel,
  type StaffModuleAccess,
} from "@/lib/api";

export type AccessStatus = "loading" | "ready" | "notfound" | "error";

type Levels = Record<string, ModuleLevel>;

const levelsOf = (access: StaffModuleAccess): Levels =>
  Object.fromEntries(access.modules.map((m) => [m.key, m.level]));

const defaultsOf = (access: StaffModuleAccess): Levels =>
  Object.fromEntries(access.modules.map((m) => [m.key, m.default_level]));

const sameLevels = (a: Levels, b: Levels) =>
  Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => a[k] === b[k]);

/**
 * State for one staff member's module access. The server is the source of truth:
 *
 * - every change is applied optimistically, then saved as a complete replacement;
 * - saves are serialized through one worker and coalesced, so rapid toggling sends the
 *   latest full map after the in-flight request instead of racing several PUTs;
 * - a failed save rolls the screen back to the last server-confirmed state;
 * - `409 ROLE_CHANGED` (the staff member's role changed while this screen was open)
 *   reloads from the server and raises a notice.
 */
export function useModuleAccess(staffId: string) {
  const [status, setStatus] = useState<AccessStatus>("loading");
  const [access, setAccess] = useState<StaffModuleAccess | null>(null);
  const [levels, setLevels] = useState<Levels>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [roleChanged, setRoleChanged] = useState(false);

  const confirmedRef = useRef<StaffModuleAccess | null>(null);
  const desiredRef = useRef<Levels>({});
  const workerRunning = useRef(false);
  // Last non-off level per module, so switching a module back on restores what it was.
  const lastOnRef = useRef<Levels>({});
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const adopt = useCallback((next: StaffModuleAccess) => {
    confirmedRef.current = next;
    desiredRef.current = levelsOf(next);
    for (const m of next.modules) {
      if (m.level !== "off") lastOnRef.current[m.key] = m.level;
    }
    if (!aliveRef.current) return;
    setAccess(next);
    setLevels(desiredRef.current);
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      adopt(await getStaffModuleAccess(staffId));
      if (aliveRef.current) setStatus("ready");
    } catch (err) {
      if (!aliveRef.current) return;
      setStatus(err instanceof ApiError && (err.status === 404 || err.status === 403) ? "notfound" : "error");
    }
  }, [staffId, adopt]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch for this staff member
    void load();
  }, [load]);

  const drain = useCallback(async () => {
    if (workerRunning.current) return;
    workerRunning.current = true;
    setSaving(true);
    try {
      while (confirmedRef.current && !sameLevels(desiredRef.current, levelsOf(confirmedRef.current))) {
        const confirmed = confirmedRef.current;
        const sent = { ...desiredRef.current };
        const saved = await saveStaffModuleAccess(staffId, confirmed.role, sent);
        confirmedRef.current = saved;
        if (aliveRef.current) setAccess(saved);
      }
      if (aliveRef.current) setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.body.code === "ROLE_CHANGED") {
        if (aliveRef.current) setRoleChanged(true);
        await load();
      } else if (confirmedRef.current) {
        // Roll the screen back to what the server last confirmed.
        desiredRef.current = levelsOf(confirmedRef.current);
        if (aliveRef.current) {
          setLevels(desiredRef.current);
          setError(err instanceof ApiError ? err.message : "save_failed");
        }
      }
    } finally {
      workerRunning.current = false;
      if (aliveRef.current) setSaving(false);
    }
  }, [staffId, load]);

  const setLevel = useCallback(
    (moduleKey: string, level: ModuleLevel) => {
      if (!confirmedRef.current) return;
      const entry = confirmedRef.current.modules.find((m) => m.key === moduleKey);
      if (!entry || !entry.levels.includes(level)) return;
      if (level !== "off") lastOnRef.current[moduleKey] = level;
      desiredRef.current = { ...desiredRef.current, [moduleKey]: level };
      setLevels(desiredRef.current);
      setError(null);
      setRoleChanged(false);
      void drain();
    },
    [drain]
  );

  const toggle = useCallback(
    (moduleKey: string) => {
      const confirmed = confirmedRef.current;
      const entry = confirmed?.modules.find((m) => m.key === moduleKey);
      if (!entry) return;
      if (desiredRef.current[moduleKey] !== "off") {
        setLevel(moduleKey, "off");
        return;
      }
      const remembered = lastOnRef.current[moduleKey];
      const target: ModuleLevel =
        (remembered && entry.levels.includes(remembered) ? remembered : undefined) ??
        (entry.default_level !== "off" ? entry.default_level : undefined) ??
        entry.levels[entry.levels.length - 1];
      setLevel(moduleKey, target);
    },
    [setLevel]
  );

  /** Back to the role's defaults (the server stores that as "not customized"). */
  const resetToDefaults = useCallback(() => {
    if (!confirmedRef.current) return;
    desiredRef.current = defaultsOf(confirmedRef.current);
    setLevels(desiredRef.current);
    setError(null);
    void drain();
  }, [drain]);

  return {
    status,
    access,
    levels,
    saving,
    error,
    roleChanged,
    dismissRoleChanged: () => setRoleChanged(false),
    setLevel,
    toggle,
    resetToDefaults,
    reload: load,
  };
}
