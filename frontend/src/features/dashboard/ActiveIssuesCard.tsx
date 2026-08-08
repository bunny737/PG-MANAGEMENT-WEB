import Link from "next/link";
import { TriangleAlert } from "lucide-react";
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
    <section className="flex h-full flex-col justify-between rounded-2xl border border-border bg-surface-card p-5.5 shadow-xs transition-all hover:border-border-strong hover:shadow-md">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 font-display text-base font-bold text-ink">
            <span className="flex size-8.5 items-center justify-center rounded-xl bg-status-warn-soft text-status-warn ring-1 ring-status-warn/15">
              <TriangleAlert className="size-4.5" aria-hidden />
            </span>
            Active Issues
          </h2>
          {highPriorityCount > 0 ? (
            <StatusPill tone="critical" dot label={`${highPriorityCount} High Priority`} />
          ) : (
            <span className="text-xs text-ink-faint">All clear</span>
          )}
        </div>

        {issues.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border/80 text-[0.6875rem] font-semibold tracking-[0.06em] text-ink-faint uppercase">
                  <th className="pb-2.5 font-semibold">Unit</th>
                  <th className="pb-2.5 font-semibold">Issue</th>
                  <th className="pb-2.5 text-right font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {issues.map((issue) => (
                  <tr
                    key={issue.id}
                    className="transition-colors hover:bg-surface-subtle/80"
                  >
                    <td className="py-3 pr-3 align-top whitespace-nowrap">
                      <span className="inline-flex items-center rounded-md bg-surface-subtle px-2 py-1 text-xs font-semibold text-ink ring-1 ring-border/80">
                        {issue.unit}
                      </span>
                    </td>
                    <td className="py-3 pr-3 align-top text-xs leading-relaxed text-ink-muted">
                      {issue.issue}
                    </td>
                    <td className="py-3 text-right align-top">
                      <StatusPill
                        tone={issue.status === "open" ? "critical" : "accent"}
                        label={STATUS_LABEL[issue.status]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-xl bg-surface-subtle px-4 py-8 text-center text-sm text-ink-muted">
            No active issues right now.
          </div>
        )}
      </div>

      <div className="mt-5 pt-3 border-t border-border/60">
        <Link
          href="/complaints"
          className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-subtle/50 py-2 text-xs font-semibold text-ink-muted transition-all hover:border-border-strong hover:bg-surface-subtle hover:text-ink"
        >
          View All Complaints →
        </Link>
      </div>
    </section>
  );
}
