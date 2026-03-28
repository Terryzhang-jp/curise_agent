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

export interface UploadReviewDiff {
  field: string;
  old: string | number | null;
  new: string | number | null;
}

export interface UploadReviewData {
  card_type: "upload_review";
  batch_id: number;
  supplier: { name: string | null; id: number | null };
  country: { name: string | null; id: number | null };
  port: { name: string | null; id: number | null };
  effective_from: string | null;
  effective_to: string | null;
  stats: { new: number; update: number; no_change: number; total: number };
  new_items: Array<{
    row: number; name: string; code: string | null;
    price: number | null; unit: string | null;
    pack_size: string | null; brand: string | null;
  }>;
  updates: Array<{
    row: number; name: string; code: string | null;
    confidence: number; match_method: string; db_name: string;
    diffs: UploadReviewDiff[];
    warning: string | null;
  }>;
  audit_findings: Array<{
    severity: string; message: string; suggestion: string;
  }>;
  missing_supplier: boolean;
  missing_country: boolean;
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

export interface GeneratedFileCardData {
  card_type: "generated_file";
  filename: string;
  session_id: string;
}

export function getFileDownloadUrl(sessionId: string, filename: string): string {
  return `${API_BASE}/api/chat/sessions/${sessionId}/files/${filename}`;
}

export interface WorkspaceFile {
  filename: string;
  size: number;
  version: number;
  synced: boolean;
  is_output: boolean;
  modified_at: number;
}

export async function listWorkspaceFiles(sessionId: string): Promise<WorkspaceFile[]> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/chat/sessions/${sessionId}/files`,
    { headers: { "Content-Type": "application/json" } }
  );
  return handleResponse<WorkspaceFile[]>(res);
}

// ─── Unified Artifacts ──────────────────────────────────────────

export interface Artifact {
  id: string;
  filename: string;
  source: "workspace" | "order_inquiry";
  size: number;
  modified_at: number;
  order_id: number | null;
  supplier_name: string | null;
  product_count: number | null;
}

export async function listArtifacts(sessionId: string): Promise<Artifact[]> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/chat/sessions/${sessionId}/artifacts`,
    { headers: { "Content-Type": "application/json" } }
  );
  return handleResponse<Artifact[]>(res);
}

export function getArtifactDownloadUrl(sessionId: string, artifactId: string): string {
  return `${API_BASE}/api/chat/sessions/${sessionId}/artifacts/download?artifact_id=${encodeURIComponent(artifactId)}`;
}

export type StructuredCard =
  | UploadValidationData | UploadPreviewData | UploadResultData
  | UploadReviewData
  | ConfirmationCardData | QueryTableCardData
  | DataAuditCardData
  | GeneratedFileCardData;

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

// ─── Cancel ─────────────────────────────────────────────────────

export async function cancelChatAgent(
  sessionId: string
): Promise<{ status: string }> {
  const res = await fetchWithAuth(`${API_BASE}/api/chat/sessions/${sessionId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<{ status: string }>(res);
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
  scenario?: string | null,
): Promise<{ status: string; session_id: string; last_msg_id: number }> {
  const url = `${API_BASE}/api/chat/sessions/${sessionId}/message`;

  // Always use FormData (backend now expects Form fields)
  const formData = new FormData();
  formData.append("content", content);
  if (file) {
    formData.append("file", file);
  }
  if (scenario) {
    formData.append("scenario", scenario);
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

// ─── Agent Memory Management ──────────────────────────────────

export interface AgentMemory {
  id: number;
  memory_type: string;
  key: string;
  value: string;
  source_session_id: string | null;
  access_count: number;
  created_at: string;
  updated_at: string;
}

export async function listMemories(): Promise<AgentMemory[]> {
  return fetchWithAuth(`${API_BASE}/chat/memories`);
}

export async function createMemory(data: {
  memory_type: string;
  key: string;
  value: string;
}): Promise<{ id: number; action: string }> {
  return fetchWithAuth(`${API_BASE}/chat/memories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateMemory(
  id: number,
  data: { memory_type?: string; key?: string; value?: string }
): Promise<{ detail: string }> {
  return fetchWithAuth(`${API_BASE}/chat/memories/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteMemory(id: number): Promise<{ detail: string }> {
  return fetchWithAuth(`${API_BASE}/chat/memories/${id}`, {
    method: "DELETE",
  });
}

export async function clearAllMemories(): Promise<{ detail: string }> {
  return fetchWithAuth(`${API_BASE}/chat/memories`, {
    method: "DELETE",
  });
}
