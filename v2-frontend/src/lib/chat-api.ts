import { fetchWithAuth } from "./fetch-with-auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// ─── Types ─────────────────────────────────────────────────────

export interface ChatSession {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at?: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "tool";
  content: string;
  msg_type?: "user_input" | "text" | "action" | "observation" | "error_observation" | "error" | "thinking";
  created_at: string;
  streaming?: boolean; // true while tokens are still arriving
  metadata?: Record<string, unknown>;
}

export interface TokenEvent {
  content: string;
  msg_id: number;
  role: string;
  msg_type: string;
}

export interface TokenDoneEvent {
  msg_id: number;
  full_content: string;
  created_at: string;
}

// ─── Helpers ───────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Sessions ──────────────────────────────────────────────────

export async function createChatSession(
  title: string = "新对话"
): Promise<ChatSession> {
  const res = await fetchWithAuth(`${API_BASE}/api/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return handleResponse<ChatSession>(res);
}

export async function listChatSessions(): Promise<ChatSession[]> {
  const res = await fetchWithAuth(`${API_BASE}/api/chat/sessions`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<ChatSession[]>(res);
}

export async function getChatSession(
  sessionId: string
): Promise<ChatSession> {
  const res = await fetchWithAuth(`${API_BASE}/api/chat/sessions/${sessionId}`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<ChatSession>(res);
}

export async function deleteChatSession(
  sessionId: string
): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/api/chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "删除失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

// ─── Messages ──────────────────────────────────────────────────

export async function getChatMessages(
  sessionId: string
): Promise<ChatMessage[]> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/chat/sessions/${sessionId}/messages`,
    { headers: { "Content-Type": "application/json" } }
  );
  return handleResponse<ChatMessage[]>(res);
}

export async function sendChatMessage(
  sessionId: string,
  content: string,
  file?: File | null,
): Promise<{ status: string; session_id: string; last_msg_id: number }> {
  const url = `${API_BASE}/api/chat/sessions/${sessionId}/message`;

  // Always use FormData (backend now expects Form fields)
  const formData = new FormData();
  formData.append("content", content);
  if (file) {
    formData.append("file", file);
  }
  const res = await fetchWithAuth(url, {
    method: "POST",
    body: formData,
  });
  return handleResponse(res);
}

// ─── SSE Stream ────────────────────────────────────────────────

/**
 * Open an SSE stream to receive real-time messages from the agent.
 * Returns an abort function to close the stream.
 */
export function streamChatMessages(
  sessionId: string,
  afterId: number,
  onMessage: (msg: ChatMessage) => void,
  onDone: (title?: string) => void,
  onError: (err: Error) => void,
  onToken?: (token: TokenEvent) => void,
  onTokenDone?: (done: TokenDoneEvent) => void,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetchWithAuth(
        `${API_BASE}/api/chat/sessions/${sessionId}/stream?after_id=${afterId}`,
        {
          signal: controller.signal,
        }
      );

      if (!res.ok) {
        throw new Error(`SSE stream failed: HTTP ${res.status}`);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events (lines starting with "data: ")
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;

          // P0-3: Separate JSON parse from callback invocation so callback
          // exceptions propagate instead of being silently swallowed.
          let envelope: Record<string, unknown>;
          try {
            envelope = JSON.parse(trimmed.slice(6));
          } catch {
            continue; // JSON parse error → skip this line
          }

          const eventType = envelope.type;

          if (eventType === "done") {
            onDone((envelope.data as Record<string, unknown>)?.title as string | undefined);
            return;
          }

          if (eventType === "token" && onToken) {
            onToken(envelope.data as TokenEvent);
            continue;
          }

          if (eventType === "token_done" && onTokenDone) {
            onTokenDone(envelope.data as TokenDoneEvent);
            continue;
          }

          if (eventType === "message") {
            onMessage(envelope.data as ChatMessage);
            continue;
          }

          // Legacy: plain message without envelope (shouldn't happen but safe)
          if (envelope.id !== undefined && envelope.role !== undefined) {
            onMessage(envelope as unknown as ChatMessage);
          }
        }
      }

      // Stream ended without done event
      onDone();
    } catch (err) {
      if (!controller.signal.aborted) {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    }
  })();

  return () => controller.abort();
}
