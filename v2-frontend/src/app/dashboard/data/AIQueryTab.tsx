"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  createChatSession,
  sendChatMessage,
  streamChatMessages,
  deleteChatSession,
  type ChatMessage,
  type TokenEvent,
  type TokenDoneEvent,
} from "@/lib/chat-api";
import { DataTable } from "@/components/data-table";
import { MarkdownContent } from "@/components/markdown-content";
import { exportToCSV } from "@/lib/export-csv";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { type ColumnDef } from "@tanstack/react-table";
import { Sparkles, Loader2, Search, Download, Database, RotateCcw } from "lucide-react";
import { toast } from "sonner";

// P1-3: Simple retry wrapper for transient network failures
async function fetchWithRetry<T>(fn: () => Promise<T>, retries = 1): Promise<T> {
  for (let i = 0; i <= retries; i++) {
    try {
      return await fn();
    } catch (e) {
      if (i === retries) throw e;
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  throw new Error("unreachable");
}

type Row = Record<string, unknown>;

interface QueryResult {
  columns: string[];
  rows: Row[];
  total: number;
  truncated?: boolean;
}

export default function AIQueryTab() {
  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [answer, setAnswer] = useState("");
  const [sql, setSql] = useState("");
  const [error, setError] = useState("");

  const streamAbortRef = useRef<(() => void) | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const busyRef = useRef(false); // synchronous guard against double-click

  // Accumulated text tokens during streaming
  const answerBufRef = useRef("");

  const cleanup = useCallback(async () => {
    streamAbortRef.current?.();
    streamAbortRef.current = null;
    if (sessionIdRef.current) {
      try {
        await deleteChatSession(sessionIdRef.current);
      } catch {
        // ignore
      }
      sessionIdRef.current = null;
    }
  }, []);

  // P0-1: Cleanup SSE connection on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      streamAbortRef.current?.();
      cleanup();
    };
  }, [cleanup]);

  const doQuery = useCallback(
    async (text: string) => {
      if (!text.trim() || busyRef.current) return;

      // Synchronous guard — prevents double-click race
      busyRef.current = true;

      // Reset state
      setLoading(true);
      setResult(null);
      setAnswer("");
      setSql("");
      setError("");
      setInput("");
      answerBufRef.current = "";

      // Cleanup previous session
      await cleanup();

      try {
        // Create a fresh session per query (with retry for transient failures)
        const session = await fetchWithRetry(() => createChatSession("数据查询"));
        sessionIdRef.current = session.id;

        // Send the message (with retry for transient failures)
        const { last_msg_id } = await fetchWithRetry(() => sendChatMessage(session.id, text));

        // Stream response — consume silently, extract data
        const abort = streamChatMessages(
          session.id,
          last_msg_id - 1,
          // onMessage — full messages (action, observation, error, text, etc.)
          (msg: ChatMessage) => {
            const type = msg.msg_type || "text";

            // Extract SQL from action messages
            if (type === "action" && msg.metadata) {
              const toolName = msg.metadata.tool_name as string | undefined;
              const toolArgs = msg.metadata.tool_args as Record<string, unknown> | undefined;
              if (toolName === "query_db" && toolArgs?.sql) {
                setSql(String(toolArgs.sql));
              }
            }

            // Extract table data from observation messages
            if (type === "observation" || msg.role === "tool") {
              try {
                const parsed = JSON.parse(msg.content);
                if (parsed.columns && Array.isArray(parsed.rows)) {
                  setResult({
                    columns: parsed.columns,
                    rows: parsed.rows,
                    total: parsed.total ?? parsed.rows.length,
                    truncated: parsed.truncated,
                  });
                }
              } catch {
                // Not JSON table data — ignore
              }
            }

            // Error messages
            if (type === "error_observation" || type === "error") {
              setError(msg.content);
              toast.error(msg.content.slice(0, 120));
            }

            // Full text messages (non-streaming)
            if (type === "text" && msg.role === "assistant" && !msg.streaming) {
              setAnswer(msg.content);
              answerBufRef.current = msg.content; // P0-2: sync buffer to prevent onToken overwrite
            }
          },
          // onDone
          () => {
            // Flush any buffered answer text
            if (answerBufRef.current) {
              setAnswer(answerBufRef.current);
            }
            busyRef.current = false;
            setLoading(false);
          },
          // onError
          (err) => {
            if (process.env.NODE_ENV === "development") console.error("Stream error:", err);
            toast.error("连接中断，请重试");
            busyRef.current = false;
            setLoading(false);
          },
          // onToken — accumulate text tokens
          (token: TokenEvent) => {
            if (token.msg_type === "text") {
              answerBufRef.current += token.content;
              setAnswer(answerBufRef.current);
            }
          },
          // onTokenDone — finalize text
          (done: TokenDoneEvent) => {
            answerBufRef.current = done.full_content;
            setAnswer(done.full_content);
          },
        );

        streamAbortRef.current = abort;
      } catch (err) {
        if (process.env.NODE_ENV === "development") console.error("Query error:", err);
        toast.error(err instanceof Error ? err.message : "查询失败");
        busyRef.current = false;
        setLoading(false);
      }
    },
    [cleanup],
  );

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doQuery(input);
    }
  }

  function handleReset() {
    cleanup();
    busyRef.current = false;
    setLoading(false);
    setResult(null);
    setAnswer("");
    setSql("");
    setError("");
  }

  function handleExportCSV() {
    if (!result) return;
    const headers = result.columns;
    const rows = result.rows.map((row) =>
      headers.map((col) => {
        const v = row[col];
        if (v == null) return "";
        if (typeof v === "object") return JSON.stringify(v);
        return v;
      }),
    );
    exportToCSV(
      headers,
      rows as (string | number | null | undefined)[][],
      `ai-query-${new Date().toISOString().slice(0, 10)}.csv`,
    );
  }

  // Dynamic columns from result
  const tableColumns: ColumnDef<Row, unknown>[] = result
    ? result.columns.map((col) => ({
        accessorKey: col,
        header: col,
        cell: ({ getValue }: { getValue: () => unknown }) => {
          const v = getValue();
          if (v === null || v === undefined) return <span className="text-muted-foreground">-</span>;
          if (typeof v === "number") return v.toLocaleString("zh-CN");
          if (typeof v === "object") return <span className="font-mono text-[10px]">{JSON.stringify(v)}</span>;
          return String(v);
        },
      }))
    : [];

  const hasResult = !!(result || answer || error);
  const showEmptyState = !hasResult && !loading;

  return (
    <div className="h-full flex flex-col">
      {/* Input bar */}
      <div className="shrink-0 px-4 py-3 border-b border-border/50">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入自然语言查询，如：价格最高的前10个产品"
              disabled={loading}
              className="pl-10 h-9 text-sm"
            />
          </div>
          <Button
            onClick={() => doQuery(input)}
            disabled={!input.trim() || loading}
            size="sm"
            className="h-9 px-4"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "查询"}
          </Button>
          {hasResult && (
            <Button
              onClick={handleReset}
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-muted-foreground"
              title="清除结果"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto">
        {/* Empty state */}
        {showEmptyState && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-5">
              <Sparkles className="h-6 w-6 text-primary" />
            </div>
            <h2 className="text-base font-medium mb-2">AI 智能查询</h2>
            <p className="text-xs text-muted-foreground max-w-sm leading-relaxed">
              用自然语言查询数据库，结果以表格展示
            </p>
            <div className="mt-4 space-y-1.5">
              {[
                "查一下日本所有供应商的联系信息",
                "价格最高的前10个产品",
                "按国家统计产品数量",
              ].map((example) => (
                <button
                  key={example}
                  onClick={() => doQuery(example)}
                  className="block w-full text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-lg px-4 py-2 transition-colors text-left"
                >
                  &ldquo;{example}&rdquo;
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Loading state (no data yet) */}
        {loading && !result && !answer && (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <Loader2 className="h-6 w-6 text-primary animate-spin" />
            <span className="text-sm text-muted-foreground">AI 正在分析...</span>
            {sql && (
              <div className="max-w-lg mt-2 px-3 py-2 rounded-lg bg-muted/50 border border-border/30">
                <p className="text-[10px] text-muted-foreground mb-1">执行 SQL:</p>
                <code className="text-[11px] font-mono text-foreground/80 break-all">{sql}</code>
              </div>
            )}
          </div>
        )}

        {/* Results — show progressively as data arrives (even while still loading) */}
        {(answer || result || error) && (
          <div className="flex flex-col h-full">
            {/* P1-4: Error banner — always visible even when answer/result present */}
            {error && (
              <div className="px-4 pt-3 shrink-0">
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-600">
                  {error}
                </div>
              </div>
            )}

            {/* Loading indicator while still streaming */}
            {loading && (
              <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-border/30">
                <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
                <span className="text-xs text-muted-foreground">AI 正在生成回答...</span>
              </div>
            )}

            {/* AI answer summary */}
            {answer && (
              <div className="px-4 pt-3 pb-2 shrink-0">
                <div className="max-w-none rounded-lg border border-border/50 bg-card px-4 py-3">
                  <MarkdownContent content={answer} />
                </div>
              </div>
            )}

            {/* Data table */}
            {result && result.rows.length > 0 && (
              <div className="flex-1 min-h-0">
                <DataTable
                  columns={tableColumns}
                  data={result.rows}
                  searchKey={result.columns[0]}
                  searchPlaceholder={`搜索 ${result.columns[0]}...`}
                  toolbar={
                    <div className="flex items-center gap-2 ml-auto">
                      {result.truncated && (
                        <span className="text-[10px] text-amber-500">
                          结果已截断（显示前 {result.rows.length} / {result.total} 条）
                        </span>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs gap-1.5"
                        onClick={handleExportCSV}
                      >
                        <Download className="h-3 w-3" />
                        导出 CSV
                      </Button>
                    </div>
                  }
                />
              </div>
            )}

            {/* SQL preview footer */}
            {sql && (
              <div className="shrink-0 px-4 py-2 border-t border-border/50 flex items-center gap-2 text-[10px] text-muted-foreground">
                <Database className="h-3 w-3" />
                <code className="font-mono truncate flex-1">{sql}</code>
                {result && (
                  <span className="shrink-0">
                    共 {result.total} 条{result.truncated ? `（显示 ${result.rows.length}）` : ""}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
