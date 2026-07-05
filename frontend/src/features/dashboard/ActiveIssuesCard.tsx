import Link from "next/link";
import { StatusPill } from "@/components/shared/StatusPill";
import type { ActiveIssue } from "./types";

const STATUS_LABEL: Record<ActiveIssue["status"], string> = {
  open: "Open",
  in_progress: "In Progress",
  resolved: "Resolved",
};

export function ActiveIssuesCard({
  issues,
  highPriorityCount,
}: {
  issues: ActiveIssue[];
  highPriorityCount: number;
}) {
  return (
    <section className="rounded-2xl bg-surface-card p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-bold text-ink">Active Issues</h2>
        {highPriorityCount > 0 ? (
          <StatusPill tone="critical" label={`${highPriorityCount} High Priority`} />
        ) : null}
      </div>

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="text-xs font-medium tracking-wide text-ink-faint uppercase">
            <th className="pb-2 font-medium">Unit</th>
            <th className="pb-2 font-medium">Issue</th>
            <th className="pb-2 text-right font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr key={issue.id} className="border-t border-border">
              <td className="py-2.5 font-medium text-ink">{issue.unit}</td>
              <td className="py-2.5 text-ink-muted">{issue.issue}</td>
              <td className="py-2.5 text-right">
                <StatusPill
                  tone={issue.status === "open" ? "critical" : "neutral"}
                  label={STATUS_LABEL[issue.status]}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <Link
        href="/complaints"
        className="mt-4 flex w-full items-center justify-center rounded-xl border border-border py-2.5 text-sm font-medium text-ink-muted transition-colors hover:bg-surface-page hover:text-ink"
      >
        View All Complaints
      </Link>
    </section>
  );
}
