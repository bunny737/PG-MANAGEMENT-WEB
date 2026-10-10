import { StaffDirectory } from "@/features/staff/StaffDirectory";

export const metadata = {
  title: "Staff Management | PropManager",
  description: "Manage staff accounts, assign properties, and control permissions.",
};

export default function StaffPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
      <StaffDirectory />
    </main>
  );
}
