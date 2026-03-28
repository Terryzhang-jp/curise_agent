"use client";

import { useState, useEffect, useRef, useCallback, memo } from "react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  ChevronDown, BrainCircuit, Wrench, Terminal, AlertTriangle,
  OctagonX, RotateCw, Loader2, Clock, Sparkles, FileSpreadsheet, Download,
} from "lucide-react";
import type { ChatMessage, GeneratedFileCardData } from "@/lib/chat-api";
import { getFileDownloadUrl } from "@/lib/chat-api";
import { SpreadsheetViewer } from "./spreadsheet-viewer";
import { UploadValidationCard } from "./upload/UploadValidationCard";
import { UploadPreviewCard } from "./upload/UploadPreviewCard";
import { UploadResultCard } from "./upload/UploadResultCard";
import { ConfirmationCard } from "./upload/ConfirmationCard";
import { QueryTableCard } from "./upload/QueryTableCard";
import { DataAuditCard } from "./upload/DataAuditCard";
import { UploadReviewCard } from "./upload/UploadReviewCard";

// ─── Card Registry ──────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const CARD_REGISTRY: Record<string, React.ComponentType<{ data: any; onQuickAction?: (text: string) => void; onOpenArtifact?: (filename: string) => void }>> = {
  upload_validation: UploadValidationCard,
  upload_preview: UploadPreviewCard,
  upload_result: UploadResultCard,
  confirmation: ConfirmationCard,
  query_table: QueryTableCard,
  data_audit: DataAuditCard,
  upload_review: UploadReviewCard,
  generated_file: GeneratedFileBubble,
};

const LEGACY_TOOL_TO_CARD: Record<string, string> = {
  resolve_and_validate: "upload_validation",
  preview_changes: "upload_preview",
  execute_upload: "upload_result",
};

function resolveCardType(data: Record<string, unknown>): string | undefined {
  if (data.card_type) return data.card_type as string;
  return LEGACY_TOOL_TO_CARD[data.tool as string] ?? undefined;
}

// ─── Utilities ──────────────────────────────────────────────

interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  truncated?: boolean;
}

function tryParseQueryResult(content: string): QueryResult | null {
  try {
    const parsed = JSON.parse(content);
    if (parsed && Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) {
      return parsed as QueryResult;
    }
  } catch {
    // not JSON
  }
  return null;
}

