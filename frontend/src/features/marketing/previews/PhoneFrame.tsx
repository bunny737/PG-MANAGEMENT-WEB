import Image from "next/image";
import { cn } from "@/lib/utils";

interface PhoneFrameProps {
  /** Which role this screen belongs to ("Owner view"). */
  role: string;
  title: string;
  /** Static screenshot path under /public. */
  src: string;
  /** Describes the screenshot for screen readers. */
  alt: string;
  className?: string;
}

/** Device frame around a real screenshot of the PGLive Android app. */
export function PhoneFrame({ role, title, src, alt, className }: PhoneFrameProps) {
  return (
    <figure className={cn("mx-auto w-full max-w-[16rem]", className)}>
      <div className="rounded-[2rem] border-[6px] border-surface-inverse bg-surface-inverse shadow-lg">
        <Image
          src={src}
          alt={alt}
          width={1080}
          height={2400}
          // eslint-disable-next-line i18next/no-literal-string -- image width hint, not UI copy
          sizes="256px"
          className="block h-auto w-full rounded-[1.5rem]"
        />
      </div>
      <figcaption className="mt-3 text-center">
        <p className="text-sm font-bold text-ink">
          {role} <span className="font-normal text-ink-muted">· {title}</span>
        </p>
      </figcaption>
    </figure>
  );
}
