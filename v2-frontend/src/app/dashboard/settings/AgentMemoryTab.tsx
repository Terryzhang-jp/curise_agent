"use client";

import { useEffect, useState, useCallback } from "react";
import type { AgentMemory } from "@/lib/chat-api";
import {
  listMemories,
  createMemory,
  updateMemory,
  deleteMemory,
  clearAllMemories,
} from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Brain, Plus, Pencil, Trash2, Trash, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";

const MEMORY_TYPES = [
  { value: "user_preference", label: "用户偏好", color: "bg-blue-100 text-blue-800" },
  { value: "supplier_knowledge", label: "供应商知识", color: "bg-green-100 text-green-800" },
  { value: "workflow_pattern", label: "工作流模式", color: "bg-purple-100 text-purple-800" },
  { value: "fact", label: "业务事实", color: "bg-orange-100 text-orange-800" },
] as const;

function getTypeInfo(type: string) {
  return MEMORY_TYPES.find((t) => t.value === type) ?? { value: type, label: type, color: "bg-gray-100 text-gray-800" };
}

export default function AgentMemoryTab() {
  const [memories, setMemories] = useState<AgentMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState<string>("all");

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formType, setFormType] = useState("fact");
  const [formKey, setFormKey] = useState("");
  const [formValue, setFormValue] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listMemories();
      setMemories(Array.isArray(data) ? data : []);
    } catch (e: unknown) {
      toast.error("加载记忆失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = memories.filter((m) => {
    const matchType = filterType === "all" || m.memory_type === filterType;
    const matchSearch =
      !search ||
      m.key.toLowerCase().includes(search.toLowerCase()) ||
      m.value.toLowerCase().includes(search.toLowerCase());
    return matchType && matchSearch;
  });

  const openCreate = () => {
    setEditingId(null);
    setFormType("fact");
    setFormKey("");
    setFormValue("");
    setDialogOpen(true);
  };

  const openEdit = (mem: AgentMemory) => {
    setEditingId(mem.id);
    setFormType(mem.memory_type);
    setFormKey(mem.key);
    setFormValue(mem.value);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formKey.trim() || !formValue.trim()) {
      toast.error("标识和内容不能为空");
      return;
    }
    setSaving(true);
    try {
      if (editingId) {
        await updateMemory(editingId, {
          memory_type: formType,
          key: formKey.trim(),
          value: formValue.trim(),
        });
        toast.success("记忆已更新");
      } else {
        await createMemory({
          memory_type: formType,
          key: formKey.trim(),
          value: formValue.trim(),
        });
        toast.success("记忆已创建");
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
      await deleteMemory(id);
      toast.success("已删除");
      load();
    } catch (e: unknown) {
      toast.error("删除失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  const handleClearAll = async () => {
    if (!confirm("确定要清除所有记忆吗？此操作不可撤销。")) return;
    try {
      const result = await clearAllMemories();
      toast.success(result.detail);
      load();
    } catch (e: unknown) {
      toast.error("清除失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  if (loading) {
    return <div className="text-center py-8 text-muted-foreground">加载中...</div>;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-muted-foreground" />
          <h3 className="text-lg font-semibold">Agent 记忆</h3>
          <span className="text-sm text-muted-foreground">
            AI 助手的跨会话长期记忆 ({memories.length} 条)
          </span>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleClearAll} disabled={memories.length === 0}>
            <Trash className="h-4 w-4 mr-1" />
            清除全部
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" />
            新增记忆
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索记忆..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {MEMORY_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Memory List */}
      {filtered.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            {memories.length === 0
              ? "暂无记忆。AI 助手会在对话中自动学习，或你可以手动添加。"
              : "没有匹配的记忆。"}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {filtered.map((mem) => {
            const typeInfo = getTypeInfo(mem.memory_type);
            return (
              <Card key={mem.id} className="group">
                <CardContent className="py-3 flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant="secondary" className={`text-xs ${typeInfo.color}`}>
                        {typeInfo.label}
                      </Badge>
                      <span className="font-medium text-sm truncate">{mem.key}</span>
                      {mem.access_count > 0 && (
                        <span className="text-xs text-muted-foreground">
                          使用 {mem.access_count} 次
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground line-clamp-2">{mem.value}</p>
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(mem)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-destructive"
                      onClick={() => handleDelete(mem.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑记忆" : "新增记忆"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>类型</Label>
              <Select value={formType} onValueChange={setFormType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MEMORY_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>标识 (Key)</Label>
              <Input
                placeholder="例: 三祐交货周期"
                value={formKey}
                onChange={(e) => setFormKey(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>内容 (Value)</Label>
              <Textarea
                placeholder="例: 三祐的标准交货周期是7个工作日，急单可以3天"
                value={formValue}
                onChange={(e) => setFormValue(e.target.value)}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "保存中..." : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
