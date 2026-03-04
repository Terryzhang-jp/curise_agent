"use client";

import { useState } from "react";
import type { UploadValidationData } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, CheckCircle2, RefreshCw, AlertTriangle, Plus, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatPill } from "./StatPill";

interface UploadValidationCardProps {
  data: UploadValidationData;
  onQuickAction?: (text: string) => void;
}

export function UploadValidationCard({ data, onQuickAction }: UploadValidationCardProps) {
  const [quarantineOpen, setQuarantineOpen] = useState(data.quarantined.length <= 5);
  const { stats, total, confidence, quarantined, missing_supplier, missing_country } = data;

  const confTotal = confidence.high + confidence.mid + confidence.low + confidence.new;

  return (
    <div className="max-w-[90%] rounded-xl border border-border/50 bg-card overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 bg-primary/5 border-b border-border/30">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">验证结果</span>
          <span className="text-xs text-muted-foreground">批次 #{data.batch_id} &middot; {total} 行</span>
        </div>
        {(data.supplier.name || data.country.name) && (
          <div className="text-[10px] text-muted-foreground mt-1">
            {data.supplier.name && <span>供应商: {data.supplier.name}</span>}
            {data.supplier.name && data.country.name && <span className="mx-1.5">&middot;</span>}
            {data.country.name && <span>国家: {data.country.name}</span>}
          </div>
        )}
      </div>

      {/* Stat pills */}
      <div className="px-4 py-3 flex flex-wrap gap-2">
        <StatPill label="新增" count={stats.new} color="blue" icon={<Plus className="h-3 w-3" />} />
        <StatPill label="更新" count={stats.update} color="green" icon={<ArrowUpDown className="h-3 w-3" />} />
        <StatPill label="无变化" count={stats.no_change} color="gray" icon={<RefreshCw className="h-3 w-3" />} />
        <StatPill label="异常" count={stats.anomaly} color="red" icon={<AlertTriangle className="h-3 w-3" />} />
      </div>

      {/* Confidence bar */}
      {confTotal > 0 && (
        <div className="px-4 pb-3">
          <div className="text-[10px] text-muted-foreground mb-1">置信度分布</div>
          <div className="flex h-2 rounded-full overflow-hidden bg-muted/50">
            {confidence.high > 0 && (
              <div className="bg-emerald-500" style={{ width: `${(confidence.high / confTotal) * 100}%` }} title={`高 ≥90%: ${confidence.high}`} />
            )}
            {confidence.mid > 0 && (
              <div className="bg-amber-400" style={{ width: `${(confidence.mid / confTotal) * 100}%` }} title={`中 70-89%: ${confidence.mid}`} />
            )}
            {confidence.low > 0 && (
              <div className="bg-red-400" style={{ width: `${(confidence.low / confTotal) * 100}%` }} title={`低 <70%: ${confidence.low}`} />
            )}
            {confidence.new > 0 && (
              <div className="bg-slate-300 dark:bg-slate-600" style={{ width: `${(confidence.new / confTotal) * 100}%` }} title={`新增: ${confidence.new}`} />
            )}
          </div>
          <div className="flex gap-3 mt-1 text-[9px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500" />高 {confidence.high}</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400" />中 {confidence.mid}</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-400" />低 {confidence.low}</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-300 dark:bg-slate-600" />新 {confidence.new}</span>
          </div>
        </div>
      )}

      {/* Quarantined items */}
      {quarantined.length > 0 && (
        <div className="px-4 pb-3">
          <Collapsible open={quarantineOpen} onOpenChange={setQuarantineOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[10px] text-amber-600 dark:text-amber-400 hover:underline">
                <AlertTriangle className="h-3 w-3" />
                <span className="font-medium">需确认项 ({quarantined.length})</span>
                <ChevronDown className={cn("h-3 w-3 transition-transform", quarantineOpen && "rotate-180")} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-1.5 rounded-lg border border-border/30 overflow-hidden">
                <div className="max-h-[200px] overflow-auto">
                  <table className="w-full text-[10px]">
                    <thead className="sticky top-0 bg-muted/80">
                      <tr>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">行</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">产品名</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">匹配名</th>
                        <th className="px-2 py-1 text-right font-medium text-muted-foreground">置信度</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quarantined.map((q) => (
                        <tr key={q.row} className="border-t border-border/20">
                          <td className="px-2 py-1 text-muted-foreground">{q.row}</td>
                          <td className="px-2 py-1 truncate max-w-[120px]">{q.name}</td>
                          <td className="px-2 py-1 truncate max-w-[120px] text-muted-foreground">{q.db_name || "-"}</td>
                          <td className="px-2 py-1 text-right">
                            <span className={cn(
                              "font-mono",
                              q.confidence >= 0.7 ? "text-amber-500" : "text-red-500"
                            )}>
                              {(q.confidence * 100).toFixed(0)}%
                            </span>
                          </td>
                          <td className="px-2 py-1">
                            <span className={cn(
                              "px-1.5 py-0.5 rounded text-[9px] font-medium",
                              q.action === "anomaly" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" : "bg-muted text-muted-foreground"
                            )}>
                              {q.action}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      )}

      {/* Quick actions */}
      {onQuickAction && (
        <div className="px-4 py-2.5 border-t border-border/30 bg-muted/20 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[11px]"
            onClick={() => onQuickAction("请预览变更")}
          >
            预览变更
          </Button>
          {(missing_supplier || missing_country) && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-[11px]"
              onClick={() => onQuickAction("请创建缺失的供应商和国家")}
            >
              创建引用
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

