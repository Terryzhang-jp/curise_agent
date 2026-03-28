"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import type { ChatSession, ChatMessage, TokenEvent, TokenDoneEvent } from "@/lib/chat-api";
import {
  createChatSession,
  listChatSessions,
  deleteChatSession,
  getChatMessages,
  sendChatMessage,
  streamChatMessages,
  cancelChatAgent,
} from "@/lib/chat-api";
import { toast } from "sonner";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import SessionSidebar from "./SessionSidebar";
import ChatPanel from "./ChatPanel";
import ArtifactPanel from "@/components/artifact-panel";

export default function WorkspacePage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [activeScenario, setActiveScenario] = useState<string | null>(null);

  // Artifact panel state
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [artifactFile, setArtifactFile] = useState<string | null>(null);

  const streamAbortRef = useRef<(() => void) | null>(null);
  // Stable ref for doSend — allows useCallback handlers to avoid stale closures
  const doSendRef = useRef<(text: string, file?: File | null, scenario?: string | null) => void>(() => {});

  // Typewriter animation state
  const typewriterRef = useRef<{
    msgId: number;
    target: string;
    revealed: number;
    done: boolean;
    finalContent: string;
    finalCreatedAt: string;
  } | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);

  function stopTypewriter() {
    const tw = typewriterRef.current;
    if (tw) {
      // Use authoritative full_content from token_done, fall back to accumulated
      // token target if token_done was never received (e.g. SSE timeout).
      const content = tw.finalContent || tw.target;
      if (content) {
        const { msgId, finalCreatedAt } = tw;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId
              ? { ...m, content, streaming: false, created_at: finalCreatedAt || m.created_at }
              : m
          )
        );
      }
    }
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    typewriterRef.current = null;
  }

  function startTypewriter(msgId: number) {
    if (rafRef.current) return;

    lastTickRef.current = performance.now();

    function tick(now: number) {
      const tw = typewriterRef.current;
      if (!tw || tw.msgId !== msgId) {
        rafRef.current = null;
        return;
      }

      // Throttle to ~50fps (20ms between updates)
      if (now - lastTickRef.current < 20) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }
      lastTickRef.current = now;

      // Dynamic chunk size: scale with content length for faster reveal on long text
      const pending = tw.target.length - tw.revealed;
      const chunk = Math.max(20, Math.floor(pending / 15));
      const prevRevealed = tw.revealed;
      const nextReveal = Math.min(tw.revealed + chunk, tw.target.length);
      tw.revealed = nextReveal;
      const isComplete = tw.done && nextReveal >= tw.target.length;

      // Nothing new to reveal and not complete — wait for more tokens without re-rendering
      if (nextReveal === prevRevealed && !isComplete) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? {
                ...m,
                content: isComplete ? tw.finalContent : tw.target.slice(0, nextReveal),
                streaming: !isComplete,
                created_at: isComplete ? tw.finalCreatedAt : m.created_at,
              }
            : m
        )
      );

      if (isComplete) {
        rafRef.current = null;
        typewriterRef.current = null;
      } else {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
  }

  const stopStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current();
      streamAbortRef.current = null;
    }
    stopTypewriter();
  }, []);

  useEffect(() => {
    return () => stopStream();
  }, [stopStream]);

  // Load sessions
  const refreshSessions = useCallback(async () => {
    try {
      setSessionsLoading(true);
      const data = await listChatSessions();
      setSessions(data);
    } catch {
      // Silently ignore
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // Detect generated_file cards in messages → auto-open artifact panel
  useEffect(() => {
    const latestMsg = messages[messages.length - 1];
    if (!latestMsg) return;
    const card = latestMsg.metadata?.structured_card as Record<string, unknown> | undefined;
    if (card?.card_type === "generated_file" && card.filename) {
      setArtifactOpen(true);
      setArtifactFile(card.filename as string);
    }
  }, [messages]);

  // Select session
  async function handleSelectSession(id: string) {
    if (id === activeSessionId) return;
    stopStream();
    setSending(false);
    setActiveSessionId(id);
    setMessages([]);
    setInput("");
    setError("");
    setActiveScenario(null);
    setArtifactOpen(false);
    setArtifactFile(null);

    const session = sessions.find((s) => s.id === id);
    setActiveSession(session || null);

    try {
      const msgs = await getChatMessages(id);
      setMessages(msgs);
      // Check if session has generated files → open artifact panel
      const hasFiles = msgs.some((m) => {
        const c = m.metadata?.structured_card as Record<string, unknown> | undefined;
        return c?.card_type === "generated_file";
      });
      if (hasFiles) {
        setArtifactOpen(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载消息失败");
    }
  }

  // New session
  async function handleNewSession() {
    stopStream();
    setError("");
    setActiveScenario(null);
    setArtifactOpen(false);
    setArtifactFile(null);
    try {
      const session = await createChatSession();
      setSessions((prev) => [session, ...prev]);
      setActiveSessionId(session.id);
      setActiveSession(session);
      setMessages([]);
      setInput("");
      setSending(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建会话失败");
    }
  }

  // Delete session
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function handleDeleteSession(id: string) {
    setDeletingId(id);
    try {
      await deleteChatSession(id);
      if (id === activeSessionId) {
        stopStream();
        setActiveSessionId(null);
        setActiveSession(null);
        setMessages([]);
        setSending(false);
        setActiveScenario(null);
        setArtifactOpen(false);
        setArtifactFile(null);
      }
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }

  // Open file in artifact panel (called from GeneratedFileBubble)
  const handleOpenArtifact = useCallback((filename: string) => {
    setArtifactOpen(true);
    setArtifactFile(filename);
  }, []);

  // Core send logic — used by both handleSend and handleRetry
  async function doSend(text: string, currentFile: File | null = null, scenario?: string | null) {
    if (!activeSessionId || sending) return;
    const sid = activeSessionId;
    setInput("");
    setFile(null);
    setSending(true);
    setError("");

    // Optimistic user message — show file name if attached
    const displayContent = currentFile ? `📎 ${currentFile.name}\n${text}` : text;
    const optimisticMsg: ChatMessage = {
      id: -1,
      role: "user",
      content: displayContent,
      msg_type: "user_input",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const { last_msg_id } = await sendChatMessage(sid, text, currentFile, scenario);

      stopStream();
      streamAbortRef.current = streamChatMessages(
        sid,
        last_msg_id,
        (msg) => {
          // Toast for error messages
          if (msg.msg_type === "error_observation" || msg.msg_type === "error") {
            const severity = (msg.metadata?.severity as string) || "error";
            if (severity === "error" || severity === "critical" || msg.msg_type === "error") {
              toast.error(msg.content.slice(0, 100));
            } else {
              toast.warning(msg.content.slice(0, 100));
            }
          }
          setMessages((prev) => {
            if (msg.msg_type === "user_input" && msg.role === "user") {
              const withoutOptimistic = prev.filter((m) => m.id !== -1);
              return [...withoutOptimistic, msg];
            }
            return [...prev, msg];
          });
        },
        (title) => {
          stopTypewriter(); // Finalize any in-progress typewriter with full content
          setSending(false);
          streamAbortRef.current = null;
          if (title) {
            setSessions((prev) =>
              prev.map((s) =>
                s.id === sid ? { ...s, title, updated_at: new Date().toISOString() } : s
              )
            );
            setActiveSession((prev) => (prev ? { ...prev, title } : prev));
          }
        },
        (err) => {
          setError(err.message);
          setSending(false);
          streamAbortRef.current = null;
        },
        (token: TokenEvent) => {
          const tw = typewriterRef.current;
          if (tw && tw.msgId === token.msg_id) {
            tw.target += token.content;
          } else {
            typewriterRef.current = {
              msgId: token.msg_id,
              target: token.content,
              revealed: 0,
              done: false,
              finalContent: "",
              finalCreatedAt: "",
            };
            setMessages((prev) => [
              ...prev,
              {
                id: token.msg_id,
                role: token.role as ChatMessage["role"],
                content: "",
                msg_type: token.msg_type as ChatMessage["msg_type"],
                created_at: new Date().toISOString(),
                streaming: true,
              },
            ]);
            startTypewriter(token.msg_id);
          }
        },
        (done: TokenDoneEvent) => {
          const tw = typewriterRef.current;
          if (tw && tw.msgId === done.msg_id) {
            tw.done = true;
            tw.target = done.full_content;
            tw.finalContent = done.full_content;
            tw.finalCreatedAt = done.created_at;
          } else {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === done.msg_id
                  ? { ...m, content: done.full_content, created_at: done.created_at, streaming: false }
                  : m
              )
            );
          }
        },
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送失败");
      setSending(false);
    }
  }

  // Keep ref in sync so stable callbacks always call the latest doSend
  doSendRef.current = doSend;

  // Public send handler — extracts current input/file state
  function handleSend() {
    if ((!input.trim() && !file) || !activeSessionId || sending) return;
    const text = input.trim() || (file ? `请帮我处理这份文件` : "");
    const scenario = activeScenario;
    setActiveScenario(null);
    doSend(text, file, scenario);
  }

  // Retry handler — stable ref to avoid breaking React.memo on ChatBubble
  const handleRetry = useCallback((toolName: string) => {
    doSendRef.current(`请重新执行上一步操作 (${toolName})`);
  }, []);

  // Stop handler — cancel the running agent and close SSE stream
  const handleStop = useCallback(async () => {
    if (!activeSessionId) return;
    stopStream();
    setSending(false);
    try {
      await cancelChatAgent(activeSessionId);
    } catch {
      // Best effort — agent may have already finished
    }
  }, [activeSessionId, stopStream]);

  // Quick action handler — stable ref to avoid breaking React.memo on ChatBubble
  const handleQuickAction = useCallback((text: string, scenario?: string) => {
    if (text.trim()) {
      // Has text → send immediately with scenario
      doSendRef.current(text, null, scenario);
    } else if (scenario) {
      // No text but has scenario → set scenario, wait for user input
      setActiveScenario(scenario);
    }
  }, []);

  return (
    <div className="h-full flex">
      <SessionSidebar
        sessions={sessions}
        activeId={activeSessionId}
        onSelect={handleSelectSession}
        onNewSession={handleNewSession}
        onDelete={handleDeleteSession}
        deletingId={deletingId}
        loading={sessionsLoading}
      />
      {artifactOpen && activeSessionId ? (
        <PanelGroup className="flex-1">
          <Panel defaultSize={55} minSize={35}>
            <ChatPanel
              session={activeSession}
              messages={messages}
              input={input}
              onInputChange={setInput}
              onSend={handleSend}
              onStop={handleStop}
              sending={sending}
              error={error}
              file={file}
              onFileChange={setFile}
              onRetry={handleRetry}
              onQuickAction={handleQuickAction}
              activeScenario={activeScenario}
              onClearScenario={() => setActiveScenario(null)}
              onOpenArtifact={handleOpenArtifact}
            />
          </Panel>
          <PanelResizeHandle className="w-1 bg-border/30 hover:bg-primary/30 transition-colors cursor-col-resize" />
          <Panel defaultSize={45} minSize={25}>
            <ArtifactPanel
              sessionId={activeSessionId}
              selectedFile={artifactFile}
              onSelectFile={setArtifactFile}
              onClose={() => setArtifactOpen(false)}
            />
          </Panel>
        </PanelGroup>
      ) : (
        <ChatPanel
          session={activeSession}
          messages={messages}
          input={input}
          onInputChange={setInput}
          onSend={handleSend}
          onStop={handleStop}
          sending={sending}
          error={error}
          file={file}
          onFileChange={setFile}
          onRetry={handleRetry}
          onQuickAction={handleQuickAction}
          activeScenario={activeScenario}
          onClearScenario={() => setActiveScenario(null)}
          onOpenArtifact={handleOpenArtifact}
        />
      )}
    </div>
  );
}