function formatTime(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function getToolDisplayName(content: string, metadata?: Record<string, unknown>): string {
  if (metadata?.summary) return metadata.summary as string;
  const match = content.match(/^调用\s+(\S+)/);
  if (match) return match[1];
  return content;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ─── ChatBubble (main dispatcher) ───────────────────────────

interface ChatBubbleProps {
  role: "user" | "assistant" | "tool";
  content: string;
  msgType?: string;
  createdAt: string;
  streaming?: boolean;
  metadata?: Record<string, unknown>;
  onRetry?: (toolName: string) => void;
  onQuickAction?: (text: string) => void;
  onOpenArtifact?: (filename: string) => void;
}

export const ChatBubble = memo(function ChatBubble({
  role, content, msgType, createdAt, streaming, metadata, onRetry, onQuickAction, onOpenArtifact,
}: ChatBubbleProps) {
  const type = msgType || "text";

  if (role === "user") {
    return (
      <div className="flex justify-end animate-in fade-in-0 slide-in-from-bottom-1 duration-200">
        <div className="max-w-[75%] rounded-2xl rounded-br-md px-4 py-2.5 bg-primary/10 text-sm">
          <div className="whitespace-pre-wrap break-words">{content}</div>
          <div className="text-[10px] text-muted-foreground/50 mt-1.5 text-right select-none">
            {formatTime(createdAt)}
          </div>
        </div>
      </div>
    );
  }

  if (type === "thinking") return <ThinkingBubble content={content} />;
  if (type === "action") return <ToolCallPill content={content} metadata={metadata} />;
  if (type === "error_observation") return <ErrorObservationBubble content={content} metadata={metadata} onRetry={onRetry} />;
  if (type === "error") return <SystemErrorBubble content={content} />;
  if (type === "observation" || role === "tool") return <ObservationBubble content={content} metadata={metadata} onQuickAction={onQuickAction} onOpenArtifact={onOpenArtifact} />;

  // Assistant final answer
  return (
    <div className="flex justify-start animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
      <div className="max-w-[80%] rounded-2xl rounded-bl-md px-4 py-3 bg-card border border-border/40 text-sm shadow-sm">
        {streaming ? (
          <div className="whitespace-pre-wrap break-words">
            {content}
            <span className="inline-block w-0.5 h-[1.1em] bg-primary/70 ml-0.5 animate-pulse align-text-bottom rounded-full" />
          </div>
        ) : (
          <>
            <MarkdownContent content={content} />
            <div className="text-[10px] text-muted-foreground/40 mt-2 select-none">
              {formatTime(createdAt)}
            </div>
          </>
        )}
      </div>
    </div>
  );
});

// ─── ThinkingBubble ─────────────────────────────────────────

function ThinkingBubble({ content }: { content: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex justify-start animate-in fade-in-0 duration-200">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[85%]">
        <CollapsibleTrigger asChild>
          <button className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] transition-all",
            "bg-violet-500/5 border border-violet-500/15 text-violet-500",
            "hover:bg-violet-500/10 hover:border-violet-500/25",
          )}>
            <BrainCircuit className="h-3 w-3 shrink-0" />
            <span className="font-medium">思考过程</span>
            <ChevronDown className={cn("h-3 w-3 transition-transform duration-200", open && "rotate-180")} />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-1.5 px-3 py-2.5 rounded-lg bg-violet-500/[0.03] border border-violet-500/10 text-xs text-muted-foreground/80 italic leading-relaxed whitespace-pre-wrap break-words">
            {content}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

// ─── ToolCallPill ───────────────────────────────────────────

function ToolCallPill({ content, metadata }: { content: string; metadata?: Record<string, unknown> }) {
  const displayName = getToolDisplayName(content, metadata);
  const duration = metadata?.duration_ms as number | undefined;

  return (
    <div className="flex justify-start animate-in fade-in-0 duration-150">
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-muted/40 border border-border/40 text-[11px]">
        <Wrench className="h-3 w-3 shrink-0 text-primary/60" />
        <span className="font-medium text-foreground/80">{displayName}</span>
        {duration != null && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground/50 ml-0.5">
            <Clock className="h-2.5 w-2.5" />
            {formatDuration(duration)}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── ObservationBubble ──────────────────────────────────────

function ObservationBubble({
  content, metadata, onQuickAction, onOpenArtifact,
}: {
  content: string;
  metadata?: Record<string, unknown>;
  onQuickAction?: (text: string) => void;
  onOpenArtifact?: (filename: string) => void;
}) {
  const [open, setOpen] = useState(false);

  // 1. Structured card
  const cardData = (metadata?.structured_card || metadata?.upload_data) as Record<string, unknown> | undefined;
  if (cardData) {
    const ct = resolveCardType(cardData);
    const Card = ct ? CARD_REGISTRY[ct] : undefined;
    if (Card) {
      return (
        <div className="flex justify-start animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
          <Card data={cardData} onQuickAction={onQuickAction} onOpenArtifact={onOpenArtifact} />
        </div>
      );
    }
  }

  // 2. Legacy query result
  const queryResult = tryParseQueryResult(content);
  if (queryResult) {
    return (
      <div className="flex justify-start animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
        <QueryTableCard data={{ card_type: "query_table" as const, ...queryResult }} />
      </div>
    );
  }

  // 3. Plain text
  const isLong = content.length > 200;

  return (
    <div className="flex justify-start animate-in fade-in-0 duration-150">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[85%]">
        <CollapsibleTrigger asChild>
          <button className={cn(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] transition-all",
            "bg-muted/30 border border-border/30 text-muted-foreground",
            "hover:bg-muted/50 hover:border-border/50",
          )}>
            <Terminal className="h-3 w-3 shrink-0" />
            <span className="font-medium">工具结果</span>
            {isLong && <ChevronDown className={cn("h-3 w-3 transition-transform duration-200", open && "rotate-180")} />}
          </button>
        </CollapsibleTrigger>
        {isLong ? (
          <CollapsibleContent>
            <div className="mt-1 px-3 py-2 rounded-lg bg-muted/20 border border-border/20 text-[10px] font-mono text-muted-foreground/80 whitespace-pre-wrap break-words max-h-48 overflow-y-auto leading-relaxed">
              {content}
            </div>
          </CollapsibleContent>
        ) : (
          <div className="mt-1 px-3 py-2 rounded-lg bg-muted/20 border border-border/20 text-[10px] font-mono text-muted-foreground/80 whitespace-pre-wrap break-words leading-relaxed">
            {content}
          </div>
        )}
      </Collapsible>
    </div>
  );
}

// ─── ErrorObservationBubble ─────────────────────────────────

function ErrorObservationBubble({
  content, metadata, onRetry,
}: {
  content: string;
  metadata?: Record<string, unknown>;
  onRetry?: (toolName: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const severity = (metadata?.severity as string) || "error";
  const toolName = (metadata?.tool_name as string) || "";
  const technicalDetail = (metadata?.technical_detail as string) || "";
  const recoveryHint = (metadata?.recovery_hint as string) || "";

  const isWarning = severity === "warning";
  const Icon = isWarning ? AlertTriangle : OctagonX;
  const label = isWarning ? "警告" : "操作失败";

  const colors = isWarning
    ? { bg: "bg-amber-500/5", border: "border-amber-500/20", text: "text-amber-600 dark:text-amber-400", hover: "hover:bg-amber-500/10" }
    : { bg: "bg-destructive/5", border: "border-destructive/20", text: "text-destructive", hover: "hover:bg-destructive/10" };

  return (
    <div className="flex justify-start animate-in fade-in-0 duration-200">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[85%]">
        <CollapsibleTrigger asChild>
          <button className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] transition-all border",
            colors.bg, colors.border, colors.text, colors.hover,
          )}>
            <Icon className="h-3 w-3 shrink-0" />
            <span className="font-medium">{label}</span>
            {technicalDetail && (
              <ChevronDown className={cn("h-3 w-3 transition-transform duration-200", open && "rotate-180")} />
            )}
          </button>
        </CollapsibleTrigger>
        <div className={cn("mt-1 px-3 py-2 rounded-lg border text-xs", colors.bg, colors.border)}>
          <p className={cn("font-medium", colors.text)}>{content}</p>
          {open && technicalDetail && (
            <p className="mt-1.5 text-[10px] font-mono text-muted-foreground break-words">{technicalDetail}</p>
          )}
          {recoveryHint && (
            <p className="mt-1.5 text-[10px] italic text-muted-foreground">{recoveryHint}</p>
          )}
          {!isWarning && onRetry && toolName && (
            <Button
              variant="ghost"
              size="sm"
              className={cn("mt-2 h-6 px-2 text-[10px] gap-1", colors.text, colors.hover)}
              onClick={() => onRetry(toolName)}
            >
              <RotateCw className="h-3 w-3" />
              重试
            </Button>
          )}
        </div>
      </Collapsible>
    </div>
  );
}

// ─── GeneratedFileBubble ─────────────────────────────────────

function GeneratedFileBubble({ data, onOpenArtifact }: { data: GeneratedFileCardData; onOpenArtifact?: (filename: string) => void }) {
  const [downloading, setDownloading] = useState(false);
  const isSpreadsheet = /\.xlsx?$/i.test(data.filename);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const { fetchWithAuth } = await import("@/lib/fetch-with-auth");
      const url = getFileDownloadUrl(data.session_id, data.filename);
      const res = await fetchWithAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = data.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      console.error("Download failed:", err);
    } finally {
      setDownloading(false);
    }
  };

  const fetchFile = useCallback(async (): Promise<ArrayBuffer> => {
    const { fetchWithAuth } = await import("@/lib/fetch-with-auth");
    const url = getFileDownloadUrl(data.session_id, data.filename);
    const res = await fetchWithAuth(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.arrayBuffer();
  }, [data.session_id, data.filename]);

  return (
    <div className="max-w-[85%]">
      <div className="inline-flex items-center gap-3 px-4 py-3 rounded-xl bg-emerald-500/5 border border-emerald-500/20 w-full">
        <FileSpreadsheet className="h-5 w-5 text-emerald-600 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{data.filename}</p>
          <p className="text-[11px] text-muted-foreground">Excel 文件已生成</p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {onOpenArtifact && (
            <button
              onClick={() => onOpenArtifact(data.filename)}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-emerald-600/30 text-emerald-700 hover:bg-emerald-500/10 transition-colors"
            >
              查看
            </button>
          )}
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-700 transition-colors disabled:opacity-50"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            下载
          </button>
        </div>
      </div>
      {!onOpenArtifact && isSpreadsheet && (
        <SpreadsheetViewer filename={data.filename} fetchFile={fetchFile} />
      )}
    </div>
  );
}

// ─── SystemErrorBubble ──────────────────────────────────────

function SystemErrorBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start animate-in fade-in-0 duration-200">
      <div className="max-w-[85%] px-3 py-2.5 rounded-lg bg-destructive/5 border border-destructive/20">
        <div className="flex items-center gap-1.5 mb-1">
          <OctagonX className="h-3.5 w-3.5 text-destructive shrink-0" />
          <span className="text-[11px] font-medium text-destructive">系统错误</span>
        </div>
        <p className="text-xs text-destructive/90">{content}</p>
      </div>
    </div>
  );
}

