"use client";

import { useEffect, useState, useCallback } from "react";
import type { FieldSchema, FieldDefinition } from "@/lib/settings-api";
import {
  listFieldSchemas,
  seedDefaults,
  createFieldSchema,
  deleteFieldSchema,
  updateFieldSchema,
  addFieldDefinition,
  updateFieldDefinition,
  deleteFieldDefinition,
} from "@/lib/settings-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { EmptyState } from "@/components/empty-state";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash2, Database, Check } from "lucide-react";

type View = "list" | "edit";

export default function FieldSchemaTab() {
  const [schemas, setSchemas] = useState<FieldSchema[]>([]);
  const [view, setView] = useState<View>("list");
  const [editingSchema, setEditingSchema] = useState<FieldSchema | null>(null);
  const [loading, setLoading] = useState(false);

  // Edit form state
  const [schemaName, setSchemaName] = useState("");
  const [schemaDesc, setSchemaDesc] = useState("");
  const [definitions, setDefinitions] = useState<FieldDefinition[]>([]);

  // New definition form
  const [newKey, setNewKey] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newType, setNewType] = useState("string");

  const refresh = useCallback(async () => {
    try {
      const data = await listFieldSchemas();
      setSchemas(data);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSeed = async () => {
    setLoading(true);
    try {
      await seedDefaults();
      await refresh();
      toast.success("默认字段已初始化");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateSchema = async () => {
    setLoading(true);
    try {
      const schema = await createFieldSchema({ name: "新字段模式" });
      await refresh();
      openEdit(schema);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "创建失败");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteSchema = async (id: number) => {
    try {
      await deleteFieldSchema(id);
      await refresh();
      toast.success("已删除");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const openEdit = (schema: FieldSchema) => {
    setEditingSchema(schema);
    setSchemaName(schema.name);
    setSchemaDesc(schema.description || "");
    setDefinitions([...schema.definitions].sort((a, b) => a.sort_order - b.sort_order));
    setView("edit");
  };

  const handleSaveSchema = async () => {
    if (!editingSchema) return;
    setLoading(true);
    try {
      await updateFieldSchema(editingSchema.id, { name: schemaName, description: schemaDesc });
      await refresh();
      setView("list");
      toast.success("保存成功");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setLoading(false);
    }
  };

  const handleAddDef = async () => {
    if (!editingSchema || !newKey.trim() || !newLabel.trim()) return;
    setLoading(true);
    try {
      const def = await addFieldDefinition(editingSchema.id, {
        field_key: newKey.trim(),
        field_label: newLabel.trim(),
        field_type: newType,
        sort_order: definitions.length + 1,
      });
      setDefinitions((prev) => [...prev, def]);
      setNewKey("");
      setNewLabel("");
      setNewType("string");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "添加失败");
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateDef = async (
    def: FieldDefinition,
    updates: Partial<{ field_label: string; field_type: string; is_required: boolean; extraction_hint: string; sort_order: number }>
  ) => {
    if (!editingSchema) return;
    try {
      const updated = await updateFieldDefinition(editingSchema.id, def.id, updates);
      setDefinitions((prev) => prev.map((d) => (d.id === def.id ? updated : d)));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "更新失败");
    }
  };

  const handleDeleteDef = async (def: FieldDefinition) => {
    if (!editingSchema) return;
    if (def.is_core) {
      toast.error("核心字段不可删除");
      return;
    }
    try {
      await deleteFieldDefinition(editingSchema.id, def.id);
      setDefinitions((prev) => prev.filter((d) => d.id !== def.id));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  // ─── List View ───────────────────────────────────────────────
  if (view === "list") {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">字段模式</h3>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleSeed} disabled={loading}>
              <Database className="h-3.5 w-3.5 mr-1.5" />
              初始化默认字段
            </Button>
            <Button size="sm" onClick={handleCreateSchema} disabled={loading}>
              <Plus className="h-3.5 w-3.5 mr-1.5" />
              新建模式
            </Button>
          </div>
        </div>

        {schemas.length === 0 ? (
          <EmptyState
            icon={Database}
            title="暂无字段模式"
            description={'点击「初始化默认字段」创建系统默认字段模式'}
          />
        ) : (
          <div className="grid gap-3">
            {schemas.map((schema) => (
              <Card key={schema.id} className="hover:border-border transition-colors">
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{schema.name}</span>
                        {schema.is_default && <Badge variant="secondary">默认</Badge>}
                      </div>
                      {schema.description && (
                        <div className="text-muted-foreground text-xs mt-1">{schema.description}</div>
                      )}
                      <div className="text-muted-foreground text-xs mt-2">
                        {schema.definitions.length} 个字段
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button variant="ghost" size="sm" onClick={() => openEdit(schema)}>
                        编辑
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-destructive">
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>确定删除？</AlertDialogTitle>
                            <AlertDialogDescription>
                              将删除字段模式「{schema.name}」及其所有字段定义。此操作不可撤销。
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>取消</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDeleteSchema(schema.id)}>
                              删除
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ─── Edit View ───────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => { setView("list"); refresh(); }}
        >
          <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
          返回列表
        </Button>
        <Button size="sm" onClick={handleSaveSchema} disabled={loading}>
          保存
        </Button>
      </div>

      {/* Schema Info */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label className="text-xs">模式名称</Label>
          <Input
            value={schemaName}
            onChange={(e) => setSchemaName(e.target.value)}
            className="mt-1"
          />
        </div>
        <div>
          <Label className="text-xs">描述</Label>
          <Input
            value={schemaDesc}
            onChange={(e) => setSchemaDesc(e.target.value)}
            className="mt-1"
          />
        </div>
      </div>

      {/* Field Definitions Table */}
      <div>
        <h4 className="text-sm font-medium mb-3">字段定义</h4>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">字段键</TableHead>
                <TableHead className="text-xs">标签</TableHead>
                <TableHead className="text-xs">类型</TableHead>
                <TableHead className="text-xs w-16">必填</TableHead>
                <TableHead className="text-xs w-16">核心</TableHead>
                <TableHead className="text-xs">提示</TableHead>
                <TableHead className="text-xs text-right w-16">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {definitions.map((def) => (
                <TableRow key={def.id}>
                  <TableCell className="font-mono text-xs">{def.field_key}</TableCell>
                  <TableCell>
                    <Input
                      value={def.field_label}
                      onChange={(e) =>
                        setDefinitions((prev) =>
                          prev.map((d) =>
                            d.id === def.id ? { ...d, field_label: e.target.value } : d
                          )
                        )
                      }
                      onBlur={(e) => handleUpdateDef(def, { field_label: e.target.value })}
                      className="h-7 text-xs border-transparent hover:border-border focus:border-ring"
                    />
                  </TableCell>
                  <TableCell>
                    <Select
                      value={def.field_type}
                      onValueChange={(v) => handleUpdateDef(def, { field_type: v })}
                    >
                      <SelectTrigger className="h-7 text-xs w-24">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="string">string</SelectItem>
                        <SelectItem value="number">number</SelectItem>
                        <SelectItem value="date">date</SelectItem>
                        <SelectItem value="currency">currency</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <input
                      type="checkbox"
                      checked={def.is_required}
                      onChange={(e) => handleUpdateDef(def, { is_required: e.target.checked })}
                      className="accent-primary"
                    />
                  </TableCell>
                  <TableCell>
                    {def.is_core ? (
                      <Check className="h-3.5 w-3.5 text-primary" />
                    ) : (
                      <span className="text-muted-foreground text-xs">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Input
                      value={def.extraction_hint || ""}
                      onChange={(e) =>
                        setDefinitions((prev) =>
                          prev.map((d) =>
                            d.id === def.id ? { ...d, extraction_hint: e.target.value } : d
                          )
                        )
                      }
                      onBlur={(e) =>
                        handleUpdateDef(def, { extraction_hint: e.target.value || undefined })
                      }
                      placeholder="..."
                      className="h-7 text-xs border-transparent hover:border-border focus:border-ring text-muted-foreground"
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    {!def.is_core && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => handleDeleteDef(def)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}

              {/* Add New Row */}
              <TableRow className="bg-muted/30">
                <TableCell>
                  <Input
                    value={newKey}
                    onChange={(e) => setNewKey(e.target.value)}
                    placeholder="field_key"
                    className="h-7 text-xs font-mono"
                  />
                </TableCell>
                <TableCell>
                  <Input
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    placeholder="标签"
                    className="h-7 text-xs"
                  />
                </TableCell>
                <TableCell>
                  <Select value={newType} onValueChange={setNewType}>
                    <SelectTrigger className="h-7 text-xs w-24">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="string">string</SelectItem>
                      <SelectItem value="number">number</SelectItem>
                      <SelectItem value="date">date</SelectItem>
                      <SelectItem value="currency">currency</SelectItem>
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell colSpan={3} />
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleAddDef}
                    disabled={!newKey.trim() || !newLabel.trim() || loading}
                    className="text-primary"
                  >
                    <Plus className="h-3.5 w-3.5 mr-1" />
                    添加
                  </Button>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Card>
      </div>
    </div>
  );
}
