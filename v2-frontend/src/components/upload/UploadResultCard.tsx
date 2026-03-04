"use client";

import { useState } from "react";
import type { UploadResultData } from "@/lib/chat-api";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface UploadResultCardProps {
  data: UploadResultData;
}

export function UploadResultCard({ data }: UploadResultCardProps) {
  const [failOpen, setFailOpen] = useState(false);
  const { status, stats, failures } = data;
  const isComplete = status === "completed";

  return (
    <div className="max-w-[90%] rounded-xl border border-border/50 bg-card overflow-hidden">
      {/* Banner */}
      <div className={cn(
        "px-4 py-2.5 border-b border-border/30",
        isComplete ? "bg-emerald-500/5" : "bg-amber-500/5"
      )}>
        <div className="flex items-center gap-2">
          {isComplete ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <AlertTriangle className="h-4 w-4 text-amber-500" />
          )}
          <span className="text-sm font-medium">
            {isComplete ? "导入完成" : "部分完成"}
          </span>
          <span className="text-xs text-muted-foreground">批次 #{data.batch_id}</span>
        </div>
      </div>

      {/* Stats grid */}
      <div className="px-4 py-3 grid grid-cols-3 gap-2">
        <StatCell label="新增" value={stats.inserted} color="text-blue-600 dark:text-blue-400" />
        <StatCell label="更新" value={stats.updated} color="text-emerald-600 dark:text-emerald-400" />
        <StatCell label="跳过" value={stats.skipped} color="text-muted-foreground" />
        {stats.excluded > 0 && <StatCell label="排除" value={stats.excluded} color="text-muted-foreground" />}
        {stats.failed > 0 && <StatCell label="失败" value={stats.failed} color="text-red-600 dark:text-red-400" />}
      </div>

      {/* Failures */}
      {failures.length > 0 && (
        <div className="px-4 pb-3">
          <Collapsible open={failOpen} onOpenChange={setFailOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[10px] text-red-600 dark:text-red-400 hover:underline">
                <AlertTriangle className="h-3 w-3" />
                <span className="font-medium">失败详情 ({failures.length})</span>
                <ChevronDown className={cn("h-3 w-3 transition-transform", failOpen && "rotate-180")} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-1.5 rounded-lg border border-red-200/50 dark:border-red-800/30 bg-red-50/30 dark:bg-red-900/10 p-2 space-y-1 max-h-[160px] overflow-auto">
                {failures.map((f, i) => (
                  <div key={i} className="text-[10px] text-red-700 dark:text-red-400 font-mono break-words">
                    {f}
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      )}
    </div>
  );
}

function StatCell({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="text-center py-1.5">
      <div className={cn("text-lg font-semibold", color)}>{value}</div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}
