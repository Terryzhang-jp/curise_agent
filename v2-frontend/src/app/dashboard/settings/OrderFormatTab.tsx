"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { FileDropZone } from "@/components/file-drop-zone";
import type {
  OrderFormatTemplate,
  ExcelSheet,
  FieldSchema,
  PdfMetadata,
  DocumentSchema,
} from "@/lib/settings-api";
import {
  listOrderTemplates,
  createOrderTemplate,
  updateOrderTemplate,
  deleteOrderTemplate,
  parseExcel,
  listFieldSchemas,
  inferOrderTemplate,
  analyzeOrderTemplatePdf,
} from "@/lib/settings-api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { EmptyState } from "@/components/empty-state";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash2, FileSpreadsheet, Loader2, ChevronRight, Pencil } from "lucide-react";

/** Collapsible AI layout prompt block — shows first 3 lines, expand to see all */
function LayoutPromptBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const lines = text.split("\n");
  const preview = lines.slice(0, 3).join("\n");
  const needsTruncation = lines.length > 3;

  return (
    <div>
      <div className="text-xs text-muted-foreground mb-1.5">AI 布局提示</div>
      <pre className="bg-muted rounded-md px-3 py-2 text-xs font-mono whitespace-pre-wrap break-words">
        {expanded || !needsTruncation ? text : preview + "\n..."}
      </pre>
      {needsTruncation && (
        <button
          className="text-xs text-primary hover:underline mt-1 cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "收起" : `展开全部 (${lines.length} 行)`}
        </button>
      )}
    </div>
  );
}

type View = "list" | "create";

const STEPS = [
  { num: 1, label: "上传" },
  { num: 2, label: "映射" },
  { num: 3, label: "保存" },
];

