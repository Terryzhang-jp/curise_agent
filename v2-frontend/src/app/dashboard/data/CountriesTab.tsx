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
import { EmptyState } from "@/components/empty-state";
import { Loader2, Globe, Plus, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import {
  listCountries,
  createCountry,
  updateCountry,
  deleteCountry,
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

export default function CountriesTab() {
  const [data, setData] = useState<CountryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<CountryItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", code: "" });

  const isWriter = (() => {
    const user = getUser();
    return user?.role === "superadmin" || user?.role === "admin";
  })();

  const reload = useCallback(() => {
    listCountries()
      .then(setData)
      .catch((err) => toast.error(err.message));
  }, []);

  useEffect(() => {
    listCountries()
      .then(setData)
      .catch((err) => toast.error(err.message))
      .finally(() => setLoading(false));
  }, []);

  function openCreate() {
    setEditing(null);
    setForm({ name: "", code: "" });
    setDialogOpen(true);
  }

  function openEdit(item: CountryItem) {
    setEditing(item);
    setForm({ name: item.name, code: item.code || "" });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.name.trim()) {
      toast.error("名称不能为空");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await updateCountry(editing.id, { name: form.name.trim(), code: form.code.trim() || undefined });
        toast.success("更新成功");
      } else {
        await createCountry({ name: form.name.trim(), code: form.code.trim() || undefined });
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

  async function handleToggleStatus(item: CountryItem) {
    try {
      await updateCountry(item.id, { status: !item.status });
      toast.success(item.status ? "已停用" : "已启用");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDelete(item: CountryItem) {
    if (!confirm(`确定要删除国家「${item.name}」吗？`)) return;
    try {
      await deleteCountry(item.id);
      toast.success("删除成功");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  }

  const columns: ColumnDef<CountryItem>[] = [
    {
      accessorKey: "name",
      header: "国家名称",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.name}</span>
      ),
    },
    {
      accessorKey: "code",
      header: "国家代码",
      size: 100,
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground uppercase">
          {row.original.code || "-"}
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
            cell: ({ row }: { row: { original: CountryItem } }) => (
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
          } as ColumnDef<CountryItem>,
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
        <Plus className="mr-1 h-3 w-3" /> 新增国家
      </Button>
    </div>
  ) : undefined;

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        searchKey="name"
        searchPlaceholder="搜索国家..."
        pageSize={20}
        toolbar={toolbar}
        emptyState={<EmptyState icon={Globe} title="暂无国家数据" />}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑国家" : "新增国家"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>国家名称 *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="例如：Australia"
              />
            </div>
            <div className="grid gap-2">
              <Label>国家代码</Label>
              <Input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="例如：AU"
                maxLength={3}
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
