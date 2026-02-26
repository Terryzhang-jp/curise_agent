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
import { Loader2, Truck, Plus, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import {
  listSuppliers,
  listCountries,
  listCategories,
  createSupplier,
  updateSupplier,
  deleteSupplier,
  type SupplierItem,
  type CountryItem,
  type CategoryItem,
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

export default function SuppliersTab() {
  const [data, setData] = useState<SupplierItem[]>([]);
  const [countries, setCountries] = useState<CountryItem[]>([]);
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SupplierItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "", country_id: "", contact: "", email: "", phone: "",
    category_ids: [] as number[],
  });

  const isWriter = (() => {
    const user = getUser();
    return user?.role === "superadmin" || user?.role === "admin";
  })();

  const reload = useCallback(() => {
    listSuppliers()
      .then(setData)
      .catch((err) => toast.error(err.message));
  }, []);

  useEffect(() => {
    Promise.all([listSuppliers(), listCountries(), listCategories()])
      .then(([s, c, cat]) => {
        setData(s);
        setCountries(c);
        setCategories(cat);
      })
      .catch((err) => toast.error(err.message))
      .finally(() => setLoading(false));
  }, []);

  function openCreate() {
    setEditing(null);
    setForm({ name: "", country_id: "", contact: "", email: "", phone: "", category_ids: [] });
    setDialogOpen(true);
  }

  function openEdit(item: SupplierItem) {
    setEditing(item);
    setForm({
      name: item.name,
      country_id: item.country_id ? String(item.country_id) : "",
      contact: item.contact || "",
      email: item.email || "",
      phone: item.phone || "",
      category_ids: item.category_ids || [],
    });
    setDialogOpen(true);
  }

  function toggleCategory(catId: number) {
    setForm((prev) => ({
      ...prev,
      category_ids: prev.category_ids.includes(catId)
        ? prev.category_ids.filter((id) => id !== catId)
        : [...prev.category_ids, catId],
    }));
  }

  async function handleSave() {
    if (!form.name.trim()) {
      toast.error("名称不能为空");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        country_id: form.country_id ? Number(form.country_id) : (editing ? null : undefined),
        contact: form.contact.trim() || undefined,
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
        category_ids: form.category_ids,
      };
      if (editing) {
        await updateSupplier(editing.id, payload);
        toast.success("更新成功");
      } else {
        await createSupplier(payload);
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

  async function handleToggleStatus(item: SupplierItem) {
    try {
      await updateSupplier(item.id, { status: !item.status });
      toast.success(item.status ? "已停用" : "已启用");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function handleDelete(item: SupplierItem) {
    if (!confirm(`确定要删除供应商「${item.name}」吗？`)) return;
    try {
      await deleteSupplier(item.id);
      toast.success("删除成功");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  }

  const columns: ColumnDef<SupplierItem>[] = [
    {
      accessorKey: "name",
      header: "供应商名称",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.name}</span>
      ),
    },
    {
      accessorKey: "country_name",
      header: "国家",
      size: 100,
      cell: ({ row }) => row.original.country_name || "-",
    },
    {
      accessorKey: "contact",
      header: "联系人",
      size: 100,
      cell: ({ row }) => row.original.contact || "-",
    },
    {
      accessorKey: "email",
      header: "邮箱",
      size: 180,
      cell: ({ row }) => (
        <span className="text-muted-foreground">
          {row.original.email || "-"}
        </span>
      ),
    },
    {
      accessorKey: "categories",
      header: "经营类别",
      size: 200,
      cell: ({ row }) => {
        const cats = row.original.categories;
        if (!cats.length) return "-";
        return (
          <div className="flex flex-wrap gap-1">
            {cats.slice(0, 3).map((c) => (
              <Badge key={c} variant="outline" className="text-[10px]">{c}</Badge>
            ))}
            {cats.length > 3 && (
              <Badge variant="secondary" className="text-[10px]">+{cats.length - 3}</Badge>
            )}
          </div>
        );
      },
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
            cell: ({ row }: { row: { original: SupplierItem } }) => (
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
          } as ColumnDef<SupplierItem>,
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
        <Plus className="mr-1 h-3 w-3" /> 新增供应商
      </Button>
    </div>
  ) : undefined;

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        searchKey="name"
        searchPlaceholder="搜索供应商..."
        pageSize={20}
        toolbar={toolbar}
        emptyState={<EmptyState icon={Truck} title="暂无供应商数据" />}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑供应商" : "新增供应商"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>供应商名称 *</Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="供应商名称"
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
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="grid gap-2">
                <Label>联系人</Label>
                <Input
                  value={form.contact}
                  onChange={(e) => setForm({ ...form, contact: e.target.value })}
                />
              </div>
              <div className="grid gap-2">
                <Label>邮箱</Label>
                <Input
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  type="email"
                />
              </div>
              <div className="grid gap-2">
                <Label>电话</Label>
                <Input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>经营类别</Label>
              <div className="flex flex-wrap gap-2 p-3 border rounded-md min-h-[40px]">
                {categories.map((cat) => {
                  const selected = form.category_ids.includes(cat.id);
                  return (
                    <Badge
                      key={cat.id}
                      variant={selected ? "default" : "outline"}
                      className={`cursor-pointer transition-colors ${
                        selected ? "" : "opacity-60 hover:opacity-100"
                      }`}
                      onClick={() => toggleCategory(cat.id)}
                    >
                      {cat.name}
                    </Badge>
                  );
                })}
                {categories.length === 0 && (
                  <span className="text-xs text-muted-foreground">暂无类别数据</span>
                )}
              </div>
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