export default function OrderFormatTab() {
  const [templates, setTemplates] = useState<OrderFormatTemplate[]>([]);
  const [fieldSchemas, setFieldSchemas] = useState<FieldSchema[]>([]);
  const [view, setView] = useState<View>("list");
  const [loading, setLoading] = useState(false);

  // Creation wizard state
  const [step, setStep] = useState(1);
  const [parsedSheet, setParsedSheet] = useState<ExcelSheet | null>(null);
  const [fileUrl, setFileUrl] = useState("");
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [templateName, setTemplateName] = useState("");
  const [selectedSchemaId, setSelectedSchemaId] = useState<number | null>(null);

  // PDF-specific state
  const [fileType, setFileType] = useState<string>("excel");
  const [pdfMetadata, setPdfMetadata] = useState<PdfMetadata | null>(null);
  const [layoutPrompt, setLayoutPrompt] = useState("");

  // Schema-first PDF state
  const [documentSchema, setDocumentSchema] = useState<DocumentSchema | null>(null);
  const [schemaAnalyzing, setSchemaAnalyzing] = useState(false);
  const [editedMapping, setEditedMapping] = useState<Record<string, string>>({});

  // Template matching fields
  const [sourceCompany, setSourceCompany] = useState("");
  const [matchKeywords, setMatchKeywords] = useState("");
  const [notes, setNotes] = useState("");
  const [inferring, setInferring] = useState(false);

  // List view: expand & edit state
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editingTpl, setEditingTpl] = useState<OrderFormatTemplate | null>(null);
  const [editName, setEditName] = useState("");
  const [editCompany, setEditCompany] = useState("");
  const [editKeywords, setEditKeywords] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  // field_key → 中文标签 map
  const fieldLabelMap = useMemo(() => {
    const m: Record<string, string> = {};
    fieldSchemas.forEach((s) =>
      s.definitions.forEach((d) => {
        m[d.field_key] = d.field_label;
      }),
    );
    return m;
  }, [fieldSchemas]);

  const refresh = useCallback(async () => {
    try {
      const [tpls, schemas] = await Promise.all([listOrderTemplates(), listFieldSchemas()]);
      setTemplates(tpls);
      setFieldSchemas(schemas);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleDelete = async (id: number) => {
    try {
      await deleteOrderTemplate(id);
      await refresh();
      toast.success("已删除");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const openEdit = (tpl: OrderFormatTemplate) => {
    setEditingTpl(tpl);
    setEditName(tpl.name);
    setEditCompany(tpl.source_company || "");
    setEditKeywords(tpl.match_keywords?.join(", ") || "");
    setEditNotes(tpl.notes || "");
  };

  const handleEditSave = async () => {
    if (!editingTpl || !editName.trim()) return;
    setEditSaving(true);
    const keywords = editKeywords
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await updateOrderTemplate(editingTpl.id, {
        name: editName.trim(),
        source_company: editCompany.trim() || undefined,
        match_keywords: keywords.length > 0 ? keywords : [],
        notes: editNotes.trim() || undefined,
      });
      await refresh();
      setEditingTpl(null);
      toast.success("模板已更新");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "更新失败");
    } finally {
      setEditSaving(false);
    }
  };

  const handleToggleActive = async (tpl: OrderFormatTemplate) => {
    try {
      await updateOrderTemplate(tpl.id, { is_active: !tpl.is_active });
      await refresh();
      toast.success(tpl.is_active ? "已停用" : "已启用");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    }
  };

  const startCreate = () => {
    setView("create");
    setStep(1);
    setParsedSheet(null);
    setFileUrl("");
    setColumnMapping({});
    setTemplateName("");
    setSelectedSchemaId(fieldSchemas[0]?.id || null);
    setFileType("excel");
    setPdfMetadata(null);
    setLayoutPrompt("");
    setSourceCompany("");
    setMatchKeywords("");
    setNotes("");
    setDocumentSchema(null);
    setSchemaAnalyzing(false);
    setEditedMapping({});
  };

  const handleFileUpload = async (file: File) => {
    setLoading(true);
    try {
      // PDF → new schema-first analysis
      if (file.name.toLowerCase().endsWith(".pdf")) {
        setFileType("pdf");
        setSchemaAnalyzing(true);
        try {
          const result = await analyzeOrderTemplatePdf(file);
          setDocumentSchema(result.document_schema);
          setEditedMapping(result.document_schema.field_mapping || {});
          setFileUrl(result.sample_file_url);
          if (!templateName) setTemplateName(result.document_type || "PDF 订单模板");
          setStep(2);
        } finally {
          setSchemaAnalyzing(false);
        }
      } else {
        // Excel → original flow unchanged
        const result = await parseExcel(file);
        const detectedType = result.file_type || "excel";
        setFileType(detectedType);

        if (detectedType === "pdf") {
          setPdfMetadata(result.metadata || null);
          setLayoutPrompt(result.layout_prompt || "");
        }

        if (result.sheets.length > 0) {
          setParsedSheet(result.sheets[0]);
          setFileUrl(result.file_url);
          const mapping: Record<string, string> = {};
          result.sheets[0].headers.forEach((h) => {
            mapping[h.column] = "";
          });
          setColumnMapping(mapping);
          setStep(2);

          // Async AI inference for template name/company/keywords (non-blocking)
          const headerLabels = result.sheets[0].headers.map((h) => h.label);
          const rawText = result.raw_text || "";
          if (rawText) {
            setInferring(true);
            inferOrderTemplate({ raw_text: rawText, headers: headerLabels, file_type: detectedType })
              .then((inferred) => {
                if (inferred.name && !templateName) setTemplateName(inferred.name);
                if (inferred.source_company && !sourceCompany) setSourceCompany(inferred.source_company);
                if (inferred.match_keywords?.length && !matchKeywords) {
                  setMatchKeywords(inferred.match_keywords.join(", "));
                }
              })
              .catch(() => {})
              .finally(() => setInferring(false));
          }
        }
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "解析失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!templateName.trim()) return;
    // For Excel flow, parsedSheet is required; for PDF schema flow, documentSchema is required
    if (!documentSchema && !parsedSheet) return;
    setLoading(true);

    const keywords = matchKeywords
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      if (fileType === "pdf" && documentSchema) {
        // PDF schema-first save
        const updatedSchema = { ...documentSchema, field_mapping: editedMapping };
        await createOrderTemplate({
          name: templateName.trim(),
          file_type: "pdf",
          sample_file_url: fileUrl,
          document_schema: updatedSchema,
          source_company: sourceCompany.trim() || undefined,
          match_keywords: keywords.length > 0 ? keywords : undefined,
          notes: notes.trim() || undefined,
        });
      } else if (parsedSheet) {
        // Excel (or legacy PDF) save
        const filtered: Record<string, string> = {};
        for (const [col, key] of Object.entries(columnMapping)) {
          if (key) filtered[col] = key;
        }
        await createOrderTemplate({
          name: templateName.trim(),
          file_type: fileType,
          header_row: parsedSheet.header_row,
          data_start_row: parsedSheet.data_start_row,
          column_mapping: filtered,
          field_schema_id: selectedSchemaId || undefined,
          format_fingerprint: parsedSheet.fingerprint,
          sample_file_url: fileUrl,
          source_company: sourceCompany.trim() || undefined,
          match_keywords: keywords.length > 0 ? keywords : undefined,
          notes: notes.trim() || undefined,
          ...(fileType === "pdf" && {
            layout_prompt: layoutPrompt || undefined,
            extracted_fields: pdfMetadata?.fields || undefined,
          }),
        });
      }
      await refresh();
      setView("list");
      toast.success("模板已保存");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setLoading(false);
    }
  };

  const fieldOptions =
    fieldSchemas.find((s) => s.id === selectedSchemaId)?.definitions || [];

  // ─── List View ───────────────────────────────────────────────
  if (view === "list") {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">订单格式模板</h3>
          <Button size="sm" onClick={startCreate}>
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            新建模板
          </Button>
        </div>

        {templates.length === 0 ? (
          <EmptyState
            icon={FileSpreadsheet}
            title="暂无订单格式模板"
            description="上传订单文件创建格式模板"
            action={<Button size="sm" onClick={startCreate}>新建模板</Button>}
          />
        ) : (
          <div className="grid gap-2">
            {templates.map((tpl) => {
              const isOpen = expandedId === tpl.id;
              const mappingEntries = tpl.column_mapping
                ? Object.entries(tpl.column_mapping).sort(([a], [b]) => a.localeCompare(b))
                : [];

              return (
                <Collapsible
                  key={tpl.id}
                  open={isOpen}
                  onOpenChange={(open) => setExpandedId(open ? tpl.id : null)}
                >
                  <Card className={cn("transition-colors", !tpl.is_active && "opacity-50")}>
                    {/* ── Summary row (trigger) ── */}
                    <div className="flex items-center px-4 py-3">
                      <CollapsibleTrigger asChild>
                        <button className="flex items-center gap-2 flex-1 min-w-0 text-left cursor-pointer">
                          <ChevronRight className={cn(
                            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
                            isOpen && "rotate-90",
                          )} />
                          <span className={cn("font-medium text-sm truncate", !tpl.is_active && "line-through")}>
                            {tpl.name}
                          </span>
                          <Badge variant="outline" className={cn(
                            "text-[10px] px-1.5 shrink-0",
                            tpl.file_type === "pdf"
                              ? "text-orange-500 border-orange-500/30"
                              : "text-emerald-600 border-emerald-600/30",
                          )}>
                            {tpl.file_type === "pdf" ? "PDF" : "Excel"}
                          </Badge>
                          {tpl.source_company && (
                            <span className="text-xs text-muted-foreground truncate shrink-0">
                              来源: {tpl.source_company}
                            </span>
                          )}
                          {!tpl.is_active && (
                            <Badge variant="outline" className="text-muted-foreground border-muted-foreground/30 text-[10px] shrink-0">
                              已停用
                            </Badge>
                          )}
                        </button>
                      </CollapsibleTrigger>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive h-8 w-8 shrink-0 ml-2">
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>确定删除？</AlertDialogTitle>
                            <AlertDialogDescription>
                              将删除订单格式模板「{tpl.name}」。此操作不可撤销。
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>取消</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDelete(tpl.id)}>删除</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>

                    {/* ── Expanded content ── */}
                    <CollapsibleContent>
                      <div className="border-t px-4 pb-4 pt-3 space-y-4">
                        {/* a) 匹配关键词 */}
                        {tpl.match_keywords && tpl.match_keywords.length > 0 && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1.5">匹配关键词</div>
                            <div className="flex flex-wrap gap-1.5">
                              {tpl.match_keywords.map((kw) => (
                                <Badge key={kw} variant="secondary" className="text-xs">
                                  {kw}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* b) 备注 */}
                        {tpl.notes && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">备注</div>
                            <p className="text-xs whitespace-pre-wrap">{tpl.notes}</p>
                          </div>
                        )}

                        {/* c) 列映射表格 */}
                        {mappingEntries.length > 0 && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1.5">列映射</div>
                            <Card>
                              <Table>
                                <TableHeader>
                                  <TableRow>
                                    <TableHead className="text-xs w-16">列</TableHead>
                                    <TableHead className="text-xs">映射字段</TableHead>
                                    <TableHead className="text-xs">字段名称</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {mappingEntries.map(([col, fieldKey]) => (
                                    <TableRow key={col}>
                                      <TableCell className="font-mono text-xs">{col}</TableCell>
                                      <TableCell className="font-mono text-xs text-muted-foreground">{fieldKey}</TableCell>
                                      <TableCell className="text-xs">{fieldLabelMap[fieldKey] || fieldKey}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </Card>
                          </div>
                        )}

                        {/* c) PDF 专属区 */}
                        {tpl.file_type === "pdf" && (
                          <>
                            {/* Schema-first info */}
                            {tpl.document_schema && (
                              <div>
                                <div className="text-xs text-muted-foreground mb-1.5">Document Schema</div>
                                <div className="flex flex-wrap gap-3 text-xs mb-2">
                                  <span>类型: {tpl.document_schema.document_type}</span>
                                  <span>{tpl.document_schema.attribute_groups?.length || 0} 个属性组</span>
                                  <span>{tpl.document_schema.page_layout?.total_pages || "?"} 页</span>
                                  {tpl.document_schema.field_mapping && (
                                    <span>{Object.keys(tpl.document_schema.field_mapping).length} 个字段已映射</span>
                                  )}
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                  {tpl.document_schema.attribute_groups?.map((g: { type: string; name: string; name_en: string; estimated_row_count?: number }, i: number) => (
                                    <Badge key={i} variant="outline" className={cn(
                                      "text-[10px]",
                                      g.type === "single" ? "text-blue-500 border-blue-500/30" :
                                      g.type === "repeating" ? "text-green-500 border-green-500/30" :
                                      "text-amber-500 border-amber-500/30"
                                    )}>
                                      {g.name} ({g.name_en})
                                      {g.type === "repeating" && g.estimated_row_count ? ` ~${g.estimated_row_count}行` : ""}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            )}
                            {/* Legacy PDF fields */}
                            {!tpl.document_schema && tpl.extracted_fields && tpl.extracted_fields.length > 0 && (
                              <div>
                                <div className="text-xs text-muted-foreground mb-1.5">提取字段</div>
                                <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                                  {tpl.extracted_fields.map((f) => (
                                    <div key={f.key} className="text-xs">
                                      <span className="text-muted-foreground">{f.label}:</span>{" "}
                                      <span>{f.value || "-"}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {tpl.layout_prompt && (
                              <LayoutPromptBlock text={tpl.layout_prompt} />
                            )}
                          </>
                        )}

                        {/* d) 底部信息 + 操作栏 */}
                        <div className="flex items-center justify-between pt-1 border-t">
                          <div className="text-muted-foreground text-[11px] flex flex-wrap gap-x-3">
                            {tpl.format_fingerprint && (
                              <span className="font-mono" title={tpl.format_fingerprint}>
                                指纹: {tpl.format_fingerprint.slice(0, 8)}...
                              </span>
                            )}
                            {tpl.document_schema ? (
                              <>
                                <span>元数据: {tpl.document_schema.page_layout?.metadata_pages?.length || 0} 页</span>
                                <span>数据: {tpl.document_schema.page_layout?.data_pages?.length || 0} 页</span>
                              </>
                            ) : (
                              <>
                                <span>表头行: {tpl.header_row}</span>
                                <span>数据起始行: {tpl.data_start_row}</span>
                              </>
                            )}
                            <span>创建: {new Date(tpl.created_at).toLocaleDateString("zh-CN")}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => openEdit(tpl)}>
                              <Pencil className="h-3 w-3 mr-1" />
                              编辑
                            </Button>
                            <Button
                              variant={tpl.is_active ? "outline" : "default"}
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => handleToggleActive(tpl)}
                            >
                              {tpl.is_active ? "停用" : "启用"}
                            </Button>
                          </div>
                        </div>
                      </div>
                    </CollapsibleContent>
                  </Card>
                </Collapsible>
              );
            })}
          </div>
        )}

        {/* ── Edit Dialog ── */}
        <Dialog open={!!editingTpl} onOpenChange={(open) => !open && setEditingTpl(null)}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>编辑模板</DialogTitle>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <div>
                <Label className="text-xs">模板名称 *</Label>
                <Input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">来源公司</Label>
                <Input
                  value={editCompany}
                  onChange={(e) => setEditCompany(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">匹配关键词（逗号分隔）</Label>
                <Input
                  value={editKeywords}
                  onChange={(e) => setEditKeywords(e.target.value)}
                  placeholder="ROYAL CARIBBEAN, RCI, RCCL"
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">备注</Label>
                <Textarea
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  placeholder="模板使用说明、注意事项等"
                  rows={3}
                  className="mt-1"
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" size="sm" onClick={() => setEditingTpl(null)}>取消</Button>
              <Button size="sm" onClick={handleEditSave} disabled={!editName.trim() || editSaving}>
                {editSaving ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />保存中...</> : "保存"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // ─── Create Wizard ───────────────────────────────────────────
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={() => setView("list")}>
          <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
          返回列表
        </Button>
        {/* Step indicator */}
        <div className="flex items-center gap-4">
          {STEPS.map((s) => (
            <div key={s.num} className={cn("flex items-center gap-1.5 text-xs", step === s.num ? "text-primary" : "text-muted-foreground")}>
              <div className={cn(
                "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium",
                step === s.num ? "bg-primary text-primary-foreground" : step > s.num ? "bg-primary/30 text-primary" : "bg-muted text-muted-foreground"
              )}>
                {s.num}
              </div>
              {s.label}
            </div>
          ))}
        </div>
      </div>

      {/* Step 1: Upload */}
      {step === 1 && (
        <div>
          <h4 className="text-sm font-medium mb-3">上传订单文件（Excel / PDF）</h4>
          <FileDropZone onFile={handleFileUpload} maxSizeMB={25} />
          {(loading || schemaAnalyzing) && (
            <div className="flex items-center justify-center gap-2 text-muted-foreground text-xs mt-3">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {schemaAnalyzing ? "PDF Schema 分析中（约 30-40s）..." : fileType === "pdf" ? "AI 分析中，请稍候..." : "解析中..."}
            </div>
          )}
        </div>
      )}

      {/* Step 2: Schema Editor (PDF) or Column Mapping (Excel) */}
      {step === 2 && (documentSchema || parsedSheet) && (
        <div className="space-y-4">
          {/* ── PDF Schema Editor ── */}
          {fileType === "pdf" && documentSchema ? (
            <>
              <h4 className="text-sm font-medium">文档 Schema — {documentSchema.document_type}</h4>

              {/* Page Layout Overview */}
              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span>{documentSchema.page_layout.total_pages} 页</span>
                <span>元数据: {documentSchema.page_layout.metadata_pages.length} 页</span>
                <span>数据: {documentSchema.page_layout.data_pages.length} 页</span>
                <span>条款: {documentSchema.page_layout.terms_pages.length} 页</span>
              </div>

              {/* Attribute Groups */}
              {documentSchema.attribute_groups.map((group, gi) => (
                <Collapsible key={gi} defaultOpen>
                  <Card>
                    <CollapsibleTrigger asChild>
                      <button className="group flex items-center gap-2 w-full px-4 py-3 text-left cursor-pointer">
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-90" />
                        <Badge variant="outline" className={cn(
                          "text-[10px] px-1.5 shrink-0",
                          group.type === "single" ? "text-blue-500 border-blue-500/30" :
                          group.type === "repeating" ? "text-green-500 border-green-500/30" :
                          "text-amber-500 border-amber-500/30"
                        )}>
                          {group.type === "single" ? "单值" : group.type === "repeating" ? "表格" : "文本"}
                        </Badge>
                        <span className="font-medium text-sm">{group.name}</span>
                        <span className="text-xs text-muted-foreground">({group.name_en})</span>
                        {group.type === "repeating" && group.estimated_row_count && (
                          <span className="text-xs text-muted-foreground ml-auto">~{group.estimated_row_count} 行</span>
                        )}
                      </button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="border-t px-4 pb-3 pt-2">
                        <p className="text-xs text-muted-foreground mb-2">{group.description}</p>
                        {/* Single group: attributes with mapping */}
                        {group.type === "single" && group.attributes && (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="text-xs">键名</TableHead>
                                <TableHead className="text-xs">标签</TableHead>
                                <TableHead className="text-xs">类型</TableHead>
                                <TableHead className="text-xs">示例值</TableHead>
                                <TableHead className="text-xs">映射</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {group.attributes.map((attr) => (
                                <TableRow key={attr.key}>
                                  <TableCell className="font-mono text-xs">{attr.key}</TableCell>
                                  <TableCell className="text-xs">{attr.label}</TableCell>
                                  <TableCell className="text-xs text-muted-foreground">{attr.type}</TableCell>
                                  <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">{attr.sample_value || "-"}</TableCell>
                                  <TableCell>
                                    {editedMapping[attr.key] ? (
                                      <Badge variant="secondary" className="text-[10px] gap-1">
                                        <span className="text-green-500">&#10003;</span>
                                        {editedMapping[attr.key]}
                                      </Badge>
                                    ) : (
                                      <span className="text-xs text-muted-foreground">-</span>
                                    )}
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                        {/* Repeating group: columns with mapping */}
                        {group.type === "repeating" && group.columns && (
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="text-xs">列键名</TableHead>
                                <TableHead className="text-xs">列标签</TableHead>
                                <TableHead className="text-xs">类型</TableHead>
                                <TableHead className="text-xs">示例值</TableHead>
                                <TableHead className="text-xs">映射</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {group.columns.map((col) => (
                                <TableRow key={col.key}>
                                  <TableCell className="font-mono text-xs">{col.key}</TableCell>
                                  <TableCell className="text-xs">{col.label}</TableCell>
                                  <TableCell className="text-xs text-muted-foreground">{col.type}</TableCell>
                                  <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">{col.sample_value || "-"}</TableCell>
                                  <TableCell>
                                    {editedMapping[col.key] ? (
                                      <Badge variant="secondary" className="text-[10px] gap-1">
                                        <span className="text-green-500">&#10003;</span>
                                        {editedMapping[col.key]}
                                      </Badge>
                                    ) : (
                                      <span className="text-xs text-muted-foreground">-</span>
                                    )}
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                        {/* Text block group */}
                        {group.type === "text_block" && group.attributes && (
                          <div className="text-xs text-muted-foreground">
                            {group.attributes.map((attr) => (
                              <div key={attr.key}>
                                {attr.label} — 文本块（可在 PDF 中直接查看）
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Card>
                </Collapsible>
              ))}

              {/* Field Mapping Summary */}
              <Card className="border-primary/30">
                <CardContent className="pt-4">
                  <h5 className="text-primary text-xs font-medium mb-2">字段映射摘要</h5>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(editedMapping).map(([schemaKey, stdKey]) => (
                      <Badge key={schemaKey} variant="outline" className="text-[10px] gap-1">
                        <span className="text-green-500">&#10003;</span>
                        {schemaKey} &rarr; {stdKey}
                      </Badge>
                    ))}
                  </div>
                  <p className="text-muted-foreground text-[11px] mt-2">
                    已映射 {Object.keys(editedMapping).length} 个字段（自动推断，提取时自动转为标准格式）
                  </p>
                </CardContent>
              </Card>
            </>
          ) : parsedSheet ? (
            /* ── Excel Column Mapping (original flow) ── */
            <>
              {/* PDF: AI Analysis (legacy path) */}
              {fileType === "pdf" && pdfMetadata && (
                <Card className="border-primary/30">
                  <CardContent className="pt-4">
                    <h5 className="text-primary text-xs font-medium mb-3">AI 识别的文档信息</h5>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                      <div className="text-muted-foreground text-xs">
                        文档类型: <span className="text-foreground ml-1">{pdfMetadata.document_type || "-"}</span>
                      </div>
                      {pdfMetadata.fields.map((field) => (
                        <div key={field.key} className="text-muted-foreground text-xs">
                          {field.label}: <span className="text-foreground ml-1">{field.value || "-"}</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium">列映射 — {parsedSheet.name}</h4>
                <div className="flex items-center gap-2">
                  <Label className="text-xs">字段模式:</Label>
                  <Select
                    value={selectedSchemaId?.toString() || ""}
                    onValueChange={(v) => setSelectedSchemaId(Number(v) || null)}
                  >
                    <SelectTrigger className="h-8 text-xs w-40">
                      <SelectValue placeholder="选择..." />
                    </SelectTrigger>
                    <SelectContent>
                      {fieldSchemas.map((s) => (
                        <SelectItem key={s.id} value={s.id.toString()}>
                          {s.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <Card>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">{fileType === "pdf" ? "列" : "Excel 列"}</TableHead>
                      <TableHead className="text-xs">表头内容</TableHead>
                      <TableHead className="text-xs">映射到字段</TableHead>
                      <TableHead className="text-xs">示例值</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parsedSheet.headers.map((header, i) => (
                      <TableRow key={header.column}>
                        <TableCell className="font-mono text-xs">{header.column}</TableCell>
                        <TableCell className="text-xs">{header.label}</TableCell>
                        <TableCell>
                          <Select
                            value={columnMapping[header.column] || "none"}
                            onValueChange={(v) =>
                              setColumnMapping((prev) => ({
                                ...prev,
                                [header.column]: v === "none" ? "" : v,
                              }))
                            }
                          >
                            <SelectTrigger className="h-7 text-xs">
                              <SelectValue placeholder="-- 不映射 --" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">-- 不映射 --</SelectItem>
                              {fieldOptions.map((f) => (
                                <SelectItem key={f.field_key} value={f.field_key}>
                                  {f.field_label} ({f.field_key})
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs">
                          {parsedSheet.sample_rows[0]?.[i] || "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>

              {/* Sample Data Preview */}
              {parsedSheet.sample_rows.length > 0 && (
                <div>
                  <h5 className="text-muted-foreground text-xs mb-2">
                    数据预览（前 {parsedSheet.sample_rows.length} 行）
                  </h5>
                  <Card>
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            {parsedSheet.headers.map((h) => (
                              <TableHead key={h.column} className="text-xs whitespace-nowrap">
                                {h.label}
                              </TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {parsedSheet.sample_rows.map((row, ri) => (
                            <TableRow key={ri}>
                              {row.map((cell, ci) => (
                                <TableCell key={ci} className="text-xs whitespace-nowrap max-w-[200px] truncate">
                                  {cell || "-"}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </Card>
                </div>
              )}

              {/* PDF: Layout Prompt Editor (legacy path) */}
              {fileType === "pdf" && (
                <div>
                  <Label className="text-xs">AI 布局提示（可编辑，用于后续解析同类文档）</Label>
                  <Textarea
                    value={layoutPrompt}
                    onChange={(e) => setLayoutPrompt(e.target.value)}
                    rows={6}
                    className="mt-1 font-mono text-xs"
                    placeholder="AI 生成的布局描述将显示在此处..."
                  />
                </div>
              )}
            </>
          ) : null}

          <div className="flex justify-end">
            <Button size="sm" onClick={() => setStep(3)}>下一步</Button>
          </div>
        </div>
      )}

      {/* Step 3: Name & Save */}
      {step === 3 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-medium">保存模板</h4>
            {inferring && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                AI 推理中...
              </span>
            )}
          </div>
          <div className="max-w-md space-y-3">
            <div>
              <Label className="text-xs">模板名称 *</Label>
              <Input
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder={fileType === "pdf" ? "例: RCCL Purchase Order 格式" : "例: MSC 标准订单格式"}
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs">来源公司</Label>
              <Input
                value={sourceCompany}
                onChange={(e) => setSourceCompany(e.target.value)}
                placeholder="例: Royal Caribbean"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs">匹配关键词（逗号分隔）</Label>
              <Input
                value={matchKeywords}
                onChange={(e) => setMatchKeywords(e.target.value)}
                placeholder="例: ROYAL CARIBBEAN, RCI, RCCL"
                className="mt-1"
              />
              <p className="text-muted-foreground text-[11px] mt-1">
                上传订单时自动匹配文档中的关键词
              </p>
            </div>
            <div>
              <Label className="text-xs">备注</Label>
              <Textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="模板使用说明、注意事项等"
                rows={3}
                className="mt-1"
              />
            </div>
          </div>
          {fileType === "pdf" && documentSchema && (
            <div className="text-muted-foreground text-xs">
              文件类型: PDF (Schema-first) | {documentSchema.attribute_groups.length} 个属性组
              {" | "}{documentSchema.page_layout.total_pages} 页
              {" | "}{Object.keys(editedMapping).length} 个字段已映射
            </div>
          )}
          {fileType === "pdf" && !documentSchema && (
            <div className="text-muted-foreground text-xs">
              文件类型: PDF | 元数据字段: {pdfMetadata?.fields.length || 0} 个
              {layoutPrompt && " | 含 AI 布局提示"}
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setStep(2)}>上一步</Button>
            <Button size="sm" onClick={handleSave} disabled={!templateName.trim() || loading}>
              {loading ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />保存中...</> : "保存模板"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
