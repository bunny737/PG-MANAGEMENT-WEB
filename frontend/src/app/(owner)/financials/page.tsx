import { redirect } from "next/navigation";

// /billing replaces this mock-driven page (UX roadmap S2) — see
// docs/frontend-plan.md's route map and Decisions.
export default function FinancialsRedirect() {
  redirect("/billing");
}
