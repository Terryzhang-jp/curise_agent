"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, Database } from "lucide-react";
import type { QueryTableCardData } from "@/lib/chat-api";

export function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

interface QueryTableCardProps {
  data: QueryTableCardData;
  onQuickAction?: (text: string) => void;
}

export function QueryTableCard({ data }: QueryTableCardProps) {
  const [open, setOpen] = useState(false);
  const { columns, rows, total, truncated } = data;

  if (rows.length === 0) {
    return (
      <div className="max-w-[90%] min-w-[320px]">
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/5 border border-blue-500/15 text-[10px] text-blue-500">
          <Database className="h-3 w-3" />
          <span className="font-medium">查询无结果</span>
        </div>
      </div>
    );
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="max-w-[90%] min-w-[320px]">
      <CollapsibleTrigger asChild>
        <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/5 border border-blue-500/15 text-[10px] text-blue-500 hover:bg-blue-500/10 transition-colors">
          <Database className="h-3 w-3" />
          <span className="font-medium">查询结果 · {total} 条</span>
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
        </button>
      </CollapsibleTrigger>
      <div className="mt-1 rounded-lg border border-border/30 overflow-hidden">
        <div className="max-h-[400px] overflow-auto">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col}
                    className="px-2.5 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap border-b border-border/30"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={i}
                  className={cn(
                    "border-b border-border/20 last:border-b-0",
                    i % 2 === 0 ? "bg-background" : "bg-muted/20"
                  )}
                >
                  {columns.map((col) => (
                    <td key={col} className="px-2.5 py-1.5 whitespace-nowrap text-foreground/80">
                      {formatCellValue(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-2.5 py-1.5 text-[10px] text-muted-foreground bg-muted/40 border-t border-border/30 flex items-center justify-between">
          <span>
            共 {total} 条{truncated ? `（仅显示前 ${rows.length} 条）` : ""}
          </span>
          <span>{rows.length} 行 × {columns.length} 列</span>
        </div>
      </div>
      <CollapsibleContent>
        <div className="mt-1 px-3 py-2 rounded-lg bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
          {JSON.stringify(data, null, 2)}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
