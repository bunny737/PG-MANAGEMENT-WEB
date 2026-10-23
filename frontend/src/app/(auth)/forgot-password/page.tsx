import { ForgotPasswordForm } from "@/features/auth/ForgotPasswordForm";
import { VisualPromo } from "@/features/auth/VisualPromo";

export default function ForgotPasswordPage() {
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <ForgotPasswordForm />
      <VisualPromo />
    </main>
  );
}
