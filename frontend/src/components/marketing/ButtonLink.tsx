import Link from "next/link";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "inverse" | "ghost";

interface ButtonLinkProps {
  href: string;
  /** mailto:, tel:, wa.me and other off-site targets render a plain anchor. */
  external?: boolean;
  variant?: Variant;
  size?: "md" | "lg";
  className?: string;
  children: React.ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-ink-inverse shadow-sm hover:bg-accent-hover",
  secondary: "border border-border-strong bg-surface-card text-ink hover:bg-surface-subtle",
  inverse: "bg-surface-card text-ink hover:bg-accent-soft",
  ghost: "text-ink-muted hover:bg-surface-subtle hover:text-ink",
};

const SIZES = {
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
};

export function ButtonLink({
  href,
  external = false,
  variant = "primary",
  size = "md",
  className,
  children,
}: ButtonLinkProps) {
  const classes = cn(
    "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-colors",
    VARIANTS[variant],
    SIZES[size],
    className
  );

  if (external) {
    const isWeb = href.startsWith("http");
    return (
      <a
        href={href}
        className={classes}
        {...(isWeb ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      >
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={classes}>
      {children}
    </Link>
  );
}
