import { DeleteAccountCard } from "@/features/account-deletion/DeleteAccountCard";
import { UserProfile } from "@/features/profile/UserProfile";

export default function UserProfilePage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <UserProfile />
      <div className="mx-auto max-w-4xl">
        <DeleteAccountCard />
      </div>
    </main>
  );
}
