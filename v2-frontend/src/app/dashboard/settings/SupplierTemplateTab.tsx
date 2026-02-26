"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { FileDropZone } from "@/components/file-drop-zone";
import type { SupplierTemplate, CellSheet, FieldPositionInfo, TemplateAnalysisResult, Country } from "@/lib/settings-api";
import {
  listSupplierTemplates,
  createSupplierTemplate,
  deleteSupplierTemplate,
  parseExcelCells,
  analyzeExcelTemplate,
  normalizeFieldPositions,
  listCountries,
} from "@/lib/settings-api";
import { cn } from "@/lib/utils";
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
import { ArrowLeft, Plus, Trash2, FileText, Loader2, Sparkles } from "lucide-react";

type View = "list" | "create";

const POSITION_FIELDS = [
  { key: "po_number", label: "PO番号" },
  { key: "order_date", label: "下单日期" },
  { key: "delivery_date", label: "交货日期" },
  { key: "ship_name", label: "船名" },
  { key: "voyage", label: "航次号" },
  { key: "port_name", label: "港口" },
  { key: "destination", label: "目的地" },
  { key: "supplier_name", label: "供应商名" },
  { key: "invoice", label: "发票号" },
  { key: "currency", label: "币种" },
  { key: "total_amount", label: "合计金额" },
  { key: "payment_date", label: "付款日期" },
  { key: "payment_method", label: "付款方式" },
  { key: "contact_person", label: "联系人" },
  { key: "delivery_address", label: "交货地址" },
];

const PRODUCT_COLUMNS = [
  { key: "line_number", label: "行号" },
  { key: "po_number", label: "PO号" },
  { key: "product_code", label: "商品代码" },
  { key: "product_name_en", label: "英文名" },
  { key: "product_name_jp", label: "日文名" },
  { key: "description", label: "规格/包装" },
  { key: "quantity", label: "数量" },
  { key: "unit", label: "单位" },
  { key: "unit_price", label: "单价" },
  { key: "currency", label: "币种" },
  { key: "total_price", label: "金额" },
];

const STEPS = [
  { num: 1, label: "基本信息" },
  { num: 2, label: "字段映射" },
  { num: 3, label: "产品表格" },
];

