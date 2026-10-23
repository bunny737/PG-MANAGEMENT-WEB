import { DeletionPendingScreen } from "@/features/account-deletion/DeletionPendingScreen";

// Deliberately its own top-level route with no portal layout: a locked account cannot call the
// endpoints that layout's navigation and background queries use.
export default function DeletionPendingPage() {
  return <DeletionPendingScreen />;
}
