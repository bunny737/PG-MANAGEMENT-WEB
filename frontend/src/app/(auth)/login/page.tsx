import { LoginForm } from "@/features/auth/LoginForm";
import { RedirectIfSignedIn } from "@/features/auth/RedirectIfSignedIn";
import { VisualPromo } from "@/features/auth/VisualPromo";
import { getSiteConfig } from "@/lib/site-config";

export default function LoginPage() {
  // Read on the server: SIGNUP_ENABLED only decides whether the "Start free trial" link shows.
  const { signupEnabled } = getSiteConfig();
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <RedirectIfSignedIn />
      <LoginForm signupEnabled={signupEnabled} />
      <VisualPromo />
    </main>
  );
}
