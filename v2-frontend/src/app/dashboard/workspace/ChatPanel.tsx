"use client";

import { useRef, useEffect } from "react";
import type { ChatSession, ChatMessage } from "@/lib/chat-api";
import { ChatBubble, ReasoningBlock } from "@/components/chat-bubble";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SendHorizontal, MessageSquare, Loader2, Paperclip, X } from "lucide-react";
import { toast } from "sonner";

interface ChatPanelProps {
  session: ChatSession | null;
  messages: ChatMessage[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  sending: boolean;
  error: string;
  file: File | null;
  onFileChange: (f: File | null) => void;
  onRetry?: (toolName: string) => void;
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
    if (REASONING_TYPES.has(msgType)) {
      currentReasoning.push(msg);
    } else {
      flushReasoning();
      groups.push({ type: "single", message: msg });
    }
  }
  flushReasoning();

  return groups;
}

export default function ChatPanel({
  session,
  messages,
  input,
  onInputChange,
  onSend,
  sending,
  error,
  file,
  onFileChange,
  onRetry,
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
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
            <div className="flex flex-col items-center justify-center h-[60vh] text-center">
              <h2 className="text-base font-medium mb-1">有什么我可以帮你的？</h2>
              <p className="text-xs text-muted-foreground max-w-xs">
                试试问：「数据库里有多少产品？」「日本的供应商有哪些？」
              </p>
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
                    />
                  );
                })}
                {/* Sending indicator — only when last group is NOT reasoning (it has its own spinner) */}
                {sending && !hasStreaming && !lastIsReasoning && (
                  <div className="flex justify-start">
                    <div className="flex items-center gap-2 px-4 py-2.5 rounded-2xl rounded-bl-md bg-card border border-border/50">
                      <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
                      <span className="text-xs text-muted-foreground">思考中...</span>
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
                    placeholder={file ? "描述这份文件..." : "输入消息..."}
                    disabled={sending}
                    rows={1}
                    className="min-h-[40px] max-h-24 resize-none pr-10 text-sm"
                  />
                  <Button
                    onClick={onSend}
                    disabled={(!input.trim() && !file) || sending}
                    size="icon"
                    variant="ghost"
                    className="absolute right-1 bottom-1 h-8 w-8 text-primary"
                  >
                    <SendHorizontal className="h-4 w-4" />
                  </Button>
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
