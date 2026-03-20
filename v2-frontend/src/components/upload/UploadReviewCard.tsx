"use client";

import { useState, useMemo } from "react";
import type { UploadReviewData, UploadReviewDiff } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, ClipboardCheck, Plus, ArrowUpDown, Minus, ShieldAlert, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatPill } from "./StatPill";

interface UploadReviewCardProps {
  data: UploadReviewData;
  onQuickAction?: (text: string) => void;
}

const FIELD_LABELS: Record<string, string> = {
  price: "价格",
  unit: "单位",
  pack_size: "规格",
  brand: "品牌",
  currency: "币种",
  country_of_origin: "原产地",
  effective_from: "生效起",
  effective_to: "生效止",
};

function formatDiffValue(field: string, value: string | number | null): string {
  if (value === null || value === undefined) return "-";
  if (field === "price" && typeof value === "number") {
    return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return String(value);
}

function formatPrice(price: number | null): string {
  if (price === null || price === undefined) return "-";
  return `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function DiffsCell({ diffs }: { diffs: UploadReviewDiff[] }) {
  return (
    <div className="space-y-0">
      {diffs.map((diff, i) => {
        const label = FIELD_LABELS[diff.field] || diff.field;
        const isPriceDiff = diff.field === "price" && typeof diff.old === "number" && typeof diff.new === "number" && diff.old > 0;
        let pctStr = "";
        if (isPriceDiff) {
          const pct = ((diff.new as number) - (diff.old as number)) / (diff.old as number) * 100;
          const sign = pct > 0 ? "+" : "";
          pctStr = `${sign}${pct.toFixed(1)}%`;
        }
        return (
          <div key={i} className="flex items-center gap-1.5 text-[10px] py-0.5 whitespace-nowrap">
            <span className="text-muted-foreground">{label}:</span>
            <span className="line-through text-muted-foreground">{formatDiffValue(diff.field, diff.old)}</span>
            <span className="text-muted-foreground">&rarr;</span>
            <span className="font-medium text-emerald-600 dark:text-emerald-400">{formatDiffValue(diff.field, diff.new)}</span>
            {pctStr && (
              <span className={cn(
                "font-mono text-[9px]",
                (diff.new as number) > (diff.old as number) ? "text-red-500" : "text-emerald-500",
              )}>
                {pctStr}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function UploadReviewCard({ data, onQuickAction }: UploadReviewCardProps) {
  const [newOpen, setNewOpen] = useState(data.stats.new > 0 && data.stats.new <= 20);
  const [updateOpen, setUpdateOpen] = useState(data.stats.update > 0 && data.stats.update <= 20);
  const [auditOpen, setAuditOpen] = useState(false);
  const [excludedRows, setExcludedRows] = useState<Set<number>>(new Set());

  const { stats, new_items, updates, audit_findings } = data;

  const hasNew = stats.new > 0;
  const hasUpdate = stats.update > 0;

  const activeNewCount = useMemo(
    () => new_items.filter((item) => !excludedRows.has(item.row)).length,
    [new_items, excludedRows],
  );
  const activeUpdateCount = useMemo(
    () => updates.filter((u) => !excludedRows.has(u.row)).length,
    [updates, excludedRows],
  );
  const activeCount = activeNewCount + activeUpdateCount;

  const toggleExclude = (row: number) => {
    setExcludedRows((prev) => {
      const next = new Set(prev);
      if (next.has(row)) next.delete(row);
      else next.add(row);
      return next;
    });
  };

  const handleExecute = () => {
    if (!onQuickAction) return;
    if (excludedRows.size > 0) {
      const rowList = Array.from(excludedRows).sort((a, b) => a - b).join(",");
      onQuickAction(`请执行产品导入，排除行 ${rowList}`);
    } else {
      onQuickAction("确认，请执行产品导入");
    }
  };

  return (
    <div className="max-w-[90%] rounded-xl border border-border/50 bg-card overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 bg-indigo-500/5 border-b border-border/30">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="h-4 w-4 text-indigo-500" />
          <span className="text-sm font-medium">上传审查</span>
          <span className="text-xs text-muted-foreground">批次 #{data.batch_id}</span>
        </div>
        <div className="text-[10px] text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
          {data.supplier?.name && <span>供应商: {data.supplier.name}</span>}
          {data.country?.name && <span>国家: {data.country.name}</span>}
          {data.port?.name && <span>港口: {data.port.name}</span>}
          {(data.effective_from || data.effective_to) && (
            <span>有效期: {data.effective_from || "?"} ~ {data.effective_to || "?"}</span>
          )}
        </div>
      </div>

      {/* Stat pills */}
      <div className="px-4 py-3 flex flex-wrap gap-2">
        <StatPill label="新增" count={stats.new} color="blue" icon={<Plus className="h-3 w-3" />} />
        <StatPill label="更新" count={stats.update} color="green" icon={<ArrowUpDown className="h-3 w-3" />} />
        <StatPill label="无变化" count={stats.no_change} color="gray" icon={<Minus className="h-3 w-3" />} />
      </div>

      {/* Audit findings (if any) */}
      {audit_findings.length > 0 && (
        <div className="px-4 pb-3 border-t border-border/30 pt-3">
          <Collapsible open={auditOpen} onOpenChange={setAuditOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[10px] text-amber-600 dark:text-amber-400 hover:underline">
                <ShieldAlert className="h-3 w-3" />
                <span className="font-medium">审计发现 ({audit_findings.length})</span>
                <ChevronDown className={cn("h-3 w-3 transition-transform", auditOpen && "rotate-180")} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-1.5 space-y-1">
                {audit_findings.map((af, i) => (
                  <div key={i} className={cn(
                    "text-[10px] px-2 py-1 rounded border-l-2",
                    af.severity === "error" ? "border-l-red-500 bg-red-50/50 dark:bg-red-900/10" :
                    af.severity === "warning" ? "border-l-amber-500 bg-amber-50/50 dark:bg-amber-900/10" :
                    "border-l-blue-500 bg-blue-50/50 dark:bg-blue-900/10",
                  )}>
                    <p className="font-medium">{af.message}</p>
                    {af.suggestion && <p className="text-muted-foreground italic mt-0.5">{af.suggestion}</p>}
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      )}

      {/* Section 1: New items table */}
      {hasNew && (
        <div className="border-t border-border/30">
          <div className="px-4 pt-3 pb-3">
            <Collapsible open={newOpen} onOpenChange={setNewOpen}>
              <CollapsibleTrigger asChild>
                <button className="flex items-center gap-1.5 text-[10px] text-blue-600 dark:text-blue-400 hover:underline">
                  <Plus className="h-3 w-3" />
                  <span className="font-medium">新增产品 ({stats.new})</span>
                  <ChevronDown className={cn("h-3 w-3 transition-transform", newOpen && "rotate-180")} />
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="mt-1.5 rounded-lg border border-border/30 max-h-[250px] overflow-auto">
                  <table className="w-full text-[10px]">
                    <thead className="sticky top-0 bg-muted/80 z-10">
                      <tr>
                        <th className="px-2 py-1 text-center font-medium text-muted-foreground w-8">
                          <input
                            type="checkbox"
                            className="h-3 w-3"
                            checked={new_items.every((item) => !excludedRows.has(item.row))}
                            onChange={(e) => {
                              setExcludedRows((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) {
                                  new_items.forEach((item) => next.delete(item.row));
                                } else {
                                  new_items.forEach((item) => next.add(item.row));
                                }
                                return next;
                              });
                            }}
                          />
                        </th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">行</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">品名</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">代码</th>
                        <th className="px-2 py-1 text-right font-medium text-muted-foreground">价格</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">单位</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">规格</th>
                      </tr>
                    </thead>
                    <tbody>
                      {new_items.map((item) => {
                        const excluded = excludedRows.has(item.row);
                        return (
                          <tr key={item.row} className={cn("border-t border-border/20", excluded && "opacity-40")}>
                            <td className="px-2 py-1 text-center">
                              <input
                                type="checkbox"
                                className="h-3 w-3"
                                checked={!excluded}
                                onChange={() => toggleExclude(item.row)}
                              />
                            </td>
                            <td className="px-2 py-1 text-muted-foreground">{item.row}</td>
                            <td className={cn("px-2 py-1 truncate max-w-[120px]", excluded && "line-through")}>{item.name}</td>
                            <td className="px-2 py-1 text-muted-foreground font-mono">{item.code || "-"}</td>
                            <td className="px-2 py-1 text-right">{formatPrice(item.price)}</td>
                            <td className="px-2 py-1 text-muted-foreground">{item.unit || "-"}</td>
                            <td className="px-2 py-1 text-muted-foreground truncate max-w-[80px]">{item.pack_size || "-"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </div>
      )}

      {/* Section 2: Updates table */}
      {hasUpdate && (
        <div className="border-t border-border/30">
          <div className="px-4 pt-3 pb-3">
            <Collapsible open={updateOpen} onOpenChange={setUpdateOpen}>
              <CollapsibleTrigger asChild>
                <button className="flex items-center gap-1.5 text-[10px] text-emerald-600 dark:text-emerald-400 hover:underline">
                  <ArrowUpDown className="h-3 w-3" />
                  <span className="font-medium">更新产品 ({stats.update})</span>
                  <ChevronDown className={cn("h-3 w-3 transition-transform", updateOpen && "rotate-180")} />
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="mt-1.5 rounded-lg border border-border/30 max-h-[350px] overflow-auto">
                  <table className="w-full text-[10px]">
                    <thead className="sticky top-0 bg-muted/80 z-10">
                      <tr>
                        <th className="px-2 py-1 text-center font-medium text-muted-foreground w-8">
                          <input
                            type="checkbox"
                            className="h-3 w-3"
                            checked={updates.every((u) => !excludedRows.has(u.row))}
                            onChange={(e) => {
                              setExcludedRows((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) {
                                  updates.forEach((u) => next.delete(u.row));
                                } else {
                                  updates.forEach((u) => next.add(u.row));
                                }
                                return next;
                              });
                            }}
                          />
                        </th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">行</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">品名</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">代码</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">变动</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">匹配</th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground">注意</th>
                      </tr>
                    </thead>
                    <tbody>
                      {updates.map((u) => {
                        const excluded = excludedRows.has(u.row);
                        const hasWarning = !!u.warning;
                        return (
                          <tr
                            key={u.row}
                            className={cn(
                              "border-t border-border/20 align-top",
                              excluded && "opacity-40",
                              hasWarning && !excluded && "bg-amber-50/30 dark:bg-amber-900/5",
                            )}
                          >
                            <td className="px-2 py-1.5 text-center">
                              <input
                                type="checkbox"
                                className="h-3 w-3"
                                checked={!excluded}
                                onChange={() => toggleExclude(u.row)}
                              />
                            </td>
                            <td className="px-2 py-1.5 text-muted-foreground">{u.row}</td>
                            <td className="px-2 py-1.5">
                              <div className={cn("truncate max-w-[120px] font-medium", excluded && "line-through")}>{u.name}</div>
                              {u.db_name !== u.name && (
                                <div className="text-[9px] text-muted-foreground truncate max-w-[120px]">DB: {u.db_name}</div>
                              )}
                            </td>
                            <td className="px-2 py-1.5 text-muted-foreground font-mono">{u.code || "-"}</td>
                            <td className="px-2 py-1.5">
                              {!excluded && <DiffsCell diffs={u.diffs} />}
                            </td>
                            <td className="px-2 py-1.5 text-[9px] text-muted-foreground whitespace-nowrap">
                              {u.match_method} {(u.confidence * 100).toFixed(0)}%
                            </td>
                            <td className="px-2 py-1.5">
                              {hasWarning && !excluded && (
                                <span className="inline-flex items-center gap-1 text-[9px] text-amber-600 dark:text-amber-400">
                                  <AlertTriangle className="h-2.5 w-2.5 shrink-0" />
                                  <span>{u.warning}</span>
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </div>
      )}

      {/* Execute button */}
      {onQuickAction && (hasNew || hasUpdate) && (
        <div className="px-4 py-2.5 border-t border-border/30">
          <Button
            variant="default"
            size="sm"
            className="h-7 text-[11px] w-full"
            onClick={handleExecute}
          >
            执行导入 ({activeCount} 条)
          </Button>
        </div>
      )}
    </div>
  );
}
