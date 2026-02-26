"use client";

import { useEffect, useState, useCallback } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/empty-state";
import { Loader2, Anchor, Plus, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import {
  listPorts,
  listCountries,
  createPort,
  updatePort,
  deletePort,
  type PortItem,
  type CountryItem,
} from "@/lib/data-api";

function StatusBadge({ status }: { status: boolean | null }) {
  if (status === true || status === null) {
    return (
      <Badge variant="secondary" className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
        有效
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
      无效
    </Badge>
  );
}

export default function PortsTab() {
  const [data, setData] = useState<PortItem[]>([]);
  const [countries, setCountries] = useState<CountryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PortItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", code: "", country_id: "", location: "" });

  const isWriter = (() => {
    const user = getUser();
    return user?.role === "superadmin" || user?.role === "admin";
  })();

  const reload = useCallback(() => {
    listPorts()
      .then(setData)
      .catch((err) => toast.error(err.message));
  }, []);

  useEffect(() => {
    Promise.all([listPorts(), listCountries()])
      .then(([p, c]) => {
        setData(p);
        setCountries(c);
      })
      .catch((err) => toast.error(err.message))
      .finally(() => setLoading(false));
  }, []);

  function openCreate() {
    setEditing(null);
    setForm({ name: "", code: "", country_id: "", location: "" });
    setDialogOpen(true);
  }

  function openEdit(item: PortItem) {
    setEditing(item);
    setForm({
      name: item.name,
      code: item.code || "",
      country_id: item.country_id ? String(item.country_id) : "",
      location: item.location || "",
    });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.name.trim()) {
      toast.error("名称不能为空");
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        code: form.code.trim() || undefined,
        country_id: form.country_id ? Number(form.country_id) : (editing ? null : undefined),
        location: form.location.trim() || undefined,
      };
      if (editing) {
        await updatePort(editing.id, payload);
        toast.success("更新成功");
      } else {
        await createPort(payload as unknown as Parameters<typeof createPort>[0]);
        toast.success("创建成功");
      }
      setDialogOpen(false);
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleStatus(item: PortItem) {
    try {
      await updatePort(item.id, { status: !item.status });
      toast.success(item.status ? "已停用" : "已启用");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDelete(item: PortItem) {
    if (!confirm(`确定要删除港口「${item.name}」吗？`)) return;
    try {
      await deletePort(item.id);
      toast.success("删除成功");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  }

  const columns: ColumnDef<PortItem>[] = [
    {
      accessorKey: "name",
      header: "港口名称",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.name}</span>
      ),
    },
    {
      accessorKey: "code",
      header: "港口代码",
      size: 100,
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground">
          {row.original.code || "-"}
        </span>
      ),
    },
    {
      accessorKey: "country_name",
      header: "所属国家",
      size: 120,
      cell: ({ row }) => row.original.country_name || "-",
    },
    {
      accessorKey: "location",
      header: "位置",
      size: 180,
      cell: ({ row }) => (
        <span className="text-muted-foreground max-w-[180px] truncate block">
          {row.original.location || "-"}
        </span>
      ),
    },
    {
      accessorKey: "status",
      header: "状态",
      size: 70,
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    ...(isWriter
      ? [
          {
            id: "actions",
            header: "操作",
            size: 60,
            cell: ({ row }: { row: { original: PortItem } }) => (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => openEdit(row.original)}>
                    编辑
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleToggleStatus(row.original)}>
                    {row.original.status ? "停用" : "启用"}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-red-600"
                    onClick={() => handleDelete(row.original)}
                  >
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ),
          } as ColumnDef<PortItem>,
        ]
      : []),
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const toolbar = isWriter ? (
    <div className="flex items-center gap-2 flex-1 justify-end">
      <Button size="sm" className="h-8 text-xs" onClick={openCreate}>
        <Plus className="mr-1 h-3 w-3" /> 新增港口
      </Button>
    </div>
  ) : undefined;

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        searchKey="name"
        searchPlaceholder="搜索港口..."
        pageSize={20}
        toolbar={toolbar}
        emptyState={<EmptyState icon={Anchor} title="暂无港口数据" />}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑港口" : "新增港口"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>港口名称 *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="例如：Sydney"
              />
            </div>
            <div className="grid gap-2">
              <Label>港口代码</Label>
              <Input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="例如：SYD"
              />
            </div>
            <div className="grid gap-2">
              <Label>所属国家</Label>
              <Select
                value={form.country_id}
                onValueChange={(v) => setForm({ ...form, country_id: v === "__none__" ? "" : v })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择国家" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">无</SelectItem>
                  {countries.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>位置</Label>
              <Input
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
                placeholder="例如：Darling Harbour"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editing ? "保存" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
