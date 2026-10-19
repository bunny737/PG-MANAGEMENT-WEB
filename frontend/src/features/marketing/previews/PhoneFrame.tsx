import { cn } from "@/lib/utils";

interface PhoneFrameProps {
  /** Which role this screen belongs to ("Resident view"). */
  role: string;
  title: string;
  /** "Concept preview" tag, so a mock-up is never mistaken for a screenshot. */
  previewLabel: string;
  /** Where the experience actually exists today. */
  availability: string;
  children: React.ReactNode;
  className?: string;
}

/** Device frame for the illustrative app screens. The screen itself is
 * decorative (aria-hidden); the caption below carries the information. */
export function PhoneFrame({ role, title, previewLabel, availability, children, className }: PhoneFrameProps) {
  return (
    <figure className={cn("mx-auto w-full max-w-[15rem]", className)}>
      <div className="rounded-[2.25rem] border-[7px] border-surface-inverse bg-surface-inverse shadow-lg">
        <div
          aria-hidden="true"
          className="flex h-[27rem] flex-col overflow-hidden rounded-[1.7rem] bg-surface-page"
        >
          <div className="flex items-center justify-between bg-surface-card px-4 pb-2 pt-3">
            <span className="h-1.5 w-12 rounded-full bg-border-strong" />
            <span className="h-1.5 w-4 rounded-full bg-border-strong" />
          </div>
          <div className="flex-1 space-y-3 overflow-hidden p-3.5">{children}</div>
        </div>
      </div>
      <figcaption className="mt-3 space-y-1 text-center">
        <p className="text-sm font-bold text-ink">
          {role} <span className="font-normal text-ink-muted">· {title}</span>
        </p>
        <p className="inline-block rounded-full bg-accent-soft px-2.5 py-0.5 text-[11px] font-semibold text-accent">
          {previewLabel}
        </p>
        <p className="text-xs text-ink-muted">{availability}</p>
      </figcaption>
    </figure>
  );
}
