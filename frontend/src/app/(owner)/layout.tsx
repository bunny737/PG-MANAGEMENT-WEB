import { BottomNav } from "@/components/shared/BottomNav";
import { SideNav } from "@/components/shared/SideNav";

export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <SideNav />
      <div className="flex-1 pb-20 md:pb-0">{children}</div>
      <BottomNav />
    </div>
  );
}
