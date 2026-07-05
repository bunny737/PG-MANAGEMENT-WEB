import { LoginForm } from "@/features/auth/LoginForm";
import { VisualPromo } from "@/features/auth/VisualPromo";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen w-full flex-row">
      <LoginForm />
      <VisualPromo />
    </main>
  );
}
