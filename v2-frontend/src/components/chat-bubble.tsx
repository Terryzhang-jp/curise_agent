"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, BrainCircuit, Wrench, Terminal, AlertTriangle, OctagonX, RotateCw, Database, Loader2 } from "lucide-react";
import type { ChatMessage } from "@/lib/chat-api";

interface ChatBubbleProps {
  role: "user" | "assistant" | "tool";
  content: string;
  msgType?: string;
  createdAt: string;
  streaming?: boolean;
  metadata?: Record<string, unknown>;
  onRetry?: (toolName: string) => void;
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

export function ChatBubble({ role, content, msgType, createdAt, streaming, metadata, onRetry }: ChatBubbleProps) {
  const type = msgType || "text";

  // User message
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-md px-4 py-2.5 bg-primary/10 text-sm">
          <div className="whitespace-pre-wrap break-words">{content}</div>
          <div className="text-[9px] text-muted-foreground mt-1.5 text-right">{formatTime(createdAt)}</div>
        </div>
      </div>
    );
  }

  // Thinking
  if (type === "thinking") {
    return <ThinkingBubble content={content} />;
  }

  // Action (tool call)
  if (type === "action") {
    return (
      <div className="flex justify-start">
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/5 border border-primary/10 text-primary text-[10px]">
          <Wrench className="h-3 w-3" />
          <span className="font-medium">{content}</span>
        </div>
      </div>
    );
  }

  // Error observation (tool error)
  if (type === "error_observation") {
    return <ErrorObservationBubble content={content} metadata={metadata} onRetry={onRetry} />;
  }

  // System error (agent crash)
  if (type === "error") {
    return <SystemErrorBubble content={content} />;
  }

  // Observation (tool result)
  if (type === "observation" || role === "tool") {
    return <ObservationBubble content={content} />;
  }

  // Assistant text (final answer)
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-md px-4 py-2.5 bg-card border border-border/50 text-sm">
        <MarkdownContent content={content} />
        {streaming && (
          <span className="inline-block w-[2px] h-[1em] bg-primary/70 ml-0.5 animate-pulse align-text-bottom" />
        )}
        {!streaming && (
          <div className="text-[9px] text-muted-foreground mt-1.5">{formatTime(createdAt)}</div>
        )}
      </div>
    </div>
  );
}

function ThinkingBubble({ content }: { content: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex justify-start">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[85%]">
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/5 border border-violet-500/15 text-[10px] text-violet-400 hover:bg-violet-500/10 transition-colors">
            <BrainCircuit className="h-3 w-3" />
            <span className="font-medium">思考过程</span>
            <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-1 px-3 py-2 rounded-lg bg-violet-500/5 border border-violet-500/10 text-xs text-muted-foreground italic whitespace-pre-wrap break-words">
            {content}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

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
    // not JSON — fall through
  }
  return null;
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function QueryResultTable({ data }: { data: QueryResult }) {
  const { columns, rows, total, truncated } = data;

  if (rows.length === 0) {
    return (
      <div className="mt-1 px-3 py-4 rounded-lg bg-muted/30 border border-border/30 text-xs text-muted-foreground text-center">
        查询无结果
      </div>
    );
  }

  return (
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
  );
}

function ObservationBubble({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const queryResult = tryParseQueryResult(content);
  const isLong = content.length > 200;

  if (queryResult) {
    return (
      <div className="flex justify-start">
        <Collapsible open={open} onOpenChange={setOpen} className="max-w-[90%] min-w-[320px]">
          <CollapsibleTrigger asChild>
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/5 border border-blue-500/15 text-[10px] text-blue-500 hover:bg-blue-500/10 transition-colors">
              <Database className="h-3 w-3" />
              <span className="font-medium">查询结果 · {queryResult.total} 条</span>
              <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
            </button>
          </CollapsibleTrigger>
          <QueryResultTable data={queryResult} />
          <CollapsibleContent>
            <div className="mt-1 px-3 py-2 rounded-lg bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
              {content}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[85%]">
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted/50 border border-border/50 text-[10px] text-muted-foreground hover:bg-muted transition-colors">
            <Terminal className="h-3 w-3" />
            <span className="font-medium">工具结果</span>
            {isLong && <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />}
          </button>
        </CollapsibleTrigger>
        {isLong ? (
          <CollapsibleContent>
            <div className="mt-1 px-3 py-2 rounded-lg bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
              {content}
            </div>
          </CollapsibleContent>
        ) : (
          <div className="mt-1 px-3 py-2 rounded-lg bg-muted/30 border border-border/30 text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words">
            {content}
          </div>
        )}
      </Collapsible>
    </div>
  );
}

function ErrorObservationBubble({
  content,
  metadata,
  onRetry,
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

  const bgColor = isWarning ? "bg-amber-500/5" : "bg-destructive/5";
  const borderColor = isWarning ? "border-amber-500/20" : "border-destructive/20";
  const textColor = isWarning ? "text-amber-600 dark:text-amber-400" : "text-destructive";
  const hoverBg = isWarning ? "hover:bg-amber-500/10" : "hover:bg-destructive/10";

  return (
    <div className="flex justify-start">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[85%]">
        <CollapsibleTrigger asChild>
          <button className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] transition-colors",
            bgColor, borderColor, textColor, hoverBg, "border"
          )}>
            <Icon className="h-3 w-3 shrink-0" />
            <span className="font-medium">{label}</span>
            {technicalDetail && <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />}
          </button>
        </CollapsibleTrigger>
        <div className={cn("mt-1 px-3 py-2 rounded-lg border text-xs", bgColor, borderColor)}>
          <p className={cn("font-medium", textColor)}>{content}</p>
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
              className={cn("mt-2 h-6 px-2 text-[10px] gap-1", textColor, hoverBg)}
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

function SystemErrorBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] px-3 py-2.5 rounded-lg bg-destructive/5 border border-destructive/20">
        <div className="flex items-center gap-1.5 mb-1">
          <OctagonX className="h-3.5 w-3.5 text-destructive shrink-0" />
          <span className="text-[10px] font-medium text-destructive">系统错误</span>
        </div>
        <p className="text-xs text-destructive/90">{content}</p>
      </div>
    </div>
  );
}


