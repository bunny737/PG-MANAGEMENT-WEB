import { cn } from "@/lib/utils";

export function Container({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cn("mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8", className)}>{children}</div>;
}

interface SectionProps {
  id?: string;
  tone?: "default" | "subtle" | "dark";
  className?: string;
  children: React.ReactNode;
}

const TONES = {
  default: "bg-surface-page text-ink",
  subtle: "bg-surface-card text-ink border-y border-border",
  dark: "bg-surface-inverse text-ink-inverse",
};

export function Section({ id, tone = "default", className, children }: SectionProps) {
  return (
    <section id={id} className={cn("py-14 sm:py-20", TONES[tone], className)}>
      <Container>{children}</Container>
    </section>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  alignLeft = false,
  inverse = false,
  pageTitle = false,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  alignLeft?: boolean;
  inverse?: boolean;
  /** Renders the heading as the page's single h1 (otherwise an h2). */
  pageTitle?: boolean;
}) {
  const Heading = pageTitle ? "h1" : "h2";
  return (
    <div className={cn("max-w-2xl", !alignLeft && "mx-auto text-center")}>
      {eyebrow && (
        <p
          className={cn(
            "text-xs font-bold uppercase tracking-widest",
            inverse ? "text-accent-border" : "text-accent"
          )}
        >
          {eyebrow}
        </p>
      )}
      <Heading className="mt-2 text-3xl font-extrabold leading-tight sm:text-4xl">{title}</Heading>
      {subtitle && (
        <p className={cn("mt-4 text-base sm:text-lg", inverse ? "text-ink-inverse-muted" : "text-ink-muted")}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
