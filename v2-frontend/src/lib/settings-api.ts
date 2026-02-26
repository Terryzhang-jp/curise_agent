import { fetchWithAuth } from "./fetch-with-auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// ─── Types ─────────────────────────────────────────────────────

export interface FieldDefinition {
  id: number;
  schema_id: number;
  field_key: string;
  field_label: string;
  field_type: string;
  is_core: boolean;
  is_required: boolean;
  extraction_hint: string | null;
  sort_order: number;
}

export interface FieldSchema {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  definitions: FieldDefinition[];
}

export interface OrderFormatTemplate {
  id: number;
  name: string;
  file_type: string;
  format_fingerprint: string | null;
  header_row: number;
  data_start_row: number;
  column_mapping: Record<string, string> | null;
  field_schema_id: number | null;
  sample_file_url: string | null;
  layout_prompt: string | null;
  extracted_fields: MetadataField[] | null;
  source_company: string | null;
  match_keywords: string[] | null;
  is_active: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Rich field position info (new format) */
export interface FieldPositionInfo {
  position: string;
  data_type?: string;
  description?: string;
}

/** field_positions value can be a string (legacy) or object (new) */
export type FieldPositionValue = string | FieldPositionInfo;

/** Normalize any field position value to the rich format */
export function normalizeFieldPosition(val: FieldPositionValue): FieldPositionInfo {
  if (typeof val === "string") return { position: val };
  return val;
}

/** Normalize the entire field_positions map */
export function normalizeFieldPositions(
  fp: Record<string, FieldPositionValue> | null | undefined,
): Record<string, FieldPositionInfo> {
  if (!fp) return {};
  const result: Record<string, FieldPositionInfo> = {};
  for (const [k, v] of Object.entries(fp)) {
    result[k] = normalizeFieldPosition(v);
  }
  return result;
}

export interface SupplierTemplate {
  id: number;
  supplier_id: number | null;
  country_id: number | null;
  template_name: string;
  template_file_url: string | null;
  field_positions: Record<string, FieldPositionValue> | null;
  has_product_table: boolean;
  product_table_config: Record<string, unknown> | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ExcelHeader {
  column: string;
  label: string;
}

export interface ExcelSheet {
  name: string;
  headers: ExcelHeader[];
  header_row: number;
  data_start_row: number;
  sample_rows: string[][];
  total_rows: number;
  fingerprint: string;
}

export interface MetadataField {
  key: string;
  label: string;
  value: string;
}

export interface PdfMetadata {
  document_type: string;
  fields: MetadataField[];
}

export interface ExcelParseResult {
  file_type?: string;
  sheets: ExcelSheet[];
  file_url: string;
  metadata?: PdfMetadata;
  layout_prompt?: string;
}

export interface CellPosition {
  position: string;
  value: string;
  row: number;
  col: string;
}

export interface CellSheet {
  name: string;
  cells: CellPosition[];
}

export interface CellParseResult {
  sheets: CellSheet[];
  file_url: string;
}

// ─── Helpers ───────────────────────────────────────────────────

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithAuth(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Field Schemas ─────────────────────────────────────────────

export function listFieldSchemas() {
  return api<FieldSchema[]>("/api/settings/field-schemas");
}

export function getFieldSchema(id: number) {
  return api<FieldSchema>(`/api/settings/field-schemas/${id}`);
}

export function createFieldSchema(data: { name: string; description?: string }) {
  return api<FieldSchema>("/api/settings/field-schemas", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateFieldSchema(id: number, data: { name: string; description?: string }) {
  return api<FieldSchema>(`/api/settings/field-schemas/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteFieldSchema(id: number) {
  return api<{ detail: string }>(`/api/settings/field-schemas/${id}`, { method: "DELETE" });
}

export function seedDefaults() {
  return api<FieldSchema>("/api/settings/field-schemas/seed-defaults", { method: "POST" });
}

// ─── Field Definitions ─────────────────────────────────────────

export function addFieldDefinition(
  schemaId: number,
  data: {
    field_key: string;
    field_label: string;
    field_type?: string;
    is_core?: boolean;
    is_required?: boolean;
    extraction_hint?: string;
    sort_order?: number;
  },
) {
  return api<FieldDefinition>(`/api/settings/field-schemas/${schemaId}/definitions`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateFieldDefinition(
  schemaId: number,
  defId: number,
  data: Partial<{
    field_label: string;
    field_type: string;
    is_required: boolean;
    extraction_hint: string;
    sort_order: number;
  }>,
) {
  return api<FieldDefinition>(`/api/settings/field-schemas/${schemaId}/definitions/${defId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteFieldDefinition(schemaId: number, defId: number) {
  return api<{ detail: string }>(`/api/settings/field-schemas/${schemaId}/definitions/${defId}`, {
    method: "DELETE",
  });
}

// ─── Order Format Templates ───────────────────────────────────

export function listOrderTemplates() {
  return api<OrderFormatTemplate[]>("/api/settings/order-templates");
}

export function createOrderTemplate(data: {
  name: string;
  file_type?: string;
  header_row?: number;
  data_start_row?: number;
  column_mapping?: Record<string, string>;
  field_schema_id?: number;
  format_fingerprint?: string;
  sample_file_url?: string;
  layout_prompt?: string;
  extracted_fields?: MetadataField[];
  source_company?: string;
  match_keywords?: string[];
  is_active?: boolean;
}) {
  return api<OrderFormatTemplate>("/api/settings/order-templates", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateOrderTemplate(
  id: number,
  data: Partial<{
    name: string;
    header_row: number;
    data_start_row: number;
    column_mapping: Record<string, string>;
    field_schema_id: number;
    source_company: string;
    match_keywords: string[];
    is_active: boolean;
  }>,
) {
  return api<OrderFormatTemplate>(`/api/settings/order-templates/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteOrderTemplate(id: number) {
  return api<{ detail: string }>(`/api/settings/order-templates/${id}`, { method: "DELETE" });
}

// ─── Supplier Templates ────────────────────────────────────────

export function listSupplierTemplates(supplierId?: number) {
  const qs = supplierId != null ? `?supplier_id=${supplierId}` : "";
  return api<SupplierTemplate[]>(`/api/settings/supplier-templates${qs}`);
}

export function createSupplierTemplate(data: {
  supplier_id?: number;
  country_id?: number;
  template_name: string;
  template_file_url?: string;
  field_positions?: Record<string, FieldPositionValue>;
  has_product_table?: boolean;
  product_table_config?: Record<string, unknown>;
}) {
  return api<SupplierTemplate>("/api/settings/supplier-templates", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateSupplierTemplate(
  id: number,
  data: Partial<{
    template_name: string;
    template_file_url: string;
    field_positions: Record<string, FieldPositionValue>;
    has_product_table: boolean;
    product_table_config: Record<string, unknown>;
  }>,
) {
  return api<SupplierTemplate>(`/api/settings/supplier-templates/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteSupplierTemplate(id: number) {
  return api<{ detail: string }>(`/api/settings/supplier-templates/${id}`, { method: "DELETE" });
}

// ─── Countries ────────────────────────────────────────────────

export interface Country {
  id: number;
  name: string;
  code: string;
}

export function listCountries() {
  return api<Country[]>("/api/settings/countries");
}

// ─── Excel Upload ──────────────────────────────────────────────

export async function parseExcel(file: File): Promise<ExcelParseResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithAuth(`${API_BASE}/api/excel/parse`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function parseExcelCells(file: File): Promise<CellParseResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithAuth(`${API_BASE}/api/excel/parse-cells`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Tool Config ──────────────────────────────────────────────

export interface ToolConfig {
  id: number;
  tool_name: string;
  group_name: string;
  display_name: string;
  description: string | null;
  is_enabled: boolean;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

export function listTools() {
  return api<ToolConfig[]>("/api/settings/tools");
}

export function updateTool(toolName: string, data: { is_enabled?: boolean; display_name?: string; description?: string }) {
  return api<ToolConfig>(`/api/settings/tools/${toolName}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function seedTools() {
  return api<{ detail: string }>("/api/settings/tools/seed", { method: "POST" });
}

// ─── Skill Config ─────────────────────────────────────────────

export interface SkillConfig {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  content: string | null;
  is_builtin: boolean;
  is_enabled: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export function listSkills() {
  return api<SkillConfig[]>("/api/settings/skills");
}

export function createSkill(data: { name: string; display_name: string; description?: string; content?: string }) {
  return api<SkillConfig>("/api/settings/skills", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getSkill(id: number) {
  return api<SkillConfig>(`/api/settings/skills/${id}`);
}

export function updateSkill(id: number, data: { display_name?: string; description?: string; content?: string; is_enabled?: boolean }) {
  return api<SkillConfig>(`/api/settings/skills/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteSkill(id: number) {
  return api<{ detail: string }>(`/api/settings/skills/${id}`, { method: "DELETE" });
}

export function seedSkills() {
  return api<{ detail: string }>("/api/settings/skills/seed", { method: "POST" });
}

// ─── Template Analysis ────────────────────────────────────────

export interface TemplateAnalysisResult {
  field_positions: Record<string, string>;
  product_table_config: {
    header_row: number;
    start_row: number;
    columns: Record<string, string>;
    formula_columns?: string[];
  };
  notes: string;
  file_url: string;
}

export async function analyzeExcelTemplate(file: File): Promise<TemplateAnalysisResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithAuth(`${API_BASE}/api/settings/supplier-templates/analyze`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "分析失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
