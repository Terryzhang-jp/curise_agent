"use client";

import { useEffect, useState, useCallback } from "react";
import type { SupplierInfo } from "@/lib/settings-api";
import { listSuppliersInfo, updateSupplierInfo } from "@/lib/settings-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { Users, Pencil, Search } from "lucide-react";

const FIELDS: { key: keyof SupplierInfo; label: string }[] = [
  { key: "contact", label: "联系人" },
  { key: "email", label: "邮箱" },
  { key: "phone", label: "电话" },
  { key: "fax", label: "传真" },
  { key: "zip_code", label: "邮编" },
  { key: "address", label: "地址" },
  { key: "default_payment_method", label: "默认付款方式" },
  { key: "default_payment_terms", label: "默认付款条件" },
];

export default function SupplierInfoTab() {
  const [suppliers, setSuppliers] = useState<SupplierInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SupplierInfo | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSuppliersInfo(search || undefined);
      setSuppliers(data);
    } catch (e: unknown) {
      toast.error("加载失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const openEdit = (supplier: SupplierInfo) => {
    setEditing(supplier);
    const f: Record<string, string> = {};
    for (const { key } of FIELDS) {
      f[key] = (supplier[key] as string) || "";
    }
    setForm(f);
    setEditDialogOpen(true);
  };

  const handleSave = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const data: Record<string, string | undefined> = {};
      for (const { key } of FIELDS) {
        data[key] = form[key] || undefined;
      }
      await updateSupplierInfo(editing.id, data);
      toast.success(`${editing.name} 信息已更新`);
      setEditDialogOpen(false);
      load();
    } catch (e: unknown) {
      toast.error("保存失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-5 w-5 text-muted-foreground" />
          <h3 className="text-lg font-semibold">供应商信息</h3>
          <span className="text-sm text-muted-foreground">
            管理供应商的联系方式和付款信息（用于询价单生成）
          </span>
        </div>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="搜索供应商..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[180px]">供应商名称</TableHead>
                <TableHead>联系人</TableHead>
                <TableHead>邮箱</TableHead>
                <TableHead>电话</TableHead>
                <TableHead>传真</TableHead>
                <TableHead>付款方式</TableHead>
                <TableHead className="w-[60px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    加载中...
                  </TableCell>
                </TableRow>
              ) : suppliers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    未找到供应商
                  </TableCell>
                </TableRow>
              ) : (
                suppliers.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell className="text-sm">{s.contact || "-"}</TableCell>
                    <TableCell className="text-sm">{s.email || "-"}</TableCell>
                    <TableCell className="text-sm">{s.phone || "-"}</TableCell>
                    <TableCell className="text-sm">{s.fax || "-"}</TableCell>
                    <TableCell className="text-sm">{s.default_payment_method || "-"}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon" onClick={() => openEdit(s)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>编辑供应商 — {editing?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {FIELDS.map(({ key, label }) => (
              <div key={key} className="space-y-1">
                <Label>{label}</Label>
                <Input
                  value={form[key] || ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                />
              </div>
            ))}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
                取消
              </Button>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "保存中..." : "保存"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
