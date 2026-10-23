import { VerifyEmail } from "@/features/auth/VerifyEmail";
import { VisualPromo } from "@/features/auth/VisualPromo";

export default function VerifyEmailPage() {
  return (
    <main className="flex min-h-dvh w-full flex-row">
      <VerifyEmail />
      <VisualPromo />
    </main>
  );
}
