import { LoginForm } from "@/features/auth/LoginForm";
import { RedirectIfSignedIn } from "@/features/auth/RedirectIfSignedIn";
import { VisualPromo } from "@/features/auth/VisualPromo";

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <RedirectIfSignedIn />
      <LoginForm />
      <VisualPromo />
    </main>
  );
}