export default function SupplierTemplateTab() {
  const [templates, setTemplates] = useState<SupplierTemplate[]>([]);
  const [countries, setCountries] = useState<Country[]>([]);
  const [view, setView] = useState<View>("list");
  const [loading, setLoading] = useState(false);

  // Creation wizard
  const [step, setStep] = useState(1);
  const [templateName, setTemplateName] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [countryId, setCountryId] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [cellSheet, setCellSheet] = useState<CellSheet | null>(null);
  const [fieldPositions, setFieldPositions] = useState<Record<string, string>>({});
  const [hasProductTable, setHasProductTable] = useState(true);
  const [productStartRow, setProductStartRow] = useState("12");
  const [productColumns, setProductColumns] = useState<Record<string, string>>({});
  const [formulaColumns, setFormulaColumns] = useState<string[]>([]);

  // AI analysis state
  const [analyzing, setAnalyzing] = useState(false);
  const [aiAnalyzed, setAiAnalyzed] = useState(false);
  const [aiFieldKeys, setAiFieldKeys] = useState<Set<string>>(new Set());
  const [aiColumnKeys, setAiColumnKeys] = useState<Set<string>>(new Set());
  const uploadedFileRef = useRef<File | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [data, countriesData] = await Promise.all([
        listSupplierTemplates(),
        listCountries(),
      ]);
      setTemplates(data);
      setCountries(countriesData);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleDelete = async (id: number) => {
    try {
      await deleteSupplierTemplate(id);
      await refresh();
      toast.success("已删除");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const startCreate = () => {
    setView("create");
    setStep(1);
    setTemplateName("");
    setSupplierId("");
    setCountryId("");
    setFileUrl("");
    setCellSheet(null);
    setFieldPositions({});
    setHasProductTable(true);
    setProductStartRow("12");
    setProductColumns({});
    setFormulaColumns([]);
    setAiAnalyzed(false);
    setAiFieldKeys(new Set());
    setAiColumnKeys(new Set());
    uploadedFileRef.current = null;
  };

  const handleFileUpload = async (file: File) => {
    uploadedFileRef.current = file;
    setLoading(true);
    try {
      const result = await parseExcelCells(file);
      if (result.sheets.length > 0) {
        setCellSheet(result.sheets[0]);
        setFileUrl(result.file_url);
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "解析失败");
    } finally {
      setLoading(false);
    }
  };

  const handleAiAnalyze = async () => {
    const file = uploadedFileRef.current;
    if (!file) {
      toast.error("请先上传模板文件");
      return;
    }
    setAnalyzing(true);
    try {
      const result: TemplateAnalysisResult = await analyzeExcelTemplate(file);

      // Auto-fill field positions
      const newFieldPositions: Record<string, string> = {};
      const newAiFieldKeys = new Set<string>();
      for (const [key, pos] of Object.entries(result.field_positions)) {
        if (pos && typeof pos === "string") {
          newFieldPositions[key] = pos;
          newAiFieldKeys.add(key);
        }
      }
      setFieldPositions(newFieldPositions);
      setAiFieldKeys(newAiFieldKeys);

      // Auto-fill product table config
      const tableConfig = result.product_table_config;
      if (tableConfig) {
        if (tableConfig.start_row) {
          setProductStartRow(String(tableConfig.start_row));
        }
        if (tableConfig.columns) {
          // Invert columns: AI returns {col_letter: field_key}, we store {field_key: col_letter}
          // Actually our state is {field_key: col_letter} but the save logic inverts it.
          // Let me check the save logic... it saves columns as {col_letter: field_key} in product_table_config.
          // So we need to store in productColumns state the inverted map: {field_key: col_letter}
          const newProductColumns: Record<string, string> = {};
          const newAiColumnKeys = new Set<string>();
          for (const [colLetter, fieldKey] of Object.entries(tableConfig.columns)) {
            newProductColumns[fieldKey] = colLetter;
            newAiColumnKeys.add(fieldKey);
          }
          setProductColumns(newProductColumns);
          setAiColumnKeys(newAiColumnKeys);
        }
        if (tableConfig.formula_columns) {
          setFormulaColumns(tableConfig.formula_columns);
        }
        setHasProductTable(true);
      }

      // Update file_url from analysis result (saved copy)
      if (result.file_url) {
        setFileUrl(result.file_url);
      }

      setAiAnalyzed(true);
      toast.success("AI 分析完成，已自动填充配置");
      setStep(2); // Jump to step 2 for review
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "AI 分析失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSave = async () => {
    if (!templateName.trim()) return;
    setLoading(true);
    const positions: Record<string, FieldPositionInfo> = {};
    for (const [k, v] of Object.entries(fieldPositions)) {
      if (v.trim()) {
        const fieldDef = POSITION_FIELDS.find((f) => f.key === k);
        positions[k] = {
          position: v.trim().toUpperCase(),
          data_type: "string",
          description: fieldDef?.label || k,
        };
      }
    }

    // Build columns map: {col_letter: field_key} for storage
    const columnsMap: Record<string, string> = {};
    for (const [fieldKey, colLetter] of Object.entries(productColumns)) {
      if (colLetter.trim()) columnsMap[colLetter.trim().toUpperCase()] = fieldKey;
    }

    const tableConfig = hasProductTable
      ? {
          start_row: parseInt(productStartRow) || 12,
          columns: columnsMap,
          formula_columns: formulaColumns,
        }
      : null;

    try {
      await createSupplierTemplate({
        supplier_id: supplierId ? parseInt(supplierId) : undefined,
        country_id: countryId ? parseInt(countryId) : undefined,
        template_name: templateName.trim(),
        template_file_url: fileUrl || undefined,
        field_positions: Object.keys(positions).length > 0 ? positions : undefined,
        has_product_table: hasProductTable,
        product_table_config: tableConfig || undefined,
      });
      await refresh();
      setView("list");
      toast.success("模板已保存");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setLoading(false);
    }
  };

  // ─── List View ───────────────────────────────────────────────
  if (view === "list") {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">供应商模板</h3>
          <Button size="sm" onClick={startCreate}>
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            新建模板
          </Button>
        </div>

        {templates.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="暂无供应商模板"
            description="创建供应商询价模板以标准化报价流程"
            action={<Button size="sm" onClick={startCreate}>新建模板</Button>}
          />
        ) : (
          <div className="grid gap-3">
            {templates.map((tpl) => (
              <Card key={tpl.id} className="hover:border-border transition-colors">
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <span className="font-medium text-sm">{tpl.template_name}</span>
                      <div className="text-muted-foreground text-xs mt-1">
                        {tpl.supplier_id ? `供应商 ID: ${tpl.supplier_id}` : "通用模板"}
                        {tpl.country_id && (() => {
                          const country = countries.find((c) => c.id === tpl.country_id);
                          return country ? ` | 国家: ${country.name}` : ` | 国家 ID: ${tpl.country_id}`;
                        })()}
                        {tpl.field_positions && ` | ${Object.keys(tpl.field_positions).length} 个字段位置`}
                        {tpl.has_product_table && " | 含产品表格"}
                        {tpl.template_file_url && " | 有模板文件"}
                      </div>
                      {tpl.field_positions && Object.keys(tpl.field_positions).length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {Object.entries(normalizeFieldPositions(tpl.field_positions)).map(([key, info]) => (
                            <Badge key={key} variant="secondary" className="text-[10px] font-mono" title={info.description || key}>
                              {key}: {info.position}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive h-8 w-8 shrink-0">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>确定删除？</AlertDialogTitle>
                          <AlertDialogDescription>
                            将删除供应商模板「{tpl.template_name}」。此操作不可撤销。
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>取消</AlertDialogCancel>
                          <AlertDialogAction onClick={() => handleDelete(tpl.id)}>删除</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
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

      {/* Step 1: Basic Info + Upload */}
      {step === 1 && (
        <div className="space-y-4">
          <h4 className="text-sm font-medium">基本信息</h4>
          <div className="grid grid-cols-3 gap-4 max-w-2xl">
            <div>
              <Label className="text-xs">模板名称</Label>
              <Input
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder="例: ABC Trading 询价模板"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs">供应商 ID（可选）</Label>
              <Input
                value={supplierId}
                onChange={(e) => setSupplierId(e.target.value)}
                placeholder="关联的供应商 ID"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs">关联国家（可选）</Label>
              <select
                value={countryId}
                onChange={(e) => setCountryId(e.target.value)}
                className="mt-1 flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">不关联国家</option>
                {countries.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <Label className="text-xs mb-2 block">上传询价模板 Excel（可选）</Label>
            <FileDropZone
              onFile={handleFileUpload}
              accept=".xlsx,.pdf"
              label="拖拽供应商的询价模板 .xlsx / .pdf 文件"
            />
            {loading && (
              <div className="flex items-center justify-center gap-2 text-muted-foreground text-xs mt-3">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                解析中...
              </div>
            )}
          </div>

          {/* Parsed cells preview + AI analyze button */}
          {cellSheet && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h5 className="text-muted-foreground text-xs">
                  模板内容预览（{cellSheet.cells.length} 个非空单元格）
                </h5>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleAiAnalyze}
                  disabled={analyzing}
                  className="gap-1.5"
                >
                  {analyzing ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      AI 分析模板结构中...
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-3.5 w-3.5" />
                      AI 智能分析
                    </>
                  )}
                </Button>
              </div>
              <Card>
                <div className="max-h-48 overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs sticky top-0 bg-card">位置</TableHead>
                        <TableHead className="text-xs sticky top-0 bg-card">内容</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cellSheet.cells.slice(0, 30).map((cell) => (
                        <TableRow key={cell.position}>
                          <TableCell className="font-mono text-xs">{cell.position}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{cell.value}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </Card>
            </div>
          )}

          <div className="flex justify-end">
            <Button size="sm" onClick={() => setStep(2)} disabled={!templateName.trim()}>
              下一步
            </Button>
          </div>
        </div>
      )}

      {/* Step 2: Field Position Mapping */}
      {step === 2 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-medium">字段位置映射</h4>
            {aiAnalyzed && (
              <Badge variant="secondary" className="text-[10px] gap-1">
                <Sparkles className="h-3 w-3" />
                AI 已分析
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            指定每个字段在模板中的单元格位置（如 A4, B8）
            {aiAnalyzed && "。AI 建议的值已自动填入，您可以微调。"}
          </p>

          <Card className="max-w-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">字段</TableHead>
                  <TableHead className="text-xs">单元格位置</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {POSITION_FIELDS.map((field) => (
                  <TableRow key={field.key}>
                    <TableCell className="text-xs">
                      {field.label}
                      {aiFieldKeys.has(field.key) && (
                        <Badge variant="outline" className="ml-1.5 text-[9px] px-1 py-0 text-orange-500 border-orange-300">
                          AI
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Input
                        value={fieldPositions[field.key] || ""}
                        onChange={(e) =>
                          setFieldPositions((prev) => ({
                            ...prev,
                            [field.key]: e.target.value,
                          }))
                        }
                        placeholder="例: A4"
                        className="h-7 w-20 font-mono text-xs"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          <div className="flex gap-2 justify-end">
            <Button variant="outline" size="sm" onClick={() => setStep(1)}>上一步</Button>
            <Button size="sm" onClick={() => setStep(3)}>下一步</Button>
          </div>
        </div>
      )}

      {/* Step 3: Product Table Config */}
      {step === 3 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-medium">产品表格配置</h4>
            {aiAnalyzed && (
              <Badge variant="secondary" className="text-[10px] gap-1">
                <Sparkles className="h-3 w-3" />
                AI 已分析
              </Badge>
            )}
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={hasProductTable}
              onChange={(e) => setHasProductTable(e.target.checked)}
              className="accent-primary"
            />
            模板包含产品明细表格
          </label>

          {hasProductTable && (
            <div className="space-y-4 pl-6">
              <div className="max-w-xs">
                <Label className="text-xs">产品表格起始行</Label>
                <Input
                  value={productStartRow}
                  onChange={(e) => setProductStartRow(e.target.value)}
                  placeholder="12"
                  className="w-20 font-mono mt-1"
                />
              </div>

              {formulaColumns.length > 0 && (
                <div>
                  <Label className="text-xs mb-1.5 block">公式列（填充时跳过）</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {formulaColumns.map((col) => (
                      <Badge key={col} variant="outline" className="font-mono text-[10px] text-amber-600 border-amber-300">
                        {col} 列 (公式)
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <Label className="text-xs mb-2 block">列映射（指定每个字段在产品表格中的列）</Label>
                <Card className="max-w-lg">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">字段</TableHead>
                        <TableHead className="text-xs">列</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {PRODUCT_COLUMNS.map((col) => (
                        <TableRow key={col.key}>
                          <TableCell className="text-xs">
                            {col.label}
                            <span className="text-muted-foreground ml-1 font-mono text-[10px]">({col.key})</span>
                            {aiColumnKeys.has(col.key) && (
                              <Badge variant="outline" className="ml-1.5 text-[9px] px-1 py-0 text-orange-500 border-orange-300">
                                AI
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            <Input
                              value={productColumns[col.key] || ""}
                              onChange={(e) =>
                                setProductColumns((prev) => ({
                                  ...prev,
                                  [col.key]: e.target.value,
                                }))
                              }
                              placeholder="例: A"
                              className="h-7 w-16 font-mono text-xs"
                            />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Card>
              </div>
            </div>
          )}

          <div className="flex gap-2 justify-end">
            <Button variant="outline" size="sm" onClick={() => setStep(2)}>上一步</Button>
            <Button size="sm" onClick={handleSave} disabled={loading}>
              {loading ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />保存中...</> : "保存模板"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
