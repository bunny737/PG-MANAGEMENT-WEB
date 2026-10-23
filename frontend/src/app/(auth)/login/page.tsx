import { LoginForm } from "@/features/auth/LoginForm";
import { RedirectIfSignedIn } from "@/features/auth/RedirectIfSignedIn";
import { VisualPromo } from "@/features/auth/VisualPromo";
import { getSiteConfig } from "@/lib/site-config";

const VIEWS = ["owner", "staff"] as const;

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ view?: string | string[] }> }) {
  // Read on the server: SIGNUP_ENABLED only decides whether the "Start free trial" link shows.
  const { signupEnabled } = getSiteConfig();
  // `?view=staff` (the link after a staff invite) skips the role chooser; anything else is ignored.
  const { view } = await searchParams;
  const initialView = VIEWS.find((candidate) => candidate === view);
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <RedirectIfSignedIn />
      <LoginForm signupEnabled={signupEnabled} initialView={initialView} />
      <VisualPromo />
    </main>
  );
}
