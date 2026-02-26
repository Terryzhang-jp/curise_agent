import { getToken } from "./auth";
import { fetchWithAuth } from "./fetch-with-auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// ─── Types ─────────────────────────────────────────────────────

export type OrderStatus =
  | "uploading"
  | "extracting"
  | "matching"
  | "ready"
  | "error";

export interface OrderMetadata {
  po_number?: string;
  ship_name?: string;
  delivery_date?: string;
  order_date?: string;
  vendor_name?: string;
  currency?: string;
  destination_port?: string;
  [key: string]: unknown;
}

export interface MatchStatistics {
  total: number;
  matched: number;
  possible_match: number;
  not_matched: number;
  match_rate: number;
}

export interface MatchResult {
  product_code: string;
  product_name: string;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
  match_status: "matched" | "possible_match" | "not_matched";
  match_score: number;
  match_reason: string;
  matched_product?: {
    id: number;
    code: string;
    product_name_en: string;
    product_name_jp: string | null;
    price: number | null;
    currency: string | null;
    supplier_id: number | null;
    category_id: number | null;
    pack_size: string | null;
    unit: string | null;
  };
}

export interface OrderProduct {
  line_number?: number;
  product_code?: string;
  product_name: string;
  quantity: number | null;
  unit?: string;
  unit_price?: number | null;
  total_price?: number | null;
}

export interface AnomalyData {
  total_anomalies: number;
  price_anomalies: Array<{
    type: string;
    product_name: string;
    product_code: string;
    order_value: number;
    db_value: number;
    deviation: number;
    description: string;
  }>;
  quantity_anomalies: Array<{
    type: string;
    product_name: string;
    issue: string;
    value?: number;
    description: string;
  }>;
  completeness_issues: string[];
}

export interface GeneratedFile {
  supplier_id: number;
  filename: string | null;
  file_url?: string;
  product_count: number;
  has_template?: boolean;
  error?: string;
  field_mapping?: Record<string, string> | null;
  template_id?: number | null;
  template_name?: string | null;
  selection_method?: "supplier" | "country" | "single" | "none";
  review_issues?: Array<{
    field: string;
    cell: string;
    issue: string;
    suggestion: string;
  }> | null;
}

export interface InquiryData {
  generated_files: GeneratedFile[];
  supplier_count: number;
  unassigned_count: number;
  agent_summary?: string;
  agent_elapsed_seconds?: number;
  agent_steps?: number;
}

export interface FinancialProductAnalysis {
  product_name: string;
  product_code: string;
  order_price: number;
  supplier_price: number;
  quantity: number;
  revenue: number;
  cost: number;
  profit: number;
  margin: number;
  currency: string;
  supplier_id: number | null;
  category_id: number | null;
}

export interface FinancialBreakdown {
  supplier_id?: number;
  supplier_name?: string;
  category_id?: number;
  category_name?: string;
  revenue: number;
  cost: number;
  profit: number;
  margin: number;
  product_count: number;
}

export interface FinancialWarning {
  type: "currency_mismatch" | "negative_margin" | "missing_price";
  product_name: string;
  product_code?: string;
  description: string;
  order_currency?: string;
  product_currency?: string;
  margin?: number;
  order_price?: number;
  supplier_price?: number;
}

export interface FinancialData {
  summary: {
    total_revenue: number;
    total_cost: number;
    total_profit: number;
    overall_margin: number;
    currency: string;
    analyzed_count: number;
    skipped_unmatched: number;
    skipped_currency_mismatch: number;
    skipped_missing_price: number;
    total_products: number;
  };
  product_analyses: FinancialProductAnalysis[];
  supplier_breakdown: FinancialBreakdown[];
  category_breakdown: FinancialBreakdown[];
  warnings: FinancialWarning[];
}

export interface DeliveryItem {
  product_name: string;
  product_code?: string;
  ordered_qty: number;
  accepted_qty: number;
  rejected_qty: number;
  rejection_reason?: string;
  notes?: string;
}

export interface DeliveryData {
  delivered_at?: string;
  received_by?: string;
  items: DeliveryItem[];
  total_accepted: number;
  total_rejected: number;
  summary: string;
}

export interface OrderAttachment {
  filename: string;
  original_name: string;
  uploaded_at: string;
  description?: string;
}

export type FulfillmentStatus =
  | "pending"
  | "inquiry_sent"
  | "quoted"
  | "confirmed"
  | "delivering"
  | "delivered"
  | "invoiced"
  | "paid";

export interface TideEntry {
  time: string;
  type: "HIGH" | "LOW";
  height_m: number;
}

export interface WaveEntry {
  time: string;
  wave_height_m: number;
}

export interface MarineData {
  max_wave_height_m: number | null;
  max_wave_period_s: number | null;
  hourly_waves: WaveEntry[];
}

export interface DeliveryWeather {
  condition: string;
  temp_c: number | null;
  max_temp_c: number | null;
  min_temp_c: number | null;
  max_wind_kph: number | null;
  max_wind_gusts_kph?: number | null;
  total_precip_mm: number | null;
  avg_vis_km: number | null;
  avg_humidity: number | null;
  uv: number | null;
}

