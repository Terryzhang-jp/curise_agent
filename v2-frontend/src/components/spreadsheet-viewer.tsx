"use client";

import { useState, useCallback } from "react";
import { Loader2, Maximize2, Minimize2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SheetData {
  name: string;
  headers: string[];
  rows: (string | number | null)[][];
  merges: { s: { r: number; c: number }; e: { r: number; c: number } }[];
}

interface SpreadsheetViewerProps {
  filename: string;
  fetchFile: () => Promise<ArrayBuffer>;
}

export function SpreadsheetViewer({ filename, fetchFile }: SpreadsheetViewerProps) {
  const [sheets, setSheets] = useState<SheetData[] | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const loadData = useCallback(async () => {
    if (sheets || loading) return; // Already loaded or in progress
    setLoading(true);
    setError(null);
    try {
      const buffer = await fetchFile();
      const XLSX = await import("xlsx");
      const wb = XLSX.read(buffer, { type: "array" });

      const parsed: SheetData[] = wb.SheetNames.map((name) => {
        const ws = wb.Sheets[name];
        const json = XLSX.utils.sheet_to_json<(string | number | null)[]>(ws, {
          header: 1,
          defval: null,
        });

        // Extract merges
        const merges = (ws["!merges"] || []).map((m) => ({
          s: { r: m.s.r, c: m.s.c },
          e: { r: m.e.r, c: m.e.c },
        }));

        // First row as headers, rest as data (or empty)
        const headers = json.length > 0
          ? (json[0] as (string | number | null)[]).map((h) => String(h ?? ""))
          : [];
        const rows = json.slice(1);

        return { name, headers, rows, merges };
      });

      setSheets(parsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "解析失败");
    } finally {
      setLoading(false);
    }
  }, [fetchFile, sheets, loading]);

  const sheet = sheets?.[activeSheet];

  // Inline preview (compact)
  const renderTable = (maxRows: number, compact: boolean) => {
    if (!sheet) return null;

    // Build merge map: for each cell, if it's part of a merge, record span info
    const mergeMap = new Map<string, { rowSpan: number; colSpan: number; hidden: boolean }>();
    for (const m of sheet.merges) {
      for (let r = m.s.r; r <= m.e.r; r++) {
        for (let c = m.s.c; c <= m.e.c; c++) {
          if (r === m.s.r && c === m.s.c) {
            mergeMap.set(`${r}:${c}`, {
              rowSpan: m.e.r - m.s.r + 1,
              colSpan: m.e.c - m.s.c + 1,
              hidden: false,
            });
          } else {
            mergeMap.set(`${r}:${c}`, { rowSpan: 1, colSpan: 1, hidden: true });
          }
        }
      }
    }

    // Combine headers as row 0 with data rows for unified merge handling
    const allRows = [sheet.headers.map((h) => h as string | number | null), ...sheet.rows];
    const displayRows = allRows.slice(0, maxRows);
    const truncated = allRows.length > maxRows;

    // Determine max columns
    const maxCols = allRows.slice(0, maxRows).reduce((m, r) => Math.max(m, r.length), 1);

    return (
      <div className="overflow-auto">
        <table className={cn(
          "border-collapse w-full",
          compact ? "text-[10px]" : "text-xs",
        )}>
          <tbody>
            {displayRows.map((row, ri) => (
              <tr key={ri} className={ri === 0 ? "bg-muted/60 font-semibold" : ri % 2 === 0 ? "bg-muted/20" : ""}>
                {/* Row number */}
                <td className="px-1.5 py-0.5 text-muted-foreground/40 text-right border border-border/30 select-none tabular-nums w-8 shrink-0">
                  {ri === 0 ? "#" : ri}
                </td>
                {Array.from({ length: maxCols }, (_, ci) => {
                  const merge = mergeMap.get(`${ri}:${ci}`);
                  if (merge?.hidden) return null;
                  const val = row[ci];
                  const display = val !== null && val !== undefined ? String(val) : "";
                  return (
                    <td
                      key={ci}
                      rowSpan={merge?.rowSpan}
                      colSpan={merge?.colSpan}
                      className={cn(
                        "px-1.5 py-0.5 border border-border/30 max-w-[200px] truncate",
                        typeof val === "number" && "text-right tabular-nums",
                      )}
                      title={display}
                    >
                      {display}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {truncated && (
          <p className="text-[10px] text-muted-foreground/50 text-center py-1">
            ... {allRows.length - maxRows} 行已省略
          </p>
        )}
      </div>
    );
  };

  // Inline compact preview
  if (!expanded) {
    return (
      <div className="mt-2 w-full">
        {!sheets && !loading && !error && (
          <button
            onClick={loadData}
            className="text-[11px] text-emerald-600 hover:text-emerald-700 hover:underline transition-colors"
          >
            预览内容
          </button>
        )}
        {loading && (
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            加载中...
          </div>
        )}
        {error && (
          <p className="text-[11px] text-destructive">{error}</p>
        )}
        {sheets && sheet && (
          <div className="space-y-1.5">
            {/* Sheet tabs (if multiple) */}
            {sheets.length > 1 && (
              <div className="flex gap-1 overflow-x-auto">
                {sheets.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => setActiveSheet(i)}
                    className={cn(
                      "px-2 py-0.5 rounded text-[10px] transition-colors shrink-0",
                      i === activeSheet
                        ? "bg-emerald-600/10 text-emerald-700 font-medium"
                        : "text-muted-foreground hover:bg-muted/50",
                    )}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            )}
            {/* Compact table */}
            <div className="rounded-lg border border-border/40 overflow-hidden max-h-[240px] overflow-y-auto">
              {renderTable(30, true)}
            </div>
            {/* Expand button */}
            <button
              onClick={() => setExpanded(true)}
              className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              <Maximize2 className="h-3 w-3" />
              全屏查看
            </button>
          </div>
        )}
      </div>
    );
  }

  // Full-screen dialog
  return (
    <>
      {/* Keep inline trigger visible */}
      <div className="mt-2">
        <button
          onClick={() => setExpanded(false)}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          <Minimize2 className="h-3 w-3" />
          收起预览
        </button>
      </div>
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="sm:max-w-[90vw] max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              {filename}
              {sheets && sheets.length > 1 && (
                <div className="flex gap-1 ml-4">
                  {sheets.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => setActiveSheet(i)}
                      className={cn(
                        "px-2.5 py-1 rounded text-xs transition-colors",
                        i === activeSheet
                          ? "bg-emerald-600/10 text-emerald-700 font-medium"
                          : "text-muted-foreground hover:bg-muted/50",
                      )}
                    >
                      {s.name}
                    </button>
                  ))}
                </div>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-auto rounded-lg border border-border/40">
            {sheet && renderTable(500, false)}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
