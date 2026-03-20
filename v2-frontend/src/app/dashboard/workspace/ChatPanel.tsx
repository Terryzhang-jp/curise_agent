"use client";

import { useRef, useEffect, useCallback } from "react";
import type { ChatSession, ChatMessage } from "@/lib/chat-api";
import { ChatBubble, ReasoningBlock } from "@/components/chat-bubble";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SendHorizontal, MessageSquare, Loader2, Paperclip, X, Upload, Search, ClipboardList, Package, Square } from "lucide-react";
import { toast } from "sonner";

interface ChatPanelProps {
  session: ChatSession | null;
  messages: ChatMessage[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  sending: boolean;
  error: string;
  file: File | null;
  onFileChange: (f: File | null) => void;
  onRetry?: (toolName: string) => void;
  onQuickAction?: (text: string, scenario?: string) => void;
  activeScenario?: string | null;
  onClearScenario?: () => void;
}

const ALLOWED_EXTENSIONS = [".xlsx", ".xls", ".pdf", ".csv"];
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB

function validateFile(f: File): string | null {
  const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return `不支持的文件类型: ${ext}。支持: ${ALLOWED_EXTENSIONS.join(", ")}`;
  }
  if (f.size > MAX_FILE_SIZE) {
    return "文件大小不能超过 20 MB";
  }
  return null;
}

// ─── Message grouping ────────────────────────────────────────

type MessageGroup =
  | { type: "single"; message: ChatMessage }
  | { type: "reasoning"; messages: ChatMessage[]; key: string };

const REASONING_TYPES = new Set(["thinking", "action", "observation", "error_observation"]);