export interface DeliveryEnvironment {
  location: string;
  date: string;
  coordinates?: { lat: number; lon: number };
  tides: TideEntry[];
  weather: DeliveryWeather;
  marine?: MarineData;
  ai_summary: string;
  forecast_available?: boolean;
  days_until_available?: number;
  fetched_at: string;
  source: string;
}

export interface Order {
  id: number;
  user_id?: number;
  filename: string;
  file_url: string | null;
  file_type: string;
  status: OrderStatus;
  processing_error: string | null;
  country_id: number | null;
  port_id: number | null;
  delivery_date: string | null;
  extraction_data: Record<string, unknown> | null;
  order_metadata: OrderMetadata | null;
  products: OrderProduct[] | null;
  product_count: number;
  total_amount: number | null;
  match_results: MatchResult[] | null;
  match_statistics: MatchStatistics | null;
  anomaly_data: AnomalyData | null;
  financial_data: FinancialData | null;
  inquiry_data: InquiryData | null;
  has_inquiry: boolean;
  is_reviewed: boolean;
  reviewed_at: string | null;
  reviewed_by: number | null;
  review_notes: string | null;
  fulfillment_status: FulfillmentStatus;
  delivery_data: DeliveryData | null;
  delivery_environment: DeliveryEnvironment | null;
  invoice_number: string | null;
  invoice_amount: number | null;
  invoice_date: string | null;
  payment_amount: number | null;
  payment_date: string | null;
  payment_reference: string | null;
  attachments: OrderAttachment[];
  fulfillment_notes: string | null;
  template_id: number | null;
  template_match_method: string | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
}

// List item is the same shape, just without large fields (backend handles this)
export type OrderListItem = Order;

// ─── Helpers ───────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Orders API ──────────────────────────────────────────────

export async function uploadOrder(file: File): Promise<Order> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithAuth(`${API_BASE}/api/orders/upload`, {
    method: "POST",
    body: form,
  });
  return handleResponse<Order>(res);
}

export interface PaginatedOrders {
  total: number;
  items: OrderListItem[];
}

export async function listOrders(params?: {
  status?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<PaginatedOrders> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.search) qs.set("search", params.search);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));

  const res = await fetchWithAuth(`${API_BASE}/api/orders?${qs.toString()}`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<PaginatedOrders>(res);
}

export async function getOrder(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<Order>(res);
}

export async function deleteOrder(orderId: number): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "删除失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

export async function reviewOrder(
  orderId: number,
  notes?: string
): Promise<{ detail: string; reviewed_at: string }> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notes: notes || null }),
  });
  return handleResponse(res);
}

export async function updateOrder(
  orderId: number,
  payload: {
    order_metadata?: Record<string, unknown>;
    products?: OrderProduct[];
  }
): Promise<Order> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<Order>(res);
}

export async function rematchOrder(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}/rematch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<Order>(res);
}

export async function reprocessOrder(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}/reprocess`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<Order>(res);
}

export async function runAnomalyCheck(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}/anomaly-check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<Order>(res);
}

export async function runFinancialAnalysis(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/orders/${orderId}/financial-analysis`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  return handleResponse<Order>(res);
}

export async function fetchDeliveryEnvironment(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/orders/${orderId}/delivery-environment`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  return handleResponse<Order>(res);
}

export async function generateInquiry(orderId: number): Promise<Order> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/orders/${orderId}/generate-inquiry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  return handleResponse<Order>(res);
}

// ─── Streaming Inquiry API ──────────────────────────────────

export interface InquiryStep {
  type: "tool_call" | "tool_result" | "thinking";
  tool_name?: string;
  tool_label?: string;
  content: string;
  step_index: number;
  elapsed_seconds: number;
  duration_ms?: number;
}

export async function startGenerateInquiry(
  orderId: number
): Promise<{ status: string; stream_key: string }> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/orders/${orderId}/generate-inquiry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  return handleResponse<{ status: string; stream_key: string }>(res);
}

export function streamInquiryProgress(
  orderId: number,
  onStep: (step: InquiryStep) => void,
  onDone: (data: InquiryData) => void,
  onError: (err: Error) => void
): () => void {
  const controller = new AbortController();
  const token = getToken();

  (async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/orders/${orderId}/inquiry-stream`,
        {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        }
      );

      if (!res.ok || !res.body) {
        onError(new Error(`HTTP ${res.status}`));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);
            if (event.type === "done") {
              onDone(event.data || {});
              return;
            } else if (event.type === "error") {
              onError(new Error(event.message || "生成失败"));
              return;
            } else {
              onStep(event as InquiryStep);
            }
          } catch {
            // skip malformed JSON
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onError(err instanceof Error ? err : new Error("Stream failed"));
      }
    }
  })();

  return () => controller.abort();
}

export async function getOrderFiles(
  orderId: number
): Promise<GeneratedFile[]> {
  const res = await fetchWithAuth(`${API_BASE}/api/orders/${orderId}/files`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<GeneratedFile[]>(res);
}

export async function downloadOrderFile(
  orderId: number,
  filename: string
): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE}/api/orders/${orderId}/files/${filename}/download`,
    { method: "POST" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "下载失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** @deprecated Use downloadOrderFile() instead — this exposes token in URL */
export function getOrderFileDownloadUrl(
  orderId: number,
  filename: string
): string {
  const token = getToken();
  return `${API_BASE}/api/orders/${orderId}/files/${filename}?token=${token}`;
}
