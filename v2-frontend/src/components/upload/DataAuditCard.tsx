"use client";

import { useState } from "react";
import type { DataAuditCardData, DataAuditFinding } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, ShieldCheck, OctagonX, AlertTriangle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatPill } from "./StatPill";

interface DataAuditCardProps {
  data: DataAuditCardData;
  onQuickAction?: (text: string) => void;
}

const SEVERITY_CONFIG = {
  error: {
    icon: OctagonX,
    label: "错误",
    border: "border-l-red-500",
    iconColor: "text-red-500",
    headerColor: "text-red-600 dark:text-red-400",
    bg: "bg-red-50/50 dark:bg-red-900/10",
  },
  warning: {
    icon: AlertTriangle,
    label: "警告",
    border: "border-l-amber-500",
    iconColor: "text-amber-500",
    headerColor: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-50/50 dark:bg-amber-900/10",
  },
  info: {
    icon: Info,
    label: "提示",
    border: "border-l-blue-500",
    iconColor: "text-blue-500",
    headerColor: "text-blue-600 dark:text-blue-400",
    bg: "bg-blue-50/50 dark:bg-blue-900/10",
  },
} as const;

function FindingItem({ finding }: { finding: DataAuditFinding }) {
  const config = SEVERITY_CONFIG[finding.severity];
  const Icon = config.icon;

  return (
    <div className={cn("border-l-2 pl-3 py-1.5", config.border, config.bg, "rounded-r-md")}>
      <div className="flex items-start gap-1.5">
        <Icon className={cn("h-3 w-3 shrink-0 mt-0.5", config.iconColor)} />
        <div className="min-w-0">
          <p className="text-xs font-medium">{finding.message}</p>
          {finding.rows.length > 0 && (
            <p className="text-[10px] text-muted-foreground mt-0.5">
              行: {finding.rows.slice(0, 10).join(", ")}
              {finding.rows.length > 10 && ` ...共 ${finding.rows.length} 行`}
            </p>
          )}
          {finding.suggestion && (
            <p className="text-[10px] text-muted-foreground mt-0.5 italic">
              {finding.suggestion}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function SeverityGroup({ severity, findings }: { severity: "error" | "warning" | "info"; findings: DataAuditFinding[] }) {
  const [open, setOpen] = useState(severity === "error" || findings.length <= 3);
  const config = SEVERITY_CONFIG[severity];
  const Icon = config.icon;

  if (findings.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="flex items-center gap-1.5 text-[10px] hover:underline w-full">
          <Icon className={cn("h-3 w-3", config.iconColor)} />
          <span className={cn("font-medium", config.headerColor)}>{config.label} ({findings.length})</span>
          <ChevronDown className={cn("h-3 w-3 transition-transform ml-auto", open && "rotate-180")} />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1.5 space-y-1.5">
          {findings.map((f, i) => (
            <FindingItem key={`${f.category}-${i}`} finding={f} />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function DataAuditCard({ data, onQuickAction }: DataAuditCardProps) {
  const { stats, findings, total_rows, summary } = data;
  const hasIssues = stats.error > 0 || stats.warning > 0;

  const errorFindings = findings.filter((f) => f.severity === "error");
  const warningFindings = findings.filter((f) => f.severity === "warning");
  const infoFindings = findings.filter((f) => f.severity === "info");

  return (
    <div className="max-w-[90%] rounded-xl border border-border/50 bg-card overflow-hidden">
      {/* Header */}
      <div className={cn(
        "px-4 py-2.5 border-b border-border/30",
        hasIssues ? "bg-amber-500/5" : "bg-emerald-500/5",
      )}>
        <div className="flex items-center gap-2">
          <ShieldCheck className={cn("h-4 w-4", hasIssues ? "text-amber-500" : "text-emerald-500")} />
          <span className="text-sm font-medium">数据质量审计</span>
          <span className="text-xs text-muted-foreground">批次 #{data.batch_id} &middot; {total_rows} 行</span>
        </div>
      </div>

      {/* Stat pills */}
      <div className="px-4 py-3 flex flex-wrap gap-2">
        <StatPill label="错误" count={stats.error} color="red" icon={<OctagonX className="h-3 w-3" />} />
        <StatPill label="警告" count={stats.warning} color="amber" icon={<AlertTriangle className="h-3 w-3" />} />
        <StatPill label="提示" count={stats.info} color="blue" icon={<Info className="h-3 w-3" />} />
      </div>

      {/* Findings by severity */}
      {findings.length > 0 && (
        <div className="px-4 pb-3 space-y-3">
          <SeverityGroup severity="error" findings={errorFindings} />
          <SeverityGroup severity="warning" findings={warningFindings} />
          <SeverityGroup severity="info" findings={infoFindings} />
        </div>
      )}

      {/* Summary */}
      <div className="px-4 py-2 text-[10px] text-muted-foreground border-t border-border/20">
        {summary}
      </div>

      {/* Quick actions */}
      {onQuickAction && (
        <div className="px-4 py-2.5 border-t border-border/30 bg-muted/20 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[11px]"
            onClick={() => onQuickAction("继续预览变更")}
          >
            继续预览变更
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[11px]"
            onClick={() => onQuickAction("重新审计数据")}
          >
            重新审计
          </Button>
        </div>
      )}
    </div>
  );
}
