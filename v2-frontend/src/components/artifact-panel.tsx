"use client";

import { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  FileSpreadsheet, FileText, Download, Loader2, X, RefreshCw,
  File as FileIcon, Coins, Zap, Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { Artifact } from "@/lib/chat-api";
import { listArtifacts, getArtifactDownloadUrl, getFileDownloadUrl } from "@/lib/chat-api";

// ─── Types ───────────────────────────────────────────────────

export interface SessionStats {
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  thinking_tokens: number;
  estimated_cost_usd: number;
  tool_calls: number;
  tool_errors: number;
  llm_calls: number;
}

interface ArtifactPanelProps {
  sessionId: string | null;
  selectedFile?: string | null;
  onSelectFile?: (filename: string) => void;
  onClose: () => void;
}

// ─── File icon helper ────────────────────────────────────────

function getFileIcon(filename: string) {
  if (/\.xlsx?$/i.test(filename)) return <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />;
  if (/\.pdf$/i.test(filename)) return <FileText className="h-3.5 w-3.5 text-red-500" />;
  if (/\.csv$/i.test(filename)) return <FileText className="h-3.5 w-3.5 text-blue-500" />;
  return <FileIcon className="h-3.5 w-3.5 text-muted-foreground" />;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── SpreadsheetPreview (extracted for artifact panel) ───────

interface SheetData {
  name: string;
  headers: string[];
  rows: (string | number | null)[][];
  merges: { s: { r: number; c: number }; e: { r: number; c: number } }[];
}

function SpreadsheetPreview({ sessionId, filename, artifactId }: { sessionId: string; filename: string; artifactId?: string }) {
  const [sheets, setSheets] = useState<SheetData[] | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSheets(null);
    setActiveSheet(0);
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const { fetchWithAuth } = await import("@/lib/fetch-with-auth");
        const url = artifactId
          ? getArtifactDownloadUrl(sessionId, artifactId)
          : getFileDownloadUrl(sessionId, filename);
        const res = await fetchWithAuth(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const buffer = await res.arrayBuffer();
        const XLSX = await import("xlsx");
        const wb = XLSX.read(buffer, { type: "array" });

        if (cancelled) return;

        const parsed: SheetData[] = wb.SheetNames.map((name) => {
          const ws = wb.Sheets[name];
          const json = XLSX.utils.sheet_to_json<(string | number | null)[]>(ws, {
            header: 1,
            defval: null,
          });
          const merges = (ws["!merges"] || []).map((m) => ({
            s: { r: m.s.r, c: m.s.c },
            e: { r: m.e.r, c: m.e.c },
          }));
          const headers = json.length > 0
            ? (json[0] as (string | number | null)[]).map((h) => String(h ?? ""))
            : [];
          const rows = json.slice(1);
          return { name, headers, rows, merges };
        });
        setSheets(parsed);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "解析失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId, filename, artifactId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin mr-2" />
        <span className="text-xs">加载文件...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-40 text-destructive text-xs">
        {error}
      </div>
    );
  }

  if (!sheets) return null;

  const sheet = sheets[activeSheet];
  if (!sheet) return null;

  // Build merge map
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

  const allRows = [sheet.headers.map((h) => h as string | number | null), ...sheet.rows];
  const maxCols = allRows.reduce((m, r) => Math.max(m, r.length), 1);

  return (
    <div className="flex flex-col h-full">
      {/* Sheet tabs */}
      {sheets.length > 1 && (
        <div className="flex gap-1 px-3 py-1.5 border-b border-border/30 overflow-x-auto shrink-0">
          {sheets.map((s, i) => (
            <button
              key={i}
              onClick={() => setActiveSheet(i)}
              className={cn(
                "px-2.5 py-1 rounded text-[11px] transition-colors shrink-0",
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
      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="border-collapse w-full text-[11px]">
          <tbody>
            {allRows.map((row, ri) => (
              <tr key={ri} className={ri === 0 ? "bg-muted/60 font-semibold sticky top-0" : ri % 2 === 0 ? "bg-muted/20" : ""}>
                <td className="px-1.5 py-0.5 text-muted-foreground/40 text-right border border-border/30 select-none tabular-nums w-8 shrink-0 sticky left-0 bg-background">
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
                        "px-1.5 py-0.5 border border-border/30 max-w-[200px] truncate whitespace-nowrap",
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
      </div>
    </div>
  );
}

// ─── Stats Bar ───────────────────────────────────────────────

function StatsBar({ sessionId }: { sessionId: string }) {
  const [stats, setStats] = useState<SessionStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { fetchWithAuth } = await import("@/lib/fetch-with-auth");
        const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
        const res = await fetchWithAuth(`${API_BASE}/api/chat/sessions/${sessionId}/stats`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setStats(data);
      } catch {
        // Silently ignore — stats are non-critical
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  if (!stats) return null;

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 border-t border-border/30 text-[10px] text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <Zap className="h-2.5 w-2.5" />
        {stats.total_tokens.toLocaleString()} tokens
      </span>
      <span className="inline-flex items-center gap-1">
        <Coins className="h-2.5 w-2.5" />
        ${stats.estimated_cost_usd.toFixed(4)}
      </span>
      <span className="inline-flex items-center gap-1">
        <Clock className="h-2.5 w-2.5" />
        {stats.tool_calls} 调用
      </span>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────

export default function ArtifactPanel({
  sessionId,
  selectedFile,
  onSelectFile,
  onClose,
}: ArtifactPanelProps) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeFile, setActiveFile] = useState<string | null>(selectedFile || null);

  // Sync external selection
  useEffect(() => {
    if (selectedFile) setActiveFile(selectedFile);
  }, [selectedFile]);

  const refreshFiles = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const data = await listArtifacts(sessionId);
      setArtifacts(data);
    } catch {
      // Silently ignore
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refreshFiles();
  }, [refreshFiles]);

  // Auto-select first file if none selected
  useEffect(() => {
    if (!activeFile && artifacts.length > 0) {
      setActiveFile(artifacts[0].filename);
    }
  }, [artifacts, activeFile]);

  // Find artifact by filename
  const findArtifact = (filename: string) => artifacts.find((a) => a.filename === filename);

  const handleDownload = async (filename: string) => {
    if (!sessionId) return;
    const artifact = findArtifact(filename);
    try {
      const { fetchWithAuth } = await import("@/lib/fetch-with-auth");
      // Use unified artifact download for order files, workspace download for ws files
      const url = artifact
        ? getArtifactDownloadUrl(sessionId, artifact.id)
        : getFileDownloadUrl(sessionId, filename);
      const res = await fetchWithAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      console.error("Download failed:", err);
    }
  };

  const handleSelect = (filename: string) => {
    setActiveFile(filename);
    onSelectFile?.(filename);
  };

  if (!sessionId) return null;

  const activeArtifact = activeFile ? findArtifact(activeFile) : null;
  const isSpreadsheet = activeFile && /\.xlsx?$/i.test(activeFile);

  return (
    <div className="flex flex-col h-full bg-background border-l border-border/50">
      {/* Header */}
      <div className="flex items-center justify-between px-3 h-10 border-b border-border/30 shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold text-foreground">工作区文件</h3>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={refreshFiles}
            disabled={loading}
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          </Button>
        </div>
        <Button variant="ghost" size="icon" className="h-5 w-5" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>

      {/* File list */}
      <div className="shrink-0 border-b border-border/30">
        <ScrollArea className="max-h-[180px]">
          <div className="p-1.5 space-y-0.5">
            {artifacts.length === 0 && !loading && (
              <p className="text-[11px] text-muted-foreground px-2 py-3 text-center">
                暂无生成文件
              </p>
            )}
            {loading && artifacts.length === 0 && (
              <div className="flex items-center justify-center py-3">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              </div>
            )}
            {artifacts.map((a) => (
              <button
                key={a.id}
                onClick={() => handleSelect(a.filename)}
                className={cn(
                  "flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-left transition-colors group",
                  activeFile === a.filename
                    ? "bg-primary/10 text-foreground"
                    : "hover:bg-muted/50 text-muted-foreground",
                )}
              >
                {getFileIcon(a.filename)}
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-medium truncate">{a.filename}</p>
                  <p className="text-[10px] text-muted-foreground/60">
                    {a.source === "order_inquiry" ? (
                      <>{a.supplier_name || "供应商"} · {a.product_count ?? "?"} 产品</>
                    ) : (
                      formatFileSize(a.size)
                    )}
                  </p>
                </div>
                <span
                  role="button"
                  onClick={(e) => { e.stopPropagation(); handleDownload(a.filename); }}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-muted cursor-pointer"
                  title="下载"
                >
                  <Download className="h-3 w-3" />
                </span>
              </button>
            ))}
          </div>
        </ScrollArea>
      </div>

      {/* Preview area */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeFile ? (
          isSpreadsheet ? (
            <SpreadsheetPreview
              sessionId={sessionId}
              filename={activeFile}
              artifactId={activeArtifact?.id}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
              {getFileIcon(activeFile)}
              <p className="text-xs">{activeFile}</p>
              <Button
                variant="outline"
                size="sm"
                className="text-xs h-7"
                onClick={() => handleDownload(activeFile)}
              >
                <Download className="h-3 w-3 mr-1" />
                下载文件
              </Button>
            </div>
          )
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <p className="text-xs">选择文件查看预览</p>
          </div>
        )}
      </div>

      {/* Stats bar */}
      <StatsBar sessionId={sessionId} />
    </div>
  );
}
