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
} from "@/lib/chat-api";
import { toast } from "sonner";
import SessionSidebar from "./SessionSidebar";
import ChatPanel from "./ChatPanel";

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

  const streamAbortRef = useRef<(() => void) | null>(null);

  // Typewriter animation state
  const typewriterRef = useRef<{
    msgId: number;
    target: string;
    revealed: number;
    done: boolean;
    finalContent: string;
    finalCreatedAt: string;
  } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopTypewriter() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    typewriterRef.current = null;
  }

  function startTypewriter(msgId: number) {
    if (timerRef.current) return;

    timerRef.current = setInterval(() => {
      const tw = typewriterRef.current;
      if (!tw || tw.msgId !== msgId) {
        clearInterval(timerRef.current!);
        timerRef.current = null;
        return;
      }

      const nextReveal = Math.min(tw.revealed + 3, tw.target.length);
      tw.revealed = nextReveal;
      const isComplete = tw.done && nextReveal >= tw.target.length;

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
        clearInterval(timerRef.current!);
        timerRef.current = null;
        typewriterRef.current = null;
      }
    }, 20);
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

  // Select session
  async function handleSelectSession(id: string) {
    if (id === activeSessionId) return;
    stopStream();
    setSending(false);
    setActiveSessionId(id);
    setMessages([]);
    setInput("");
    setError("");

    const session = sessions.find((s) => s.id === id);
    setActiveSession(session || null);

    try {
      const msgs = await getChatMessages(id);
      setMessages(msgs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载消息失败");
    }
  }

  // New session
  async function handleNewSession() {
    stopStream();
    setError("");
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
  async function handleDeleteSession(id: string) {
    try {
      await deleteChatSession(id);
      if (id === activeSessionId) {
        stopStream();
        setActiveSessionId(null);
        setActiveSession(null);
        setMessages([]);
        setSending(false);
      }
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  // Core send logic — used by both handleSend and handleRetry
  async function doSend(text: string, currentFile: File | null = null) {
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
      const { last_msg_id } = await sendChatMessage(sid, text, currentFile);

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

  // Public send handler — extracts current input/file state
  function handleSend() {
    if ((!input.trim() && !file) || !activeSessionId || sending) return;
    const text = input.trim() || (file ? `请帮我处理这份文件` : "");
    doSend(text, file);
  }

  // Retry handler — sends a retry request as a new user message
  function handleRetry(toolName: string) {
    if (!activeSessionId || sending) return;
    doSend(`请重新执行上一步操作 (${toolName})`);
  }

  return (
    <div className="h-full flex">
      <SessionSidebar
        sessions={sessions}
        activeId={activeSessionId}
        onSelect={handleSelectSession}
        onNewSession={handleNewSession}
        onDelete={handleDeleteSession}
        loading={sessionsLoading}
      />
      <ChatPanel
        session={activeSession}
        messages={messages}
        input={input}
        onInputChange={setInput}
        onSend={handleSend}
        sending={sending}
        error={error}
        file={file}
        onFileChange={setFile}
        onRetry={handleRetry}
      />
    </div>
  );
}
