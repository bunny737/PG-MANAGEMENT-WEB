// Account deletion (backend Module 22). Constants and types only, so lib/api.ts and
// lib/permissions.ts can both use them without importing each other.

/** Where a locked account lands: the only screen it can still use besides sign-out. */
export const DELETION_PENDING_ROUTE = "/account/deletion-pending";

/** 403 codes the API answers with for every route except /auth/me/ (GET) and the deletion
 * endpoint while an account (or, for staff, their whole business) is being deleted. */
export const DELETION_LOCK_CODES: ReadonlySet<string> = new Set([
  "ACCOUNT_DELETION_PENDING",
  "TENANT_DELETION_PENDING",
]);

export type DeletionScope = "user" | "tenant";
/** `failed` means the purge gave up and needs a person; the account stays locked. */
export type DeletionStatus = "pending" | "processing" | "failed";

export interface AccountDeletion {
  scope: DeletionScope;
  status: DeletionStatus;
  /** When the purge may start (ISO, 00:00 IST). */
  scheduled_for: string;
  /** True only for the requester (or the business's Owner) while still pending. */
  can_cancel: boolean;
}

/** How a deletion request can be confirmed right now; the API only lists what works. */
export type DeletionConfirmMethod = "password" | "otp_email" | "otp_phone";
