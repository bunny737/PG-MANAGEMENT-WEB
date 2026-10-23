import { ResetPasswordForm } from "@/features/auth/ResetPasswordForm";
import { VisualPromo } from "@/features/auth/VisualPromo";

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <ResetPasswordForm />
      <VisualPromo />
    </main>
  );
}