// ─── Reasoning Block (collapsible group of thinking/action/observation) ──────

function getReasoningBlockSummary(messages: ChatMessage[]): string {
  // 1. First thinking message's metadata.summary
  const firstThinking = messages.find((m) => m.msg_type === "thinking");
  if (firstThinking?.metadata?.summary) return firstThinking.metadata.summary as string;

  // 2. First action message's metadata.summary
  const firstAction = messages.find((m) => m.msg_type === "action");
  if (firstAction?.metadata?.summary) return firstAction.metadata.summary as string;

  // 3. First action's content
  if (firstAction) return firstAction.content;

  // 4. Fallback
  return "推理过程";
}

function ReasoningStepInline({ msg, onRetry }: { msg: ChatMessage; onRetry?: (toolName: string) => void }) {
  const type = msg.msg_type || "text";

  if (type === "thinking") {
    return (
      <div className="flex items-start gap-2 py-1.5">
        <BrainCircuit className="h-3 w-3 text-violet-400 shrink-0 mt-0.5" />
        <p className="text-xs text-muted-foreground italic whitespace-pre-wrap break-words line-clamp-4">
          {msg.content}
        </p>
      </div>
    );
  }

  if (type === "action") {
    const summary = (msg.metadata?.summary as string) || msg.content;
    return (
      <div className="flex items-center gap-2 py-1.5">
        <Wrench className="h-3 w-3 text-primary shrink-0" />
        <span className="text-xs text-primary font-medium">{summary}</span>
      </div>
    );
  }

  if (type === "error_observation") {
    return (
      <div className="py-1.5">
        <ErrorObservationBubble content={msg.content} metadata={msg.metadata} onRetry={onRetry} />
      </div>
    );
  }

  if (type === "observation") {
    const queryResult = tryParseQueryResult(msg.content);
    if (queryResult) {
      return (
        <div className="py-1.5">
          <div className="flex items-center gap-1.5 text-[10px] text-blue-500 mb-1">
            <Database className="h-3 w-3" />
            <span className="font-medium">查询结果 · {queryResult.total} 条</span>
          </div>
          <QueryResultTable data={queryResult} />
        </div>
      );
    }
    const truncated = msg.content.length > 300 ? msg.content.slice(0, 300) + "..." : msg.content;
    return (
      <div className="flex items-start gap-2 py-1.5">
        <Terminal className="h-3 w-3 text-muted-foreground shrink-0 mt-0.5" />
        <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
          {truncated}
        </pre>
      </div>
    );
  }

  return null;
}

interface ReasoningBlockProps {
  messages: ChatMessage[];
  isActive: boolean;
  onRetry?: (toolName: string) => void;
}

export function ReasoningBlock({ messages, isActive, onRetry }: ReasoningBlockProps) {
  const [open, setOpen] = useState(false);
  const summary = getReasoningBlockSummary(messages);
  const stepCount = messages.length;
  const hasError = messages.some((m) => m.msg_type === "error_observation");

  return (
    <div className="flex justify-start">
      <Collapsible open={open} onOpenChange={setOpen} className="max-w-[90%]">
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] transition-colors border",
              isActive
                ? "bg-primary/5 border-primary/15 text-primary"
                : hasError
                  ? "bg-amber-500/5 border-amber-500/15 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"
                  : "bg-violet-500/5 border-violet-500/15 text-violet-500 hover:bg-violet-500/10"
            )}
          >
            {isActive ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <BrainCircuit className="h-3 w-3" />
            )}
            <span className="font-medium truncate max-w-[240px]">
              {isActive ? "思考中..." : summary}
            </span>
            {!isActive && (
              <>
                <span className="text-[9px] opacity-60">{stepCount} 步</span>
                <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
              </>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-1.5 ml-1.5 pl-3 border-l-2 border-violet-500/20 space-y-0.5">
            {messages.map((msg) => (
              <ReasoningStepInline key={msg.id} msg={msg} onRetry={onRetry} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
