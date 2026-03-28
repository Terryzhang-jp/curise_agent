"use client";

import { useEffect, useState, useCallback } from "react";
import type { DeliveryLocation } from "@/lib/settings-api";
import {
  listDeliveryLocations,
  createDeliveryLocation,
  updateDeliveryLocation,
  deleteDeliveryLocation,
} from "@/lib/settings-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { MapPin, Plus, Pencil, Trash2 } from "lucide-react";

interface FormData {
  name: string;
  address: string;
  contact_person: string;
  contact_phone: string;
  delivery_notes: string;
  ship_name_label: string;
}

const EMPTY_FORM: FormData = {
  name: "",
  address: "",
  contact_person: "",
  contact_phone: "",
  delivery_notes: "",
  ship_name_label: "",
};

export default function DeliveryLocationTab() {
  const [locations, setLocations] = useState<DeliveryLocation[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<DeliveryLocation | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listDeliveryLocations();
      setLocations(data);
    } catch (e: unknown) {
      toast.error("加载失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openNew = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (loc: DeliveryLocation) => {
    setEditing(loc);
    setForm({
      name: loc.name,
      address: loc.address || "",
      contact_person: loc.contact_person || "",
      contact_phone: loc.contact_phone || "",
      delivery_notes: loc.delivery_notes || "",
      ship_name_label: loc.ship_name_label || "",
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error("名称不能为空");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await updateDeliveryLocation(editing.id, {
          name: form.name,
          address: form.address || undefined,
          contact_person: form.contact_person || undefined,
          contact_phone: form.contact_phone || undefined,
          delivery_notes: form.delivery_notes || undefined,
          ship_name_label: form.ship_name_label || undefined,
        });
        toast.success("配送点已更新");
      } else {
        await createDeliveryLocation({
          name: form.name,
          address: form.address || undefined,
          contact_person: form.contact_person || undefined,
          contact_phone: form.contact_phone || undefined,
          delivery_notes: form.delivery_notes || undefined,
          ship_name_label: form.ship_name_label || undefined,
        });
        toast.success("配送点已创建");
      }
      setDialogOpen(false);
      load();
    } catch (e: unknown) {
      toast.error("保存失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteDeliveryLocation(id);
      toast.success("配送点已删除");
      load();
    } catch (e: unknown) {
      toast.error("删除失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  const setField = (key: keyof FormData, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapPin className="h-5 w-5 text-muted-foreground" />
          <h3 className="text-lg font-semibold">仓库 / 配送点</h3>
          <span className="text-sm text-muted-foreground">
            询价单中的配送地址和联系方式
          </span>
        </div>
        <Button size="sm" onClick={openNew}>
          <Plus className="h-4 w-4 mr-1" />
          新建配送点
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-8 text-muted-foreground">加载中...</div>
      ) : locations.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            暂无配送点，点击"新建配送点"添加
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {locations.map((loc) => (
            <Card key={loc.id}>
              <CardContent className="flex items-start justify-between py-4 px-5">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium">{loc.name}</span>
                    {loc.is_default && (
                      <Badge variant="secondary" className="text-xs">默认</Badge>
                    )}
                    {loc.port_name && (
                      <Badge variant="outline" className="text-xs">{loc.port_name}</Badge>
                    )}
                  </div>
                  <div className="text-sm text-muted-foreground space-y-0.5">
                    {loc.address && <p>{loc.address}</p>}
                    {loc.contact_person && (
                      <p>联系人: {loc.contact_person} {loc.contact_phone && `(${loc.contact_phone})`}</p>
                    )}
                    {loc.ship_name_label && <p>船名标签: {loc.ship_name_label}</p>}
                    {loc.delivery_notes && <p>备注: {loc.delivery_notes}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0 ml-4">
                  <Button variant="ghost" size="icon" onClick={() => openEdit(loc)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button variant="ghost" size="icon">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>删除配送点</AlertDialogTitle>
                        <AlertDialogDescription>
                          确定要删除 &ldquo;{loc.name}&rdquo; 吗？此操作不可撤销。
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction
                          variant="destructive"
                          onClick={() => handleDelete(loc.id)}
                        >
                          删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑配送点" : "新建配送点"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>名称 *</Label>
              <Input
                value={form.name}
                onChange={(e) => setField("name", e.target.value)}
                placeholder="如：那覇仓库"
              />
            </div>
            <div className="space-y-1">
              <Label>地址</Label>
              <Input
                value={form.address}
                onChange={(e) => setField("address", e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>联系人</Label>
                <Input
                  value={form.contact_person}
                  onChange={(e) => setField("contact_person", e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label>联系电话</Label>
                <Input
                  value={form.contact_phone}
                  onChange={(e) => setField("contact_phone", e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label>船名标签</Label>
              <Input
                value={form.ship_name_label}
                onChange={(e) => setField("ship_name_label", e.target.value)}
                placeholder="如：M/V DIAMOND PRINCESS"
              />
            </div>
            <div className="space-y-1">
              <Label>配送备注</Label>
              <Input
                value={form.delivery_notes}
                onChange={(e) => setField("delivery_notes", e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setDialogOpen(false)}>
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
