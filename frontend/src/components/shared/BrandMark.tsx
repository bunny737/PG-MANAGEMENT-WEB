import Image from "next/image";
import { cn } from "@/lib/utils";

/** The PGLive app-icon mark (rounded square with the PG house). Decorative: the brand name is
 * always rendered as text beside it. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <Image
      src="/brand/pglive-mark.png"
      alt=""
      width={256}
      height={256}
      priority
      className={cn("size-9 shrink-0", className)}
    />
  );
}
