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
import { Loader2, ArrowRightLeft, Plus, MoreHorizontal, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import {
  listExchangeRates,
  createExchangeRate,
  updateExchangeRate,
  deleteExchangeRate,
  fetchExchangeRates,
  type ExchangeRateItem,
} from "@/lib/data-api";

export default function ExchangeRatesTab() {
  const [data, setData] = useState<ExchangeRateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ExchangeRateItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [form, setForm] = useState({
    from_currency: "",
    to_currency: "",
    rate: "",
    effective_date: new Date().toISOString().slice(0, 10),
  });

  const isWriter = (() => {
    const user = getUser();
    return user?.role === "superadmin" || user?.role === "admin";
  })();

  const reload = useCallback(() => {
    listExchangeRates()
      .then(setData)
      .catch((err) => toast.error(err.message));
  }, []);

  useEffect(() => {
    listExchangeRates()
      .then(setData)
      .catch((err) => toast.error(err.message))
      .finally(() => setLoading(false));
  }, []);

  function openCreate() {
    setEditing(null);
    setForm({
      from_currency: "",
      to_currency: "",
      rate: "",
      effective_date: new Date().toISOString().slice(0, 10),
    });
    setDialogOpen(true);
  }

  function openEdit(item: ExchangeRateItem) {
    setEditing(item);
    setForm({
      from_currency: item.from_currency,
      to_currency: item.to_currency,
      rate: String(item.rate),
      effective_date: item.effective_date,
    });
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.from_currency.trim() || !form.to_currency.trim()) {
      toast.error("请填写源币种和目标币种");
      return;
    }
    const rateNum = parseFloat(form.rate);
    if (isNaN(rateNum) || rateNum <= 0) {
      toast.error("汇率必须大于 0");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await updateExchangeRate(editing.id, {
          rate: rateNum,
          effective_date: form.effective_date,
        });
        toast.success("更新成功");
      } else {
        await createExchangeRate({
          from_currency: form.from_currency.trim().toUpperCase(),
          to_currency: form.to_currency.trim().toUpperCase(),
          rate: rateNum,
          effective_date: form.effective_date,
        });
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

  async function handleDelete(item: ExchangeRateItem) {
    if (!confirm(`确定要删除 ${item.from_currency}→${item.to_currency} (${item.effective_date}) 汇率记录吗？`)) return;
    try {
      await deleteExchangeRate(item.id);
      toast.success("删除成功");
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleFetchRates() {
    setFetching(true);
    try {
      const result = await fetchExchangeRates("USD");
      toast.success(`获取完成：新增 ${result.created} 条，更新 ${result.updated} 条`);
      reload();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "获取汇率失败");
    } finally {
      setFetching(false);
    }
  }

  const columns: ColumnDef<ExchangeRateItem>[] = [
    {
      accessorKey: "from_currency",
      header: "源币种",
      size: 80,
      cell: ({ row }) => (
        <span className="font-mono font-medium">{row.original.from_currency}</span>
      ),
    },
    {
      accessorKey: "to_currency",
      header: "目标币种",
      size: 80,
      cell: ({ row }) => (
        <span className="font-mono font-medium">{row.original.to_currency}</span>
      ),
    },
    {
      accessorKey: "rate",
      header: "汇率",
      size: 120,
      cell: ({ row }) => (
        <span className="font-mono">
          {row.original.rate.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 8 })}
        </span>
      ),
    },
    {
      accessorKey: "effective_date",
      header: "生效日期",
      size: 110,
      cell: ({ row }) => (
        <span className="text-muted-foreground">{row.original.effective_date}</span>
      ),
    },
    {
      accessorKey: "source",
      header: "来源",
      size: 70,
      cell: ({ row }) => (
        <Badge variant="secondary" className={
          row.original.source === "api"
            ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
            : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
        }>
          {row.original.source === "api" ? "API" : "手动"}
        </Badge>
      ),
    },
    ...(isWriter
      ? [
          {
            id: "actions",
            header: "操作",
            size: 60,
            cell: ({ row }: { row: { original: ExchangeRateItem } }) => (
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
                  <DropdownMenuItem
                    className="text-red-600"
                    onClick={() => handleDelete(row.original)}
                  >
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ),
          } as ColumnDef<ExchangeRateItem>,
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
      <Button
        variant="outline"
        size="sm"
        className="h-8 text-xs"
        onClick={handleFetchRates}
        disabled={fetching}
      >
        {fetching ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
        获取最新汇率
      </Button>
      <Button size="sm" className="h-8 text-xs" onClick={openCreate}>
        <Plus className="mr-1 h-3 w-3" /> 新增汇率
      </Button>
    </div>
  ) : undefined;

  return (
    <>
      <DataTable
        columns={columns}
        data={data}
        searchKey="from_currency"
        searchPlaceholder="搜索币种..."
        pageSize={20}
        toolbar={toolbar}
        emptyState={<EmptyState icon={ArrowRightLeft} title="暂无汇率数据" description="点击「获取最新汇率」从 API 获取，或手动添加" />}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑汇率" : "新增汇率"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>源币种 *</Label>
                <Input
                  value={form.from_currency}
                  onChange={(e) => setForm({ ...form, from_currency: e.target.value.toUpperCase() })}
                  placeholder="例如：USD"
                  maxLength={3}
                  disabled={!!editing}
                />
              </div>
              <div className="grid gap-2">
                <Label>目标币种 *</Label>
                <Input
                  value={form.to_currency}
                  onChange={(e) => setForm({ ...form, to_currency: e.target.value.toUpperCase() })}
                  placeholder="例如：JPY"
                  maxLength={3}
                  disabled={!!editing}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>汇率 *</Label>
              <Input
                type="number"
                step="any"
                min="0"
                value={form.rate}
                onChange={(e) => setForm({ ...form, rate: e.target.value })}
                placeholder="例如：149.50"
              />
              {form.from_currency && form.to_currency && form.rate && (
                <p className="text-xs text-muted-foreground">
                  1 {form.from_currency} = {form.rate} {form.to_currency}
                </p>
              )}
            </div>
            <div className="grid gap-2">
              <Label>生效日期 *</Label>
              <Input
                type="date"
                value={form.effective_date}
                onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
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
