import { BottomNav } from "@/components/shared/BottomNav";

export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen pb-20">
      {children}
      <BottomNav />
    </div>
  );
}