function groupMessages(messages: ChatMessage[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  let currentReasoning: ChatMessage[] = [];

  function flushReasoning() {
    if (currentReasoning.length > 0) {
      groups.push({
        type: "reasoning",
        messages: [...currentReasoning],
        key: `reasoning-${currentReasoning[0].id}`,
      });
      currentReasoning = [];
    }
  }

  for (const msg of messages) {
    const msgType = msg.msg_type || "text";
    // Structured cards with interactive buttons should appear in main chat flow,
    // not hidden inside collapsed reasoning blocks
    const isStructuredCard = msgType === "observation" &&
      (msg.metadata?.structured_card || msg.metadata?.upload_data);
    if (isStructuredCard) {
      flushReasoning();
      groups.push({ type: "single", message: msg });
    } else if (REASONING_TYPES.has(msgType)) {
      currentReasoning.push(msg);
    } else {
      flushReasoning();
      groups.push({ type: "single", message: msg });
    }
  }
  flushReasoning();

  return groups;
}

const SCENARIO_LABELS: Record<string, string> = {
  data_upload: "上传数据",
  query: "查询数据",
  order_management: "订单管理",
  fulfillment: "履约管理",
};

const SCENARIO_PLACEHOLDERS: Record<string, string> = {
  data_upload: "描述你要上传的数据，或直接拖入文件...",
  query: "输入你想查询的内容，如「日本有多少供应商？」",
  order_management: "输入订单相关问题，如「最近的订单有哪些？」",
  fulfillment: "输入履约相关操作，如「订单123已交货」",
};

function ScenarioButton({ icon, label, desc, onClick }: {
  icon: React.ReactNode;
  label: string;
  desc: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex items-start gap-3 p-3.5 rounded-xl border border-border/60 hover:border-primary/40 hover:bg-accent/50 hover:shadow-sm transition-all text-left"
    >
      <div className="shrink-0 w-8 h-8 rounded-lg bg-primary/10 group-hover:bg-primary/15 flex items-center justify-center transition-colors">
        <div className="text-primary">{icon}</div>
      </div>
      <div className="min-w-0">
        <div className="text-sm font-medium leading-tight">{label}</div>
        <div className="text-xs text-muted-foreground mt-0.5 leading-snug">{desc}</div>
      </div>
    </button>
  );
}

export default function ChatPanel({
  session,
  messages,
  input,
  onInputChange,
  onSend,
  onStop,
  sending,
  error,
  file,
  onFileChange,
  onRetry,
  onQuickAction,
  activeScenario,
  onClearScenario,
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const userScrolledUpRef = useRef(false);

  // Detect user scroll: if user scrolls away from bottom, stop auto-scroll
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // "near bottom" = within 150px of the bottom edge
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    userScrolledUpRef.current = !nearBottom;
  }, []);

  useEffect(() => {
    // Only auto-scroll if user hasn't scrolled up
    if (!userScrolledUpRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // Reset scroll lock when sending a new message (user expects to see the response)
  useEffect(() => {
    if (sending) {
      userScrolledUpRef.current = false;
    }
  }, [sending]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 h-full">
      {/* Messages area */}
      <div ref={scrollContainerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-6 space-y-4">
          {/* Empty states */}
          {!session && (
            <div className="flex flex-col items-center justify-center h-[60vh] text-center">
              <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-5">
                <MessageSquare className="h-6 w-6 text-primary" />
              </div>
              <h2 className="text-base font-medium mb-1">有什么我可以帮你的？</h2>
              <p className="text-xs text-muted-foreground max-w-xs">
                我可以查询产品数据库、供应商信息、订单状态等。点击左侧"新建对话"开始。
              </p>
            </div>
          )}

          {session && messages.length === 0 && !sending && (
            <div className="flex flex-col items-center justify-center h-[60vh] text-center gap-5">
              <div className="text-4xl">👋</div>
              <div>
                <h2 className="text-lg font-semibold">有什么我可以帮你的？</h2>
                <p className="text-sm text-muted-foreground mt-1">选择一个场景快速开始，或直接输入问题</p>
              </div>
              <div className="grid grid-cols-2 gap-2.5 w-full max-w-[420px]">
                <ScenarioButton
                  icon={<Upload className="h-4 w-4" />}
                  label="上传数据"
                  desc="上传报价单、更新产品价格"
                  onClick={() => onQuickAction?.("我要上传产品数据", "data_upload")}
                />
                <ScenarioButton
                  icon={<Search className="h-4 w-4" />}
                  label="查询数据"
                  desc="查产品、供应商、订单信息"
                  onClick={() => onQuickAction?.("", "query")}
                />
                <ScenarioButton
                  icon={<ClipboardList className="h-4 w-4" />}
                  label="订单管理"
                  desc="查看订单、生成询价单"
                  onClick={() => onQuickAction?.("", "order_management")}
                />
                <ScenarioButton
                  icon={<Package className="h-4 w-4" />}
                  label="履约管理"
                  desc="交货验收、发票付款"
                  onClick={() => onQuickAction?.("", "fulfillment")}
                />
              </div>
            </div>
          )}

          {/* Messages (grouped) */}
          {(() => {
            const grouped = groupMessages(messages);
            const hasStreaming = messages.some((m) => (m as ChatMessage & { streaming?: boolean }).streaming);
            const lastGroup = grouped[grouped.length - 1];
            const lastIsReasoning = lastGroup?.type === "reasoning";

            return (
              <>
                {grouped.map((group) => {
                  if (group.type === "single") {
                    const msg = group.message;
                    return (
                      <ChatBubble
                        key={msg.id}
                        role={msg.role}
                        content={msg.content}
                        msgType={msg.msg_type}
                        createdAt={msg.created_at}
                        streaming={(msg as ChatMessage & { streaming?: boolean }).streaming}
                        metadata={msg.metadata}
                        onRetry={onRetry}
                        onQuickAction={onQuickAction}
                      />
                    );
                  }
                  // reasoning group
                  const isActive = sending && group === lastGroup;
                  return (
                    <ReasoningBlock
                      key={group.key}
                      messages={group.messages}
                      isActive={isActive}
                      onRetry={onRetry}
                      onQuickAction={onQuickAction}
                    />
                  );
                })}
                {/* Sending indicator — only when no reasoning block or streaming is visible */}
                {sending && !hasStreaming && !lastIsReasoning && (
                  <div className="flex justify-start animate-in fade-in-0 duration-300">
                    <div className="thinking-shimmer flex items-center gap-2 px-4 py-2.5 rounded-2xl rounded-bl-md bg-card border border-border/40 shadow-sm">
                      <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
                      <span className="text-xs text-muted-foreground">
                        思考中
                        <span className="thinking-dots ml-0.5">
                          <span>.</span><span>.</span><span>.</span>
                        </span>
                      </span>
                    </div>
                  </div>
                )}
              </>
            );
          })()}

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-xs text-destructive">
              {error}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input bar */}
      <div className="shrink-0 border-t border-border/50 bg-background/80 backdrop-blur-sm">
        <div className="max-w-2xl mx-auto px-4 py-3">
          {!session ? (
            <p className="text-center text-muted-foreground text-xs py-1">创建新对话开始聊天</p>
          ) : (
            <>
              {/* Active scenario indicator */}
              {activeScenario && (
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-medium">
                    {SCENARIO_LABELS[activeScenario] || activeScenario}
                    <button
                      onClick={onClearScenario}
                      className="ml-0.5 hover:bg-primary/20 rounded-full p-0.5 transition-colors"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                </div>
              )}
              {/* File preview */}
              {file && (
                <div className="flex items-center gap-2 mb-2 px-2 py-1.5 rounded-lg bg-muted/50 border border-border/50 text-xs">
                  <Paperclip className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="truncate flex-1">{file.name}</span>
                  <span className="text-muted-foreground shrink-0">
                    {(file.size / 1024).toFixed(0)} KB
                  </span>
                  <button
                    onClick={() => onFileChange(null)}
                    className="text-muted-foreground hover:text-foreground shrink-0"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              <div className="flex items-end gap-2">
                {/* Hidden file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.pdf,.csv,.jpg,.jpeg,.png,.webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0] || null;
                    if (f) {
                      const err = validateFile(f);
                      if (err) {
                        toast.error(err);
                        e.target.value = "";
                        return;
                      }
                    }
                    onFileChange(f);
                    e.target.value = "";  // Reset so same file can be selected again
                  }}
                />
                <Button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={sending}
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-muted-foreground hover:text-foreground shrink-0"
                  title="附件"
                >
                  <Paperclip className="h-4 w-4" />
                </Button>
                <div className="flex-1 relative">
                  <Textarea
                    value={input}
                    onChange={(e) => onInputChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={file ? "描述这份文件..." : (activeScenario && SCENARIO_PLACEHOLDERS[activeScenario]) || "输入消息..."}
                    disabled={sending}
                    rows={1}
                    className="min-h-[40px] max-h-24 resize-none pr-10 text-sm"
                  />
                  {sending ? (
                    <Button
                      onClick={onStop}
                      size="icon"
                      variant="ghost"
                      className="absolute right-1 bottom-1 h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                      title="停止"
                    >
                      <Square className="h-3.5 w-3.5 fill-current" />
                    </Button>
                  ) : (
                    <Button
                      onClick={onSend}
                      disabled={!input.trim() && !file}
                      size="icon"
                      variant="ghost"
                      className="absolute right-1 bottom-1 h-8 w-8 text-primary"
                    >
                      <SendHorizontal className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
          {session && (
            <p className="text-[10px] text-muted-foreground text-center mt-1.5">
              Enter 发送 · Shift+Enter 换行 · 📎 附件上传 Excel/PDF
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
