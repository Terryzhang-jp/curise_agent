import { fetchWithAuth } from "./fetch-with-auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// ─── Types ─────────────────────────────────────────────────────

export interface UserItem {
  id: number;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  is_default_password: boolean;
  last_login: string | null;
  created_at: string | null;
}

// ─── Helpers ───────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── API ───────────────────────────────────────────────────────

export async function listUsers(): Promise<UserItem[]> {
  const res = await fetchWithAuth(`${API_BASE}/api/users`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<UserItem[]>(res);
}

export async function createUser(data: {
  email: string;
  full_name: string;
  role: string;
  password: string;
}): Promise<UserItem> {
  const res = await fetchWithAuth(`${API_BASE}/api/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<UserItem>(res);
}

export async function updateUser(
  userId: number,
  data: { full_name?: string; role?: string; is_active?: boolean },
): Promise<UserItem> {
  const res = await fetchWithAuth(`${API_BASE}/api/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<UserItem>(res);
}

export async function deleteUser(userId: number): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/api/users/${userId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "操作失败" }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

export async function resetPassword(
  userId: number,
): Promise<{ detail: string }> {
  const res = await fetchWithAuth(`${API_BASE}/api/users/${userId}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<{ detail: string }>(res);
}
