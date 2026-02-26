"use client";

import { useEffect, useState, useCallback } from "react";
import type { ToolConfig, SkillConfig } from "@/lib/settings-api";
import {
  listTools,
  updateTool,
  seedTools,
  listSkills,
  createSkill,
  updateSkill,
  deleteSkill,
  seedSkills,
} from "@/lib/settings-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { Wrench, Sparkles, Plus, Trash2, Pencil, RefreshCw } from "lucide-react";

// ─── Group labels ───────────────────────────────────────────

const GROUP_LABELS: Record<string, string> = {
  reasoning: "推理",
  business: "业务",
  utility: "工具",
  todo: "任务",
  skill: "技能",
  web: "网络",
  default: "其他",
};

export default function AIConfigTab() {
  // ─── Tools State ───────────────────────────────────────────
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);

  // ─── Skills State ──────────────────────────────────────────
  const [skills, setSkills] = useState<SkillConfig[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillDialogOpen, setSkillDialogOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillConfig | null>(null);

  // Skill form
  const [skillName, setSkillName] = useState("");
  const [skillDisplayName, setSkillDisplayName] = useState("");
  const [skillDescription, setSkillDescription] = useState("");
  const [skillContent, setSkillContent] = useState("");

  // ─── Loaders ────────────────────────────────────────────────

  const loadTools = useCallback(async () => {
    setToolsLoading(true);
    try {
      const data = await listTools();
      setTools(data);
    } catch (e: unknown) {
      toast.error("加载工具列表失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setToolsLoading(false);
    }
  }, []);

  const loadSkills = useCallback(async () => {
    setSkillsLoading(true);
    try {
      const data = await listSkills();
      setSkills(data);
    } catch (e: unknown) {
      toast.error("加载技能列表失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setSkillsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTools();
    loadSkills();
  }, [loadTools, loadSkills]);

  // ─── Tool Handlers ─────────────────────────────────────────

  const handleToolToggle = async (toolName: string, enabled: boolean) => {
    try {
      const updated = await updateTool(toolName, { is_enabled: enabled });
      setTools((prev) => prev.map((t) => (t.tool_name === toolName ? updated : t)));
      toast.success(`${updated.display_name} 已${enabled ? "启用" : "禁用"}`);
    } catch (e: unknown) {
      toast.error("切换失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  const handleSeedTools = async () => {
    try {
      const res = await seedTools();
      toast.success(res.detail);
      loadTools();
    } catch (e: unknown) {
      toast.error("同步失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  // ─── Skill Handlers ────────────────────────────────────────

  const openNewSkillDialog = () => {
    setEditingSkill(null);
    setSkillName("");
    setSkillDisplayName("");
    setSkillDescription("");
    setSkillContent("");
    setSkillDialogOpen(true);
  };

  const openEditSkillDialog = (skill: SkillConfig) => {
    setEditingSkill(skill);
    setSkillName(skill.name);
    setSkillDisplayName(skill.display_name);
    setSkillDescription(skill.description || "");
    setSkillContent(skill.content || "");
    setSkillDialogOpen(true);
  };

  const handleSaveSkill = async () => {
    if (!skillName.trim() || !skillDisplayName.trim()) {
      toast.error("名称不能为空");
      return;
    }
    try {
      if (editingSkill) {
        await updateSkill(editingSkill.id, {
          display_name: skillDisplayName,
          description: skillDescription || undefined,
          content: skillContent || undefined,
        });
        toast.success("技能已更新");
      } else {
        await createSkill({
          name: skillName,
          display_name: skillDisplayName,
          description: skillDescription || undefined,
          content: skillContent || undefined,
        });
        toast.success("技能已创建");
      }
      setSkillDialogOpen(false);
      loadSkills();
    } catch (e: unknown) {
      toast.error("保存失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  const handleDeleteSkill = async (id: number) => {
    try {
      await deleteSkill(id);
      toast.success("技能已删除");
      loadSkills();
    } catch (e: unknown) {
      toast.error("删除失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  const handleSkillToggle = async (skill: SkillConfig, enabled: boolean) => {
    try {
      const updated = await updateSkill(skill.id, { is_enabled: enabled });
      setSkills((prev) => prev.map((s) => (s.id === skill.id ? updated : s)));
      toast.success(`${skill.display_name} 已${enabled ? "启用" : "禁用"}`);
    } catch (e: unknown) {
      toast.error("切换失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  const handleSeedSkills = async () => {
    try {
      const res = await seedSkills();
      toast.success(res.detail);
      loadSkills();
    } catch (e: unknown) {
      toast.error("同步失败: " + (e instanceof Error ? e.message : "未知错误"));
    }
  };

  // ─── Render ─────────────────────────────────────────────────

  return (
    <div className="space-y-8">
      {/* ── AI 工具 ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Wrench className="h-5 w-5 text-muted-foreground" />
            <h3 className="text-lg font-semibold">AI 工具</h3>
            <span className="text-sm text-muted-foreground">
              控制 AI 助手可使用的工具，修改后新对话生效
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={handleSeedTools}>
            <RefreshCw className="h-4 w-4 mr-1" />
            同步内置工具
          </Button>
        </div>

        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[140px]">工具名</TableHead>
                  <TableHead className="w-[100px]">分组</TableHead>
                  <TableHead>显示名</TableHead>
                  <TableHead>说明</TableHead>
                  <TableHead className="w-[80px] text-center">状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {toolsLoading ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                      加载中...
                    </TableCell>
                  </TableRow>
                ) : tools.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                      暂无工具配置，点击"同步内置工具"初始化
                    </TableCell>
                  </TableRow>
                ) : (
                  tools.map((tool) => (
                    <TableRow key={tool.tool_name}>
                      <TableCell className="font-mono text-sm">{tool.tool_name}</TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {GROUP_LABELS[tool.group_name] || tool.group_name}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">{tool.display_name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground max-w-[300px] truncate">
                        {tool.description}
                      </TableCell>
                      <TableCell className="text-center">
                        <Switch
                          checked={tool.is_enabled}
                          onCheckedChange={(checked) =>
                            handleToolToggle(tool.tool_name, checked)
                          }
                        />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </section>

      {/* ── 技能模板 ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-muted-foreground" />
            <h3 className="text-lg font-semibold">技能模板</h3>
            <span className="text-sm text-muted-foreground">
              可复用的 Prompt 模板，通过 /技能名 或 use_skill 工具调用
            </span>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleSeedSkills}>
              <RefreshCw className="h-4 w-4 mr-1" />
              从文件同步
            </Button>
            <Button size="sm" onClick={openNewSkillDialog}>
              <Plus className="h-4 w-4 mr-1" />
              新建技能
            </Button>
          </div>
        </div>

        {skillsLoading ? (
          <div className="text-center py-8 text-muted-foreground">加载中...</div>
        ) : skills.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              暂无技能，点击"新建技能"创建或"从文件同步"导入内置技能
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3">
            {skills.map((skill) => (
              <Card key={skill.id}>
                <CardContent className="flex items-center justify-between py-4 px-5">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium">{skill.display_name}</span>
                      <Badge variant="outline" className="font-mono text-xs">
                        /{skill.name}
                      </Badge>
                      {skill.is_builtin && (
                        <Badge variant="secondary" className="text-xs">内置</Badge>
                      )}
                    </div>
                    {skill.description && (
                      <p className="text-sm text-muted-foreground truncate max-w-[600px]">
                        {skill.description}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-3 shrink-0 ml-4">
                    <Switch
                      checked={skill.is_enabled}
                      onCheckedChange={(checked) => handleSkillToggle(skill, checked)}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => openEditSkillDialog(skill)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    {!skill.is_builtin && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon">
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>删除技能</AlertDialogTitle>
                            <AlertDialogDescription>
                              确定要删除技能 &ldquo;{skill.display_name}&rdquo; 吗？此操作不可撤销。
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>取消</AlertDialogCancel>
                            <AlertDialogAction
                              variant="destructive"
                              onClick={() => handleDeleteSkill(skill.id)}
                            >
                              删除
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* ── Skill Dialog ── */}
      <Dialog open={skillDialogOpen} onOpenChange={setSkillDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingSkill ? "编辑技能" : "新建技能"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>技能标识名</Label>
                <Input
                  value={skillName}
                  onChange={(e) => setSkillName(e.target.value)}
                  placeholder="如 analyze-order"
                  disabled={!!editingSkill}
                />
                <p className="text-xs text-muted-foreground">
                  用于触发技能的唯一标识，在聊天中输入 /标识名 即可调用
                </p>
              </div>
              <div className="space-y-2">
                <Label>显示名称</Label>
                <Input
                  value={skillDisplayName}
                  onChange={(e) => setSkillDisplayName(e.target.value)}
                  placeholder="如 订单分析"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>描述</Label>
              <Input
                value={skillDescription}
                onChange={(e) => setSkillDescription(e.target.value)}
                placeholder="简要描述技能用途，AI 会根据描述判断何时使用此技能"
              />
            </div>
            <div className="space-y-2">
              <Label>Prompt 模板</Label>
              <Textarea
                value={skillContent}
                onChange={(e) => setSkillContent(e.target.value)}
                placeholder={`请分析以下订单数据：\n\n$ARGUMENTS\n\n要求：\n1. 检查产品匹配情况\n2. 标注异常价格\n3. 给出优化建议`}
                rows={10}
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                编写 AI 执行此技能时的指令。用 <code className="bg-muted px-1 rounded">$ARGUMENTS</code> 作为参数占位符，
                调用时会替换为用户输入的内容。例如：用户输入 <code className="bg-muted px-1 rounded">/analyze-order 订单#123</code>，
                则 $ARGUMENTS 被替换为 &ldquo;订单#123&rdquo;。
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setSkillDialogOpen(false)}>
                取消
              </Button>
              <Button onClick={handleSaveSkill}>保存</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
