import { fetchWithAuth } from "./fetch-with-auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// ─── Types ─────────────────────────────────────────────────────

export interface ProductItem {
  id: number;
  product_name_en: string | null;
  product_name_jp: string | null;
  code: string | null;
  unit: string | null;
  price: number | null;
  unit_size: string | null;
  pack_size: string | null;
  country_of_origin: string | null;
  brand: string | null;
  currency: string | null;
  status: boolean | null;
  country_name: string | null;
  category_name: string | null;
  supplier_name: string | null;
  port_name: string | null;
  country_id: number | null;
  category_id: number | null;
  supplier_id: number | null;
  port_id: number | null;
  effective_from: string | null;
  effective_to: string | null;
}

export interface SupplierItem {
  id: number;
  name: string;
  contact: string | null;
  email: string | null;
  phone: string | null;
  status: boolean | null;
  country_name: string | null;
  country_id: number | null;
  categories: string[];
  category_ids: number[];
}

export interface CountryItem {
  id: number;
  name: string;
  code: string | null;
  status: boolean | null;
}

export interface PortItem {
  id: number;
  name: string;
  code: string | null;
  location: string | null;
  status: boolean | null;
  country_name: string | null;
  country_id: number | null;
}

export interface CategoryItem {
  id: number;
  name: string;
  code: string | null;
  description: string | null;
  status: boolean | null;
}

// ─── Helpers ───────────────────────────────────────────────────

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetchWithAuth(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiVoid(path: string, options?: RequestInit): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

function jsonBody(data: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
}

function patchBody(data: unknown): RequestInit {
  return {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
}

// ─── Paginated Response ──────────────────────────────────────

export interface PaginatedResponse<T> {
  total: number;
  items: T[];
}

// ─── List API Functions ───────────────────────────────────────

export function listProducts(params?: {
  search?: string;
  country_id?: number;
  category_id?: number;
  supplier_id?: number;
  limit?: number;
  offset?: number;
}): Promise<PaginatedResponse<ProductItem>> {
  const qs = new URLSearchParams();
  if (params?.search) qs.set("search", params.search);
  if (params?.country_id) qs.set("country_id", String(params.country_id));
  if (params?.category_id) qs.set("category_id", String(params.category_id));
  if (params?.supplier_id) qs.set("supplier_id", String(params.supplier_id));
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return api<PaginatedResponse<ProductItem>>(`/api/data/products${query ? `?${query}` : ""}`);
}

export function listSuppliers() {
  return api<SupplierItem[]>("/api/data/suppliers");
}

export function listCountries() {
  return api<CountryItem[]>("/api/data/countries");
}

export function listPorts() {
  return api<PortItem[]>("/api/data/ports");
}

export function listCategories() {
  return api<CategoryItem[]>("/api/data/categories");
}

// ─── Country CRUD ─────────────────────────────────────────────

export function createCountry(data: { name: string; code?: string; status?: boolean }) {
  return api<CountryItem>("/api/data/countries", jsonBody(data));
}

export function updateCountry(id: number, data: Partial<{ name: string; code: string; status: boolean }>) {
  return api<CountryItem>(`/api/data/countries/${id}`, patchBody(data));
}

export function deleteCountry(id: number) {
  return apiVoid(`/api/data/countries/${id}`, { method: "DELETE" });
}

// ─── Category CRUD ────────────────────────────────────────────

export function createCategory(data: { name: string; code?: string; description?: string; status?: boolean }) {
  return api<CategoryItem>("/api/data/categories", jsonBody(data));
}

export function updateCategory(id: number, data: Partial<{ name: string; code: string; description: string; status: boolean }>) {
  return api<CategoryItem>(`/api/data/categories/${id}`, patchBody(data));
}

export function deleteCategory(id: number) {
  return apiVoid(`/api/data/categories/${id}`, { method: "DELETE" });
}

// ─── Port CRUD ────────────────────────────────────────────────

export function createPort(data: { name: string; code?: string; country_id?: number | null; location?: string; status?: boolean }) {
  return api<PortItem>("/api/data/ports", jsonBody(data));
}

export function updatePort(id: number, data: Partial<{ name: string; code: string; country_id: number | null; location: string; status: boolean }>) {
  return api<PortItem>(`/api/data/ports/${id}`, patchBody(data));
}

export function deletePort(id: number) {
  return apiVoid(`/api/data/ports/${id}`, { method: "DELETE" });
}

// ─── Supplier CRUD ────────────────────────────────────────────

export function createSupplier(data: { name: string; country_id?: number | null; contact?: string; email?: string; phone?: string; category_ids?: number[]; status?: boolean }) {
  return api<SupplierItem>("/api/data/suppliers", jsonBody(data));
}

export function updateSupplier(id: number, data: Partial<{ name: string; country_id: number | null; contact: string; email: string; phone: string; category_ids: number[]; status: boolean }>) {
  return api<SupplierItem>(`/api/data/suppliers/${id}`, patchBody(data));
}

export function deleteSupplier(id: number) {
  return apiVoid(`/api/data/suppliers/${id}`, { method: "DELETE" });
}

// ─── Product CRUD ─────────────────────────────────────────────

export interface ProductCreateData {
  product_name_en: string;
  product_name_jp?: string | null;
  code?: string | null;
  country_id?: number | null;
  category_id?: number | null;
  supplier_id?: number | null;
  port_id?: number | null;
  unit?: string | null;
  price?: number | null;
  unit_size?: string | null;
  pack_size?: string | null;
  country_of_origin?: string | null;
  brand?: string | null;
  currency?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  status?: boolean;
}

export function createProduct(data: ProductCreateData) {
  return api<ProductItem>("/api/data/products", jsonBody(data));
}

export function updateProduct(id: number, data: Partial<ProductCreateData>) {
  return api<ProductItem>(`/api/data/products/${id}`, patchBody(data));
}

export function deleteProduct(id: number) {
  return apiVoid(`/api/data/products/${id}`, { method: "DELETE" });
}

// ─── Exchange Rate CRUD ──────────────────────────────────────

export interface ExchangeRateItem {
  id: number;
  from_currency: string;
  to_currency: string;
  rate: number;
  effective_date: string;
  source: string;
  created_at?: string;
  updated_at?: string;
}

export function listExchangeRates(params?: {
  from_currency?: string;
  to_currency?: string;
}): Promise<ExchangeRateItem[]> {
  const qs = new URLSearchParams();
  if (params?.from_currency) qs.set("from_currency", params.from_currency);
  if (params?.to_currency) qs.set("to_currency", params.to_currency);
  const query = qs.toString();
  return api<ExchangeRateItem[]>(`/api/data/exchange-rates${query ? `?${query}` : ""}`);
}

export function createExchangeRate(data: {
  from_currency: string;
  to_currency: string;
  rate: number;
  effective_date: string;
}) {
  return api<ExchangeRateItem>("/api/data/exchange-rates", jsonBody(data));
}

export function updateExchangeRate(id: number, data: Partial<{ rate: number; effective_date: string }>) {
  return api<ExchangeRateItem>(`/api/data/exchange-rates/${id}`, patchBody(data));
}

export function deleteExchangeRate(id: number) {
  return apiVoid(`/api/data/exchange-rates/${id}`, { method: "DELETE" });
}

export function fetchExchangeRates(baseCurrency: string = "USD", targetCurrencies?: string[]) {
  return api<{ created: number; updated: number; base: string; date: string }>(
    "/api/data/exchange-rates/fetch",
    jsonBody({ base_currency: baseCurrency, target_currencies: targetCurrencies || [] }),
  );
}