// ─── ReasoningBlock ─────────────────────────────────────────

function getReasoningBlockSummary(messages: ChatMessage[]): string {
  const firstThinking = messages.find((m) => m.msg_type === "thinking");
  if (firstThinking?.metadata?.summary) return firstThinking.metadata.summary as string;

  const firstAction = messages.find((m) => m.msg_type === "action");
  if (firstAction?.metadata?.summary) return firstAction.metadata.summary as string;
  if (firstAction) return firstAction.content;

  return "推理过程";
}

function getActiveLabel(messages: ChatMessage[]): string {
  const lastMsg = messages[messages.length - 1];
  if (!lastMsg) return "思考中";
  if (lastMsg.msg_type === "action") {
    const name = getToolDisplayName(lastMsg.content, lastMsg.metadata);
    return `${name}`;
  }
  if (lastMsg.msg_type === "observation") return "分析结果";
  return "思考中";
}

interface ReasoningBlockProps {
  messages: ChatMessage[];
  isActive: boolean;
  onRetry?: (toolName: string) => void;
  onQuickAction?: (text: string) => void;
  onOpenArtifact?: (filename: string) => void;
}

export const ReasoningBlock = memo(function ReasoningBlock({
  messages, isActive, onRetry, onQuickAction, onOpenArtifact,
}: ReasoningBlockProps) {
  const [open, setOpen] = useState(isActive);
  const wasActiveRef = useRef(isActive);
  const summary = getReasoningBlockSummary(messages);
  const stepCount = messages.length;
  const hasError = messages.some((m) => m.msg_type === "error_observation");
  const activeLabel = getActiveLabel(messages);

  // Auto-expand when active; auto-collapse 600ms after completion (like Claude.ai)
  useEffect(() => {
    if (isActive) {
      setOpen(true);
      wasActiveRef.current = true;
    } else if (wasActiveRef.current) {
      // Just became inactive — auto-collapse after delay
      wasActiveRef.current = false;
      const timer = setTimeout(() => setOpen(false), 600);
      return () => clearTimeout(timer);
    }
  }, [isActive]);

  const triggerStyles = isActive
    ? "thinking-shimmer bg-primary/[0.04] border-primary/20 text-primary"
    : hasError
      ? "bg-amber-500/5 border-amber-500/15 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"
      : "bg-muted/30 border-border/40 text-muted-foreground hover:bg-muted/50 hover:border-border/60";

  return (
    <div className="flex justify-start animate-in fade-in-0 duration-200">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[90%] w-full">
        <CollapsibleTrigger asChild>
          <button className={cn(
            "flex items-center gap-2 w-full px-3 py-2 rounded-xl text-[11px] transition-all border",
            triggerStyles,
          )}>
            {isActive ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
            ) : hasError ? (
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            ) : (
              <Sparkles className="h-3.5 w-3.5 shrink-0" />
            )}
            <span className="font-medium truncate flex-1 text-left">
              {isActive ? (
                <>
                  {activeLabel}
                  <span className="thinking-dots ml-0.5">
                    <span>.</span><span>.</span><span>.</span>
                  </span>
                </>
              ) : summary}
            </span>
            {!isActive && (
              <>
                <span className="text-[10px] opacity-40 shrink-0 tabular-nums">{stepCount}</span>
                <ChevronDown className={cn(
                  "h-3 w-3 shrink-0 transition-transform duration-200",
                  open && "rotate-180",
                )} />
              </>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="reasoning-timeline mt-2 space-y-0.5">
            {messages.map((msg, idx) => (
              <ReasoningStepInline
                key={msg.id}
                msg={msg}
                isLast={idx === messages.length - 1 && isActive}
                onRetry={onRetry}
                onQuickAction={onQuickAction}
                onOpenArtifact={onOpenArtifact}
              />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
});

// ─── ReasoningStepInline ────────────────────────────────────

function ReasoningStepInline({
  msg, isLast, onRetry, onQuickAction, onOpenArtifact,
}: {
  msg: ChatMessage;
  isLast?: boolean;
  onRetry?: (toolName: string) => void;
  onQuickAction?: (text: string) => void;
  onOpenArtifact?: (filename: string) => void;
}) {
  const type = msg.msg_type || "text";

  if (type === "thinking") {
    return (
      <div className="reasoning-step py-2 animate-in fade-in-0 duration-200" data-type="thinking" data-active={isLast}>
        <div className="flex items-start gap-2">
          <BrainCircuit className="h-4 w-4 text-violet-500 shrink-0 mt-0.5" />
          <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
            {msg.content}
          </p>
        </div>
      </div>
    );
  }

  if (type === "action") {
    const displayName = getToolDisplayName(msg.content, msg.metadata);
    const duration = msg.metadata?.duration_ms as number | undefined;
    return (
      <div className="reasoning-step py-1.5 animate-in fade-in-0 duration-200" data-type="action" data-active={isLast}>
        <div className="flex items-center gap-1.5">
          {isLast ? (
            <Loader2 className="h-3 w-3 text-primary/70 animate-spin shrink-0" />
          ) : (
            <Wrench className="h-3 w-3 text-primary/60 shrink-0" />
          )}
          <span className="text-[11px] font-medium text-foreground/70">{displayName}</span>
          {duration != null && (
            <span className="text-[10px] text-muted-foreground/40 tabular-nums">{formatDuration(duration)}</span>
          )}
        </div>
      </div>
    );
  }

  if (type === "error_observation") {
    return (
      <div className="reasoning-step py-1.5 animate-in fade-in-0 duration-200" data-type="error_observation">
        <ErrorObservationBubble content={msg.content} metadata={msg.metadata} onRetry={onRetry} />
      </div>
    );
  }

  if (type === "observation") {
    // Structured card
    const cardData = (msg.metadata?.structured_card || msg.metadata?.upload_data) as Record<string, unknown> | undefined;
    if (cardData) {
      const ct = resolveCardType(cardData);
      const Card = ct ? CARD_REGISTRY[ct] : undefined;
      if (Card) {
        return (
          <div className="reasoning-step py-1.5 animate-in fade-in-0 duration-300" data-type="observation">
            <Card data={cardData} onQuickAction={onQuickAction} onOpenArtifact={onOpenArtifact} />
          </div>
        );
      }
    }

    // Legacy query result
    const queryResult = tryParseQueryResult(msg.content);
    if (queryResult) {
      return (
        <div className="reasoning-step py-1.5 animate-in fade-in-0 duration-300" data-type="observation">
          <QueryTableCard data={{ card_type: "query_table" as const, ...queryResult }} />
        </div>
      );
    }

    // Plain text
    const truncated = msg.content.length > 300 ? msg.content.slice(0, 300) + "..." : msg.content;
    return (
      <div className="reasoning-step py-1.5 animate-in fade-in-0 duration-150" data-type="observation">
        <div className="flex items-start gap-1.5">
          <Terminal className="h-3 w-3 text-emerald-500/50 shrink-0 mt-0.5" />
          <pre className="text-[10px] font-mono text-muted-foreground/60 whitespace-pre-wrap break-words max-h-32 overflow-y-auto leading-relaxed">
            {truncated}
          </pre>
        </div>
      </div>
    );
  }

  return null;
}
