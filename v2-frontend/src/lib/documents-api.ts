import { fetchWithAuth } from "./fetch-with-auth";
import type { Order } from "./orders-api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export type DocumentStatus = "uploaded" | "extracting" | "extracted" | "error";

export interface DocumentSummary {
  id: number;
  user_id: number;
  filename: string;
  file_url: string | null;
  file_type: string;
  file_size_bytes: number | null;
  doc_type: string | null;
  extraction_method: string | null;
  status: DocumentStatus;
  processing_error: string | null;
  product_count: number;
  linked_order_id: number | null;
  preview_url: string | null;
  preview_text: string | null;
  created_at: string | null;
  updated_at: string | null;
  extracted_at: string | null;
}

// ─── Universal block schema (Stage 1 v1.0) ────────────────────────────
// Mirrors v2-backend/services/extraction/schema.py. Any block must have a
// `type`. Block-specific fields are optional and depend on the type.

export type ExtractionBlockType =
  | "heading"
  | "paragraph"
  | "field_group"
  | "table"
  | "list"
  | "signature_block"
  | "other";

export interface ExtractionField {
  label?: string | null;
  value?: string | null;
}

export interface ExtractionBlock {
  type: ExtractionBlockType;
  // heading / paragraph / other
  text?: string;
  level?: number;
  section?: "header" | "body" | "footer" | "unknown";
  // field_group / signature_block
  fields?: ExtractionField[];
  labels?: string[];
  values?: Array<string | null>;
  // table
  caption?: string | null;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  // list
  style?: "bullet" | "numbered";
  items?: string[];
  // common
  page?: number | number[];
}

export interface DocumentDetail extends DocumentSummary {
  content_markdown: string | null;
  extracted_data: {
    metadata?: Record<string, unknown>;
    products?: Array<Record<string, unknown>>;
    tables?: Array<Record<string, unknown>>;
    field_evidence?: Record<string, unknown>;
    raw_extraction?: Record<string, unknown>;
    // Stage 1 v1.0 fields (only present on documents extracted with the
    // new universal extractor — older records won't have these)
    extraction_schema_version?: string;
    blocks?: ExtractionBlock[];
    title?: string | null;
    language?: string | null;
    page_count?: number | null;
    projection?: {
      purchase_order?: {
        confidence?: Record<string, unknown>;
      };
    };
  } | null;
}

export interface OrderPayload {
  document_id: number;
  doc_type: string | null;
  order_metadata: Record<string, unknown>;
  products: Array<Record<string, unknown>>;
  product_count: number;
  missing_fields: string[];
  blocking_missing_fields: string[];
  field_evidence: Record<string, unknown>;
  confidence_summary: Record<string, unknown>;
  ready_for_order_creation: boolean;
}

export interface PaginatedDocuments {
  total: number;
  items: DocumentSummary[];
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithAuth(`${API_BASE}/api/documents/upload`, {
    method: "POST",
    body: form,
    timeout: 120000,
  } as RequestInit & { timeout?: number });
  return handleResponse<DocumentSummary>(res);
}

export async function listDocuments(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<PaginatedDocuments> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  const res = await fetchWithAuth(`${API_BASE}/api/documents${query ? `?${query}` : ""}`);
  return handleResponse<PaginatedDocuments>(res);
}

export async function getDocument(documentId: number): Promise<DocumentDetail> {
  const res = await fetchWithAuth(`${API_BASE}/api/documents/${documentId}`);
  return handleResponse<DocumentDetail>(res);
}

export async function getDocumentOrderPayload(documentId: number): Promise<OrderPayload> {
  const res = await fetchWithAuth(`${API_BASE}/api/documents/${documentId}/order-payload`);
  return handleResponse<OrderPayload>(res);
}

export async function createOrderFromDocument(documentId: number, force = false): Promise<Order> {
  const res = await fetchWithAuth(`${API_BASE}/api/documents/${documentId}/create-order`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force }),
  });
  return handleResponse<Order>(res);
}

export interface DeleteDocumentResult {
  ok: boolean;
  document_id: number;
  unlinked_order_id: number | null;
}

export type SupportedDocType = "purchase_order" | "unknown";

export async function updateDocumentType(
  documentId: number,
  docType: SupportedDocType,
): Promise<DocumentDetail> {
  const res = await fetchWithAuth(`${API_BASE}/api/documents/${documentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_type: docType }),
  });
  return handleResponse<DocumentDetail>(res);
}

export async function deleteDocument(
  documentId: number,
  force = false,
): Promise<DeleteDocumentResult> {
  const url = new URL(`${API_BASE}/api/documents/${documentId}`);
  if (force) url.searchParams.set("force", "true");
  const res = await fetchWithAuth(url.toString(), { method: "DELETE" });
  return handleResponse<DeleteDocumentResult>(res);
}
