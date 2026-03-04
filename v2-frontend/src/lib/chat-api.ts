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

// ─── Upload structured data types ──────────────────────────────

export interface UploadValidationData {
  card_type?: "upload_validation";
  tool: "resolve_and_validate";
  batch_id: number;
  stats: { new: number; update: number; no_change: number; anomaly: number };
  total: number;
  supplier: { name: string | null; id: number | null };
  country: { name: string | null; id: number | null };
  confidence: { high: number; mid: number; low: number; new: number };
  quarantined: Array<{
    row: number;
    name: string;
    code: string | null;
    db_name: string;
    confidence: number;
    action: string;
    price_change_pct: number | null;
  }>;
  missing_supplier: boolean;
  missing_country: boolean;
}

export interface UploadPreviewData {
  card_type?: "upload_preview";
  tool: "preview_changes";
  batch_id: number;
  supplier: { name: string | null; id: number | null };
  country: { name: string | null; id: number | null };
  stats: { new: number; update: number; anomaly: number; no_change: number };
  anomalies: Array<{
    row: number;
    name: string;
    old_price: number | null;
    new_price: number | null;
    change_pct: number | null;
  }>;
  new_items: Array<{ row: number; name: string; code: string | null; price: number | null }>;
  updates: Array<{
    row: number;
    name: string;
    old_price: number | null;
    new_price: number | null;
    change_pct: number | null;
  }>;
}

export interface UploadResultData {
  card_type?: "upload_result";
  tool: "execute_upload";
  batch_id: number;
  status: "completed" | "partial";
  stats: { inserted: number; updated: number; skipped: number; excluded: number; failed: number };
  failures: string[];
}

export interface ConfirmationCardData {
  card_type: "confirmation";
  title: string;
  description: string;
  actions: Array<{ label: string; message: string; variant: "default" | "outline" | "destructive" }>;
}

export interface QueryTableCardData {
  card_type: "query_table";
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  truncated?: boolean;
}

export interface DataAuditFinding {
  severity: "error" | "warning" | "info";
  category: string;
  rows: number[];
  message: string;
  suggestion: string;
}

export interface DataAuditCardData {
  card_type: "data_audit";
  batch_id: number;
  total_rows: number;
  findings: DataAuditFinding[];
  summary: string;
  stats: { error: number; warning: number; info: number };
}

export type StructuredCard =
  | UploadValidationData | UploadPreviewData | UploadResultData
  | ConfirmationCardData | QueryTableCardData
  | DataAuditCardData;

export type UploadData = UploadValidationData | UploadPreviewData | UploadResultData;

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
