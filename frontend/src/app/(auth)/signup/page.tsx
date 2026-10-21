import { RedirectIfSignedIn } from "@/features/auth/RedirectIfSignedIn";
import { SignupForm } from "@/features/auth/SignupForm";
import { VisualPromo } from "@/features/auth/VisualPromo";

// Reachable whether or not SIGNUP_ENABLED is set: the flag only controls whether the marketing
// site and the login page link here (docs/frontend-plan.md §12).
export default function SignupPage() {
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <RedirectIfSignedIn />
      <SignupForm />
      <VisualPromo />
    </main>
  );
}
