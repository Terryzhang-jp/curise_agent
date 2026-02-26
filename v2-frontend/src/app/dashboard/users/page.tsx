"use client";

import { useEffect, useState } from "react";
import { listUsers, createUser, updateUser, deleteUser, resetPassword, type UserItem } from "@/lib/users-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { Loader2, Plus, MoreHorizontal, KeyRound, UserX, UserCheck, Pencil } from "lucide-react";

const ROLES = [
  { value: "superadmin", label: "超级管理员" },
  { value: "admin", label: "管理员" },
  { value: "finance", label: "财务" },
  { value: "employee", label: "员工" },
];

function roleBadge(role: string) {
  const colors: Record<string, string> = {
    superadmin: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
    admin: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
    finance: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
    employee: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
  };
  const label = ROLES.find((r) => r.value === role)?.label || role;
  return (
    <Badge variant="secondary" className={colors[role] || ""}>
      {label}
    </Badge>
  );
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return "-";
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function UsersPage() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);

  // Create form
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("employee");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createSubmitAttempted, setCreateSubmitAttempted] = useState(false);

  // Edit form
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("");

  const fetchUsers = async () => {
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载用户列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const createErrors = createSubmitAttempted
    ? {
        email: !email.trim()
          ? "请输入邮箱"
          : !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
          ? "请输入有效的邮箱格式"
          : "",
        fullName: !fullName.trim() ? "请输入姓名" : "",
        password: !password
          ? "请输入密码"
          : password.length < 8
          ? "密码长度至少 8 个字符"
          : "",
      }
    : { email: "", fullName: "", password: "" };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateSubmitAttempted(true);
    if (
      !email.trim() ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
      !fullName.trim() ||
      !password ||
      password.length < 8
    ) {
      return;
    }
    setSubmitting(true);
    try {
      await createUser({ email, full_name: fullName, role, password });
      toast.success("用户创建成功");
      setShowCreate(false);
      setEmail("");
      setFullName("");
      setRole("employee");
      setPassword("");
      setCreateSubmitAttempted(false);
      fetchUsers();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingUser) return;
    setSubmitting(true);
    try {
      await updateUser(editingUser.id, { full_name: editName, role: editRole });
      toast.success("用户信息已更新");
      setShowEdit(false);
      setEditingUser(null);
      fetchUsers();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "更新失败");
    } finally {
      setSubmitting(false);
    }
  };

  const openEdit = (user: UserItem) => {
    setEditingUser(user);
    setEditName(user.full_name || "");
    setEditRole(user.role);
    setShowEdit(true);
  };

  const handleResetPassword = async (user: UserItem) => {
    try {
      const res = await resetPassword(user.id);
      toast.success(res.detail);
      fetchUsers();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "重置失败");
    }
  };

  const handleToggleActive = async (user: UserItem) => {
    try {
      if (user.is_active) {
        await deleteUser(user.id);
        toast.success("用户已停用");
      } else {
        await updateUser(user.id, { is_active: true });
        toast.success("用户已启用");
      }
      fetchUsers();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  };

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">用户管理</h1>
            <p className="text-sm text-muted-foreground">
              管理系统用户账号和权限
            </p>
          </div>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4 mr-1" />
            新建用户
          </Button>
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/50 text-muted-foreground text-left">
                  <th className="px-4 py-3 font-medium">邮箱</th>
                  <th className="px-4 py-3 font-medium">姓名</th>
                  <th className="px-4 py-3 font-medium">角色</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">上次登录</th>
                  <th className="px-4 py-3 font-medium">创建时间</th>
                  <th className="px-4 py-3 font-medium w-12"></th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {users.map((user) => (
                  <tr key={user.id} className="hover:bg-muted/30">
                    <td className="px-4 py-3">{user.email}</td>
                    <td className="px-4 py-3">{user.full_name || "-"}</td>
                    <td className="px-4 py-3">{roleBadge(user.role)}</td>
                    <td className="px-4 py-3">
                      {user.is_active ? (
                        <Badge variant="secondary" className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
                          活跃
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
                          停用
                        </Badge>
                      )}
                      {user.is_default_password && (
                        <Badge variant="outline" className="ml-1 text-orange-600 border-orange-300">
                          默认密码
                        </Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {formatDate(user.last_login)}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {formatDate(user.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-8 w-8">
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => openEdit(user)}>
                            <Pencil className="mr-2 h-3.5 w-3.5" />
                            编辑
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => handleResetPassword(user)}>
                            <KeyRound className="mr-2 h-3.5 w-3.5" />
                            重置密码
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => handleToggleActive(user)}>
                            {user.is_active ? (
                              <>
                                <UserX className="mr-2 h-3.5 w-3.5" />
                                停用
                              </>
                            ) : (
                              <>
                                <UserCheck className="mr-2 h-3.5 w-3.5" />
                                启用
                              </>
                            )}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create User Dialog */}
      <Dialog open={showCreate} onOpenChange={(open) => { setShowCreate(open); if (!open) setCreateSubmitAttempted(false); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新建用户</DialogTitle>
            <DialogDescription>
              创建后用户将使用默认密码登录，首次登录时系统会要求修改密码。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label>邮箱</Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@company.com"
                aria-invalid={createErrors.email ? true : undefined}
              />
              {createErrors.email && <p className="text-xs text-destructive">{createErrors.email}</p>}
            </div>
            <div className="space-y-2">
              <Label>姓名</Label>
              <Input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="用户姓名"
                aria-invalid={createErrors.fullName ? true : undefined}
              />
              {createErrors.fullName && <p className="text-xs text-destructive">{createErrors.fullName}</p>}
            </div>
            <div className="space-y-2">
              <Label>角色</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>初始密码</Label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="至少 8 个字符"
                aria-invalid={createErrors.password ? true : undefined}
              />
              {createErrors.password && <p className="text-xs text-destructive">{createErrors.password}</p>}
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              创建用户
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit User Dialog */}
      <Dialog open={showEdit} onOpenChange={setShowEdit}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>编辑用户</DialogTitle>
            <DialogDescription>
              修改用户 {editingUser?.email} 的信息
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEdit} className="space-y-4">
            <div className="space-y-2">
              <Label>姓名</Label>
              <Input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="用户姓名"
                required
              />
            </div>
            <div className="space-y-2">
              <Label>角色</Label>
              <Select value={editRole} onValueChange={setEditRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              保存
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
