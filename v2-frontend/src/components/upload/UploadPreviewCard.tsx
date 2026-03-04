"use client";

import { useState } from "react";
import type { UploadPreviewData } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, Eye, Plus, ArrowUpDown, AlertTriangle, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatPill } from "./StatPill";

interface UploadPreviewCardProps {
  data: UploadPreviewData;
  onQuickAction?: (text: string) => void;
}

function formatPrice(price: number | null): string {
  if (price === null || price === undefined) return "-";
  return `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPct(pct: number | null): string {
  if (pct === null || pct === undefined) return "";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

export function UploadPreviewCard({ data, onQuickAction }: UploadPreviewCardProps) {
  const [newOpen, setNewOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const { stats, anomalies, new_items, updates } = data;

  const anomalyRows = anomalies.map((a) => a.row).join(",");

  return (
    <div className="max-w-[90%] rounded-xl border border-border/50 bg-card overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 bg-blue-500/5 border-b border-border/30">
        <div className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-blue-500" />
          <span className="text-sm font-medium">变更预览</span>
          <span className="text-xs text-muted-foreground">批次 #{data.batch_id}</span>
        </div>
        {(data.supplier.name || data.country.name) && (
          <div className="text-[10px] text-muted-foreground mt-1">
            {data.supplier.name && <span>供应商: {data.supplier.name}</span>}
            {data.supplier.name && data.country.name && <span className="mx-1.5">&middot;</span>}
            {data.country.name && <span>国家: {data.country.name}</span>}
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="px-4 py-3 flex flex-wrap gap-2">
        <StatPill label="新增" count={stats.new} color="blue" icon={<Plus className="h-3 w-3" />} />
        <StatPill label="更新" count={stats.update} color="green" icon={<ArrowUpDown className="h-3 w-3" />} />
        <StatPill label="异常" count={stats.anomaly} color="red" icon={<AlertTriangle className="h-3 w-3" />} />
        <StatPill label="无变化" count={stats.no_change} color="gray" icon={<Minus className="h-3 w-3" />} />
      </div>

      {/* Anomalies (always show) */}
      {anomalies.length > 0 && (
        <div className="px-4 pb-3">
          <div className="flex items-center gap-1.5 text-[10px] text-red-600 dark:text-red-400 mb-1.5">
            <AlertTriangle className="h-3 w-3" />
            <span className="font-medium">价格异常 ({anomalies.length})</span>
          </div>
          <div className="rounded-lg border border-red-200/50 dark:border-red-800/30 overflow-hidden">
            <table className="w-full text-[10px]">
              <thead className="bg-red-50/50 dark:bg-red-900/10">
                <tr>
                  <th className="px-2 py-1 text-left font-medium text-muted-foreground">行</th>
                  <th className="px-2 py-1 text-left font-medium text-muted-foreground">产品名</th>
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground">原价</th>
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground">新价</th>
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground">变化</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.map((a) => (
                  <tr key={a.row} className="border-t border-red-200/30 dark:border-red-800/20">
                    <td className="px-2 py-1 text-muted-foreground">{a.row}</td>
                    <td className="px-2 py-1 truncate max-w-[140px]">{a.name}</td>
                    <td className="px-2 py-1 text-right text-muted-foreground">{formatPrice(a.old_price)}</td>
                    <td className="px-2 py-1 text-right font-medium">{formatPrice(a.new_price)}</td>
                    <td className="px-2 py-1 text-right">
                      <span className={cn(
                        "font-mono font-medium",
                        (a.change_pct ?? 0) > 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"
                      )}>
                        {formatPct(a.change_pct)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* New items (collapsible) */}
      {new_items.length > 0 && (
        <div className="px-4 pb-3">
          <Collapsible open={newOpen} onOpenChange={setNewOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[10px] text-blue-600 dark:text-blue-400 hover:underline">
                <Plus className="h-3 w-3" />
                <span className="font-medium">新增产品 ({stats.new})</span>
                <ChevronDown className={cn("h-3 w-3 transition-transform", newOpen && "rotate-180")} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-1.5 rounded-lg border border-border/30 overflow-hidden max-h-[160px] overflow-auto">
                <table className="w-full text-[10px]">
                  <thead className="sticky top-0 bg-muted/80">
                    <tr>
                      <th className="px-2 py-1 text-left font-medium text-muted-foreground">行</th>
                      <th className="px-2 py-1 text-left font-medium text-muted-foreground">产品名</th>
                      <th className="px-2 py-1 text-left font-medium text-muted-foreground">代码</th>
                      <th className="px-2 py-1 text-right font-medium text-muted-foreground">价格</th>
                    </tr>
                  </thead>
                  <tbody>
                    {new_items.map((item) => (
                      <tr key={item.row} className="border-t border-border/20">
                        <td className="px-2 py-1 text-muted-foreground">{item.row}</td>
                        <td className="px-2 py-1 truncate max-w-[140px]">{item.name}</td>
                        <td className="px-2 py-1 text-muted-foreground font-mono">{item.code || "-"}</td>
                        <td className="px-2 py-1 text-right">{formatPrice(item.price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      )}

      {/* Updates (collapsible) */}
      {updates.length > 0 && (
        <div className="px-4 pb-3">
          <Collapsible open={updateOpen} onOpenChange={setUpdateOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[10px] text-emerald-600 dark:text-emerald-400 hover:underline">
                <ArrowUpDown className="h-3 w-3" />
                <span className="font-medium">价格更新 ({stats.update})</span>
                <ChevronDown className={cn("h-3 w-3 transition-transform", updateOpen && "rotate-180")} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-1.5 rounded-lg border border-border/30 overflow-hidden max-h-[160px] overflow-auto">
                <table className="w-full text-[10px]">
                  <thead className="sticky top-0 bg-muted/80">
                    <tr>
                      <th className="px-2 py-1 text-left font-medium text-muted-foreground">行</th>
                      <th className="px-2 py-1 text-left font-medium text-muted-foreground">产品名</th>
                      <th className="px-2 py-1 text-right font-medium text-muted-foreground">原价</th>
                      <th className="px-2 py-1 text-right font-medium text-muted-foreground">新价</th>
                      <th className="px-2 py-1 text-right font-medium text-muted-foreground">变化</th>
                    </tr>
                  </thead>
                  <tbody>
                    {updates.map((u) => (
                      <tr key={u.row} className="border-t border-border/20">
                        <td className="px-2 py-1 text-muted-foreground">{u.row}</td>
                        <td className="px-2 py-1 truncate max-w-[120px]">{u.name}</td>
                        <td className="px-2 py-1 text-right text-muted-foreground">{formatPrice(u.old_price)}</td>
                        <td className="px-2 py-1 text-right font-medium">{formatPrice(u.new_price)}</td>
                        <td className="px-2 py-1 text-right font-mono text-[9px]">{formatPct(u.change_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      )}

      {/* Quick actions */}
      {onQuickAction && (
        <div className="px-4 py-2.5 border-t border-border/30 bg-muted/20 flex flex-wrap gap-2">
          <Button
            variant="default"
            size="sm"
            className="h-7 text-[11px]"
            onClick={() => onQuickAction("确认，请执行产品导入")}
          >
            确认执行
          </Button>
          {anomalies.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-[11px] text-red-600 dark:text-red-400 border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-900/20"
              onClick={() => onQuickAction(`请排除行 ${anomalyRows} 后执行`)}
            >
              排除异常行
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

