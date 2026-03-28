"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { FileDropZone } from "@/components/file-drop-zone";
import type {
  SupplierTemplate,
  CellSheet,
  FieldPositionInfo,
  TemplateAnalysisResult,
  CellClassification,
  Country,
  OrderFormatTemplate,
  FieldMappingPreviewItem,
} from "@/lib/settings-api";
import {
  listSupplierTemplates,
  createSupplierTemplate,
  deleteSupplierTemplate,
  uploadSupplierTemplateFile,
  parseExcelCells,
  analyzeExcelTemplate,
  normalizeFieldPositions,
  listCountries,
  listOrderTemplates,
} from "@/lib/settings-api";
import { listSuppliers, type SupplierItem } from "@/lib/data-api";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/empty-state";
import { ZoneConfigBadge } from "@/components/zone-config-panel";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ArrowLeft, Plus, Trash2, FileText, Loader2, Sparkles, Link2, ZoomIn, ZoomOut, CircleCheck, CircleAlert, MousePointerClick, Upload, CheckCircle2 } from "lucide-react";

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

const STEPS = [
  { num: 1, label: "基本信息" },
  { num: 2, label: "模板配置" },
];

/** Parse "A12" → { col: "A", row: 12 } */
function parseCellRef(ref: string): { col: string; row: number } | null {
  const m = ref.match(/^([A-Z]+)(\d+)$/);
  return m ? { col: m[1], row: parseInt(m[2]) } : null;
}

type LegendType = CellClassification["source_type"] | "product_data";

const LEGEND_ITEMS: { type: LegendType; label: string; dotClass: string }[] = [
  { type: "order",          label: "订单",   dotClass: "bg-red-500" },
  { type: "supplier",       label: "供应商", dotClass: "bg-orange-500" },
  { type: "company",        label: "公司",   dotClass: "bg-blue-500" },
  { type: "formula",        label: "公式",   dotClass: "bg-purple-500" },
  { type: "static",         label: "固定",   dotClass: "bg-gray-400" },
  { type: "product_header", label: "表头",   dotClass: "bg-teal-500" },
  { type: "product_data",   label: "产品",   dotClass: "bg-amber-500" },
];

const SOURCE_TYPE_LABELS: Record<CellClassification["source_type"], string> = {
  order: "订单",
  supplier: "供应商",
  company: "公司",
  formula: "公式",
  static: "固定",
  product_header: "表头",
};

const SOURCE_TYPE_BADGE_CLASSES: Record<CellClassification["source_type"], string> = {
  order: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  supplier: "bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30",
  company: "bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30",
  formula: "bg-purple-500/15 text-purple-600 dark:text-purple-400 border-purple-500/30",
  static: "bg-gray-400/15 text-gray-600 dark:text-gray-400 border-gray-400/30",
  product_header: "bg-teal-500/15 text-teal-600 dark:text-teal-400 border-teal-500/30",
};

export default function SupplierTemplateTab() {
  const [templates, setTemplates] = useState<SupplierTemplate[]>([]);
  const [countries, setCountries] = useState<Country[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierItem[]>([]);
  const [orderTemplates, setOrderTemplates] = useState<OrderFormatTemplate[]>([]);
  const [view, setView] = useState<View>("list");
  const [loading, setLoading] = useState(false);

  // Creation wizard
  const [step, setStep] = useState(1);
  const [templateName, setTemplateName] = useState("");
  const [supplierIds, setSupplierIds] = useState<number[]>([]);
  const [countryId, setCountryId] = useState("");
  const [orderTemplateId, setOrderTemplateId] = useState("");
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
  const [cellMap, setCellMap] = useState<Record<string, CellClassification>>({});
  const uploadedFileRef = useRef<File | null>(null);

  // Field mapping preview (order-context mode)
  const [mappingPreview, setMappingPreview] = useState<FieldMappingPreviewItem[]>([]);

  // Visual editor state (Step 2)
  const [templateHtml, setTemplateHtml] = useState<string>("");
  const [selectedCellRef, setSelectedCellRef] = useState<string | null>(null);
  const [highlightedFieldKey, setHighlightedFieldKey] = useState<string | null>(null);
  const [cellAnnotations, setCellAnnotations] = useState<Record<string, string>>({});
  const [templateStyles, setTemplateStyles] = useState<Record<string, unknown> | null>(null);
  const excelPreviewRef = useRef<HTMLDivElement>(null);
  const excelContainerRef = useRef<HTMLDivElement>(null);
  const [previewScale, setPreviewScale] = useState(1);

  // Legend filter
  const [filterType, setFilterType] = useState<LegendType | null>(null);
  const [productDataCount, setProductDataCount] = useState(0);

  // Auto-scale Excel preview to fit container width
  useEffect(() => {
    if (!templateHtml) return;
    const raf = requestAnimationFrame(() => {
      const inner = excelPreviewRef.current;
      const outer = excelContainerRef.current;
      if (!inner || !outer) return;
      const table = inner.querySelector("table");
      if (!table) return;
      // Measure natural width of the table
      inner.style.transform = "none";
      const tableW = table.scrollWidth;
      const containerW = outer.clientWidth - 16; // minus padding
      const scale = tableW > containerW ? containerW / tableW : 1;
      setPreviewScale(Math.min(scale, 1));
    });
    return () => cancelAnimationFrame(raf);
  }, [templateHtml]);

  // Apply cell coloring based on cellMap + productStartRow + filterType
  useEffect(() => {
    const container = excelPreviewRef.current;
    if (!container) return;

    const startRow = parseInt(productStartRow) || 0;
    let pdCount = 0;

    container.querySelectorAll("td[data-cell-ref]").forEach((td) => {
      td.classList.remove(
        "cell-order", "cell-supplier", "cell-company", "cell-formula",
        "cell-static", "cell-product-header", "cell-product-data", "cell-dimmed",
      );

      const ref = td.getAttribute("data-cell-ref")?.toUpperCase();
      if (!ref) return;

      const mapInfo = cellMap[ref];
      if (mapInfo) {
        td.classList.add(`cell-${mapInfo.source_type.replace("_", "-")}`);
        if (filterType && filterType !== mapInfo.source_type) td.classList.add("cell-dimmed");
      } else {
        const parsed = parseCellRef(ref);
        if (parsed && startRow > 0 && parsed.row >= startRow) {
          td.classList.add("cell-product-data");
          pdCount++;
          if (filterType && filterType !== "product_data") td.classList.add("cell-dimmed");
        } else if (filterType) {
          td.classList.add("cell-dimmed");
        }
      }
    });

    setProductDataCount(pdCount);
  }, [cellMap, templateHtml, filterType, productStartRow]);

  // ─── Computed: legend counts, writable fields, inspector field key ──

  const legendCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const info of Object.values(cellMap)) {
      counts[info.source_type] = (counts[info.source_type] || 0) + 1;
    }
    return counts;
  }, [cellMap]);

  const writableFields = useMemo(() => {
    const fields: { pos: string; info: CellClassification }[] = [];
    for (const [pos, info] of Object.entries(cellMap)) {
      if (info.writable) {
        fields.push({ pos, info });
      }
    }
    fields.sort((a, b) => a.pos.localeCompare(b.pos, undefined, { numeric: true }));
    return fields;
  }, [cellMap]);

  const writableByGroup = useMemo(() => {
    const groups: Record<string, { pos: string; info: CellClassification }[]> = {};
    for (const f of writableFields) {
      const st = f.info.source_type;
      if (!groups[st]) groups[st] = [];
      groups[st].push(f);
    }
    return groups;
  }, [writableFields]);

  const summaryStats = useMemo(() => {
    const total = writableFields.length;
    let mapped = 0;
    for (const { info } of writableFields) {
      if (info.field_key && fieldPositions[info.field_key]) {
        mapped++;
      } else if (info.field_key) {
        // Check if there's a mappingPreview entry
        const mp = mappingPreview.find((m) => m.order_field_key === info.field_key);
        if (mp?.matched_position) mapped++;
      }
    }
    return { total, mapped, pending: total - mapped };
  }, [writableFields, fieldPositions, mappingPreview]);

  /** Derive inspected cell's field_key from selectedCellRef */
  const inspectorFieldKey = useMemo(() => {
    if (!selectedCellRef) return null;
    const info = cellMap[selectedCellRef];
    if (info?.field_key) return info.field_key;
    // Also check fieldPositions reverse lookup
    for (const [k, v] of Object.entries(fieldPositions)) {
      if (v.toUpperCase() === selectedCellRef) return k;
    }
    // Check mapping preview
    for (const item of mappingPreview) {
      if (item.matched_position?.toUpperCase() === selectedCellRef) return item.order_field_key;
    }
    return null;
  }, [selectedCellRef, cellMap, fieldPositions, mappingPreview]);

  /** Is the selected cell in the product data area? */
  const isProductDataCell = useMemo(() => {
    if (!selectedCellRef || cellMap[selectedCellRef]) return false;
    const parsed = parseCellRef(selectedCellRef);
    const startRow = parseInt(productStartRow) || 0;
    return parsed !== null && startRow > 0 && parsed.row >= startRow;
  }, [selectedCellRef, cellMap, productStartRow]);

  /** Which product column field does the selected cell map to? */
  const productColumnField = useMemo(() => {
    if (!selectedCellRef || !isProductDataCell) return null;
    const parsed = parseCellRef(selectedCellRef);
    if (!parsed) return null;
    for (const [fieldKey, colLetter] of Object.entries(productColumns)) {
      if (colLetter.toUpperCase() === parsed.col) return fieldKey;
    }
    if (formulaColumns.some((c) => c.toUpperCase() === parsed.col)) return "__formula__";
    return null;
  }, [selectedCellRef, isProductDataCell, productColumns, formulaColumns]);

  const refresh = useCallback(async () => {
    try {
      const [data, countriesData, suppliersData, orderTplData] = await Promise.all([
        listSupplierTemplates(),
        listCountries(),
        listSuppliers(),
        listOrderTemplates(),
      ]);
      setTemplates(data);
      setCountries(countriesData);
      setSuppliers(suppliersData);
      setOrderTemplates(orderTplData);
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

  const [uploadingId, setUploadingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingUploadIdRef = useRef<number | null>(null);

  const handleUploadFile = (tplId: number) => {
    pendingUploadIdRef.current = tplId;
    fileInputRef.current?.click();
  };

  const onFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const tplId = pendingUploadIdRef.current;
    if (!file || !tplId) return;
    e.target.value = "";

    setUploadingId(tplId);
    try {
      await uploadSupplierTemplateFile(tplId, file);
      await refresh();
      toast.success("模板文件已上传到云存储");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploadingId(null);
      pendingUploadIdRef.current = null;
    }
  };

  const startCreate = () => {
    setView("create");
    setStep(1);
    setTemplateName("");
    setSupplierIds([]);
    setCountryId("");
    setOrderTemplateId("");
    setFileUrl("");
    setCellSheet(null);
    setFieldPositions({});
    setHasProductTable(true);
    setProductStartRow("12");
    setProductColumns({});
    setFormulaColumns([]);
    setAiAnalyzed(false);
    setAiFieldKeys(new Set());
    setCellMap({});
    setMappingPreview([]);
    setTemplateHtml("");
    setSelectedCellRef(null);
    setHighlightedFieldKey(null);
    setCellAnnotations({});
    setFilterType(null);
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

  const handleReAnalyze = async (applySection: "all" | "headers" | "table") => {
    const file = uploadedFileRef.current;
    if (!file) {
      toast.error("请先上传模板文件");
      return;
    }
    setAnalyzing(true);
    try {
      const otId = orderTemplateId ? parseInt(orderTemplateId) : undefined;
      const result: TemplateAnalysisResult = await analyzeExcelTemplate(file, otId);

      if (applySection === "headers" || applySection === "all") {
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

        // Field mapping preview (order-context mode)
        if (result.field_mapping_preview && result.field_mapping_preview.length > 0) {
          setMappingPreview(result.field_mapping_preview);
        } else {
          setMappingPreview([]);
        }
      }

      if (applySection === "table" || applySection === "all") {
        // Auto-fill product table config
        const tableConfig = result.product_table_config;
        if (tableConfig) {
          if (tableConfig.start_row) {
            setProductStartRow(String(tableConfig.start_row));
          }
          if (tableConfig.columns) {
            const newProductColumns: Record<string, string> = {};
            for (const [colLetter, fieldKey] of Object.entries(tableConfig.columns)) {
              newProductColumns[fieldKey] = colLetter;
            }
            setProductColumns(newProductColumns);
          }
          if (tableConfig.formula_columns) {
            setFormulaColumns(tableConfig.formula_columns);
          }
          setHasProductTable(true);
        }
      }

      // Store cell_map
      if (result.cell_map && Object.keys(result.cell_map).length > 0) {
        setCellMap(result.cell_map);
      }

      // Store template_styles (includes zone_config for deterministic engine)
      if (result.template_styles) {
        setTemplateStyles(result.template_styles);
      }

      if (applySection === "all") {
        // Update file_url from analysis result (saved copy)
        if (result.file_url) {
          setFileUrl(result.file_url);
        }

        // Capture template HTML for visual preview
        if (result.template_html) {
          setTemplateHtml(result.template_html);
        }

        setStep(2); // Jump to step 2 for review
      }

      setAiAnalyzed(true);
      const sectionName = applySection === "all" ? "" : applySection === "headers" ? "头部字段" : "产品表格";
      toast.success(applySection === "all" ? "AI 分析完成，已自动填充配置" : `${sectionName}已重新分析`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "AI 分析失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleAiAnalyze = () => handleReAnalyze("all");

  const handleSave = async () => {
    if (!templateName.trim()) return;
    setLoading(true);

    // Build field_positions from either mappingPreview or manual fieldPositions
    const positions: Record<string, FieldPositionInfo> = {};

    if (orderTemplateId && mappingPreview.length > 0) {
      // Order-context mode: build from mapping preview
      for (const item of mappingPreview) {
        if (item.matched_position) {
          positions[item.order_field_key] = {
            position: item.matched_position.trim().toUpperCase(),
            data_type: "string",
            description: item.order_field_label,
          };
        }
      }
      // Also include any extra fieldPositions not covered by preview
      for (const [k, v] of Object.entries(fieldPositions)) {
        if (v.trim() && !positions[k]) {
          const cellInfo = Object.values(cellMap).find((c) => c.field_key === k);
          positions[k] = {
            position: v.trim().toUpperCase(),
            data_type: "string",
            description: cellInfo?.label || k,
          };
        }
      }
    } else {
      // Standard mode: from fieldPositions
      for (const [k, v] of Object.entries(fieldPositions)) {
        if (v.trim()) {
          const cellInfo = Object.values(cellMap).find((c) => c.field_key === k);
          positions[k] = {
            position: v.trim().toUpperCase(),
            data_type: "string",
            description: cellInfo?.label || k,
          };
        }
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

    // Build field_mapping_metadata for provenance
    const hasAnnotations = Object.keys(cellAnnotations).length > 0;
    const mappingMeta: Record<string, unknown> | undefined =
      (orderTemplateId && mappingPreview.length > 0) || hasAnnotations
        ? {
            items: mappingPreview.map((item) => ({
              key: item.order_field_key,
              label: item.order_field_label,
              position: item.matched_position,
              confidence: item.confidence,
              source: item.source,
              note: item.note,
            })),
            ...(hasAnnotations ? { annotations: cellAnnotations } : {}),
          }
        : undefined;

    try {
      await createSupplierTemplate({
        supplier_ids: supplierIds.length > 0 ? supplierIds : undefined,
        country_id: countryId ? parseInt(countryId) : undefined,
        template_name: templateName.trim(),
        template_file_url: fileUrl || undefined,
        field_positions: Object.keys(positions).length > 0 ? positions : undefined,
        has_product_table: hasProductTable,
        product_table_config: tableConfig || undefined,
        order_format_template_id: orderTemplateId ? parseInt(orderTemplateId) : undefined,
        field_mapping_metadata: mappingMeta,
        template_styles: templateStyles || undefined,
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

  /** Find the order template name by id */
  const getOrderTemplateName = (id: number | null) => {
    if (!id) return null;
    return orderTemplates.find((t) => t.id === id)?.name || `ID: ${id}`;
  };

  // ─── Visual Editor Helpers ────────────────────────────────────

  /** Apply interactive state classes (selected, highlighted, annotation dots) */
  useEffect(() => {
    const container = excelPreviewRef.current;
    if (!container || !templateHtml) return;

    const allTds = container.querySelectorAll<HTMLTableCellElement>("td[data-cell-ref]");
    allTds.forEach((td) => {
      const ref = td.getAttribute("data-cell-ref")?.toUpperCase();
      if (!ref) return;

      // Reset interactive classes only (preserve cell-order, cell-supplier, etc.)
      td.classList.remove("cell-selected", "cell-highlighted", "cell-has-note");

      if (selectedCellRef && ref === selectedCellRef.toUpperCase()) {
        td.classList.add("cell-selected");
      }
      if (highlightedFieldKey) {
        // Check if this cell matches the highlighted field
        const cellInfo = cellMap[ref];
        if (cellInfo && (cellInfo.field_key === highlightedFieldKey || ref === highlightedFieldKey)) {
          td.classList.add("cell-highlighted");
        }
      }
      if (cellAnnotations[ref]) {
        td.classList.add("cell-has-note");
      }
    });
  }, [templateHtml, selectedCellRef, highlightedFieldKey, cellAnnotations, cellMap]);

  /** Handle field assignment */
  const handleAssignField = useCallback((cellRef: string, fieldKey: string) => {
    const isClearing = !cellRef;

    // Update mappingPreview
    if (mappingPreview.length > 0) {
      setMappingPreview((prev) =>
        prev.map((item) => {
          // When assigning a cell: clear any other item that pointed to it
          if (!isClearing && item.matched_position?.toUpperCase() === cellRef && item.order_field_key !== fieldKey) {
            return { ...item, matched_position: null, source: "manual" };
          }
          // Assign (or clear) the target field
          if (item.order_field_key === fieldKey) {
            return { ...item, matched_position: isClearing ? null : cellRef, source: "manual" };
          }
          return item;
        }),
      );
    }
    // Update fieldPositions
    setFieldPositions((prev) => {
      const next = { ...prev };
      // When assigning a cell: clear any other field that pointed to it
      if (!isClearing) {
        for (const [k, v] of Object.entries(next)) {
          if (v.toUpperCase() === cellRef && k !== fieldKey) {
            delete next[k];
          }
        }
      }
      if (fieldKey) {
        next[fieldKey] = cellRef; // "" to clear, or "K4" to assign
      }
      return next;
    });
  }, [mappingPreview]);

  /** Handle click on Excel preview cell — simplified: just select */
  const handleCellClick = useCallback((e: React.MouseEvent) => {
    const td = (e.target as HTMLElement).closest("td[data-cell-ref]");
    if (!td) return;
    const ref = td.getAttribute("data-cell-ref");
    if (ref) setSelectedCellRef(ref.toUpperCase());
  }, []);

  /** Save annotation for a cell */
  const handleSaveAnnotation = useCallback((cellRef: string, note: string) => {
    setCellAnnotations((prev) => {
      if (!note.trim()) {
        const next = { ...prev };
        delete next[cellRef];
        return next;
      }
      return { ...prev, [cellRef]: note.trim() };
    });
    // Also save note into mapping preview item
    if (mappingPreview.length > 0) {
      setMappingPreview((prev) =>
        prev.map((item) =>
          item.matched_position?.toUpperCase() === cellRef
            ? { ...item, note: note.trim() || undefined }
            : item,
        ),
      );
    }
  }, [mappingPreview]);

  /** Scroll to a cell in the Excel preview */
  const scrollToCell = useCallback((cellRef: string) => {
    const container = excelPreviewRef.current;
    if (!container) return;
    const td = container.querySelector(`td[data-cell-ref="${cellRef}"]`);
    if (td) {
      td.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    }
  }, []);

  /** Get all available fields (from mapping preview + cellMap writable + POSITION_FIELDS) */
  const allFieldOptions = useCallback(() => {
    const opts: { key: string; label: string }[] = [];
    const seen = new Set<string>();
    for (const item of mappingPreview) {
      if (!seen.has(item.order_field_key)) {
        opts.push({ key: item.order_field_key, label: item.order_field_label });
        seen.add(item.order_field_key);
      }
    }
    for (const info of Object.values(cellMap)) {
      if (info.writable && info.field_key && !seen.has(info.field_key)) {
        opts.push({ key: info.field_key, label: info.label || info.field_key });
        seen.add(info.field_key);
      }
    }
    for (const f of POSITION_FIELDS) {
      if (!seen.has(f.key)) {
        opts.push(f);
        seen.add(f.key);
      }
    }
    return opts;
  }, [mappingPreview, cellMap]);

  // ─── List View ───────────────────────────────────────────────
  if (view === "list") {
    return (
      <div className="space-y-4">
        {/* Hidden file input for template upload */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls"
          className="hidden"
          onChange={onFileSelected}
        />
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
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{tpl.template_name}</span>
                        <ZoneConfigBadge config={tpl.template_styles as Record<string, unknown> | null} templateName={tpl.template_name} />
                      </div>
                      <div className="text-muted-foreground text-xs mt-1">
                        {(tpl.supplier_ids && tpl.supplier_ids.length > 0)
                          ? `供应商: ${tpl.supplier_ids.map((sid) => suppliers.find((s) => s.id === sid)?.name || `#${sid}`).join(", ")}`
                          : tpl.supplier_id
                            ? `供应商: ${suppliers.find((s) => s.id === tpl.supplier_id)?.name || `#${tpl.supplier_id}`}`
                            : "通用模板"}
                        {tpl.country_id && (() => {
                          const country = countries.find((c) => c.id === tpl.country_id);
                          return country ? ` | 国家: ${country.name}` : ` | 国家 ID: ${tpl.country_id}`;
                        })()}
                        {tpl.field_positions && ` | ${Object.keys(tpl.field_positions).length} 个字段位置`}
                        {tpl.has_product_table && " | 含产品表格"}
                      </div>
                      {tpl.order_format_template_id && (
                        <div className="flex items-center gap-1 mt-1.5">
                          <Link2 className="h-3 w-3 text-blue-500" />
                          <span className="text-xs text-blue-600">
                            绑定订单模板: {getOrderTemplateName(tpl.order_format_template_id)}
                          </span>
                        </div>
                      )}
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
                    <div className="flex items-center gap-1 shrink-0">
                      {/* Storage status badge */}
                      {tpl.template_file_url && !tpl.template_file_url.startsWith("/uploads/") ? (
                        <Badge variant="outline" className="text-[10px] border-green-300 text-green-600 gap-1">
                          <CheckCircle2 className="h-3 w-3" />已上传
                        </Badge>
                      ) : tpl.template_file_url ? (
                        <Badge variant="outline" className="text-[10px] border-amber-300 text-amber-600 gap-1">
                          本地文件
                        </Badge>
                      ) : null}

                      {/* Upload button */}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-muted-foreground hover:text-blue-600 h-8 w-8"
                        title="上传模板文件到云存储"
                        onClick={() => handleUploadFile(tpl.id)}
                        disabled={uploadingId === tpl.id}
                      >
                        {uploadingId === tpl.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Upload className="h-3.5 w-3.5" />
                        )}
                      </Button>

                      {/* Delete button */}
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-destructive h-8 w-8">
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
          <div className="grid grid-cols-2 gap-4 max-w-2xl">
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
              <Label className="text-xs">关联供应商（可选，可多选）</Label>
              <div className="mt-1 border border-input rounded-md">
                <div className="max-h-36 overflow-y-auto p-1">
                  {suppliers.length === 0 ? (
                    <p className="text-xs text-muted-foreground px-2 py-1.5">暂无供应商数据</p>
                  ) : (
                    suppliers.map((s) => (
                      <label
                        key={s.id}
                        className={cn(
                          "flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer hover:bg-muted/50",
                          supplierIds.includes(s.id) && "bg-primary/10"
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={supplierIds.includes(s.id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSupplierIds((prev) => [...prev, s.id]);
                            } else {
                              setSupplierIds((prev) => prev.filter((id) => id !== s.id));
                            }
                          }}
                          className="accent-primary"
                        />
                        <span className="truncate">{s.name}</span>
                        {s.country_name && (
                          <span className="text-muted-foreground text-[10px] shrink-0">({s.country_name})</span>
                        )}
                      </label>
                    ))
                  )}
                </div>
                {supplierIds.length > 0 && (
                  <div className="border-t border-input px-2 py-1.5 flex items-center justify-between">
                    <span className="text-[10px] text-muted-foreground">已选 {supplierIds.length} 个供应商</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-5 text-[10px] px-1.5"
                      onClick={() => setSupplierIds([])}
                    >
                      清除
                    </Button>
                  </div>
                )}
              </div>
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
            <div>
              <Label className="text-xs">绑定订单模板（可选）</Label>
              <select
                value={orderTemplateId}
                onChange={(e) => setOrderTemplateId(e.target.value)}
                className="mt-1 flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">不绑定订单模板</option>
                {orderTemplates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}{t.source_company ? ` (${t.source_company})` : ""}</option>
                ))}
              </select>
              {orderTemplateId && (
                <p className="text-[10px] text-blue-600 mt-1">
                  AI 分析时将使用此订单模板的字段列表做精准匹配
                </p>
              )}
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
                  onClick={handleAiAnalyze}
                  disabled={analyzing || !templateName.trim()}
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
              {!templateName.trim() && (
                <p className="text-[11px] text-muted-foreground">请先填写模板名称</p>
              )}
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
        </div>
      )}

      {/* Step 2: Field Position Mapping — Excel-First with Inline Inspector */}
      {step === 2 && (
        <div className="space-y-4">
          {/* ── Summary Bar ── */}
          <div className="flex items-center gap-3 flex-wrap">
            <h4 className="text-sm font-medium">字段位置映射</h4>
            {aiAnalyzed && (
              <Badge variant="secondary" className="text-[10px] gap-1">
                <Sparkles className="h-3 w-3" />
                AI 已分析
              </Badge>
            )}
            {writableFields.length > 0 && (
              <span className="text-xs text-muted-foreground">
                {summaryStats.total} 个可填字段
                <span className="mx-1">·</span>
                <span className="text-green-600 dark:text-green-400">{summaryStats.mapped} 已映射</span>
                {summaryStats.pending > 0 && (
                  <>
                    <span className="mx-1">·</span>
                    <span className="text-orange-600 dark:text-orange-400">{summaryStats.pending} 待映射</span>
                  </>
                )}
              </span>
            )}
            <div className="ml-auto">
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1.5"
                onClick={() => handleReAnalyze("all")}
                disabled={analyzing}
              >
                {analyzing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                重新分析
              </Button>
            </div>
          </div>

          {/* ── Split layout: left = Excel preview, right = Inspector + Checklist ── */}
          <div className="flex gap-4" style={{ minHeight: 480 }}>

            {/* LEFT: Legend + Zoom + Excel Preview */}
            <div ref={excelContainerRef} className="flex-[3] min-w-0 border border-border rounded-lg overflow-hidden bg-card flex flex-col">
              {templateHtml ? (
                <>
                  {/* Legend pills + Zoom toolbar */}
                  <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-muted/30 gap-2">
                    {/* Legend pills */}
                    <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                      {LEGEND_ITEMS.map(({ type, label, dotClass }) => {
                        const count = type === "product_data" ? productDataCount : (legendCounts[type] || 0);
                        if (count === 0) return null;
                        const isActive = filterType === type;
                        return (
                          <button
                            key={type}
                            type="button"
                            className={cn(
                              "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] transition-colors border",
                              isActive
                                ? "bg-foreground/10 border-foreground/20 text-foreground"
                                : "bg-transparent border-transparent text-muted-foreground hover:bg-muted/50"
                            )}
                            onClick={() => setFilterType(isActive ? null : type)}
                          >
                            <span className={cn("w-2 h-2 rounded-full shrink-0", dotClass)} />
                            {label} {count}
                          </button>
                        );
                      })}
                    </div>
                    {/* Zoom controls */}
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => setPreviewScale((s) => Math.max(0.3, s - 0.1))}
                        title="缩小"
                      >
                        <ZoomOut className="h-3.5 w-3.5" />
                      </Button>
                      <button
                        type="button"
                        className="text-[10px] text-muted-foreground font-mono w-10 text-center hover:text-foreground"
                        onClick={() => setPreviewScale(1)}
                        title="重置缩放"
                      >
                        {Math.round(previewScale * 100)}%
                      </button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => setPreviewScale((s) => Math.min(2, s + 0.1))}
                        title="放大"
                      >
                        <ZoomIn className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  {/* Excel preview */}
                  <div className="overflow-auto flex-1" style={{ height: "calc(100vh - 320px)" }}>
                    <div
                      ref={excelPreviewRef}
                      className="excel-preview p-2"
                      onClick={handleCellClick}
                      dangerouslySetInnerHTML={{ __html: templateHtml }}
                      style={{
                        transform: `scale(${previewScale})`,
                        transformOrigin: "top left",
                        width: previewScale < 1 ? `${100 / previewScale}%` : undefined,
                      }}
                    />
                  </div>
                </>
              ) : (
                <div className="h-[520px] flex items-center justify-center text-muted-foreground text-sm">
                  <div className="text-center space-y-2">
                    <FileText className="h-10 w-10 mx-auto opacity-30" />
                    <p>尚未生成模板预览</p>
                    <p className="text-xs">请先在 Step 1 上传 Excel 并运行 AI 分析</p>
                  </div>
                </div>
              )}
            </div>

            {/* RIGHT: Cell Inspector + Writable Fields Checklist */}
            <div className="flex-[2] min-w-[340px] max-w-[440px] shrink-0 border border-border rounded-lg bg-card overflow-hidden flex flex-col">

              {/* ── Cell Inspector ── */}
              <div className="border-b border-border">
                {selectedCellRef ? (
                  (() => {
                    const info = cellMap[selectedCellRef];
                    const currentFieldKey = inspectorFieldKey;
                    const currentNote = cellAnnotations[selectedCellRef] || "";
                    const cellContent = (() => {
                      // Try to get content from the DOM
                      const td = excelPreviewRef.current?.querySelector(`td[data-cell-ref="${selectedCellRef}"]`);
                      return td?.textContent || "";
                    })();

                    return (
                      <div className="p-3 space-y-3">
                        {/* Header row: cell ref + badges */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline" className="font-mono text-xs">{selectedCellRef}</Badge>
                          {info ? (
                            <>
                              <Badge className={cn("text-[10px] border", SOURCE_TYPE_BADGE_CLASSES[info.source_type])}>
                                {SOURCE_TYPE_LABELS[info.source_type]}
                              </Badge>
                              {info.writable && (
                                <Badge className="text-[10px] bg-green-500/15 text-green-600 dark:text-green-400 border border-green-500/30">
                                  需填写
                                </Badge>
                              )}
                            </>
                          ) : isProductDataCell ? (
                            <Badge className="text-[10px] bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30">
                              产品数据
                            </Badge>
                          ) : (
                            <span className="text-[10px] text-muted-foreground">未分类</span>
                          )}
                        </div>

                        {/* Current content */}
                        {cellContent && (
                          <div>
                            <Label className="text-[10px] text-muted-foreground">当前内容</Label>
                            <p className="text-xs mt-0.5 text-foreground/80 truncate" title={cellContent}>{cellContent}</p>
                          </div>
                        )}

                        {/* Formula display */}
                        {info?.formula && (
                          <div>
                            <Label className="text-[10px] text-muted-foreground">公式</Label>
                            <p className="text-xs mt-0.5 font-mono text-purple-500 truncate" title={info.formula}>{info.formula}</p>
                          </div>
                        )}

                        {/* Product column mapping */}
                        {isProductDataCell && (
                          <div>
                            <Label className="text-[10px] text-muted-foreground">列映射</Label>
                            <p className="text-xs mt-0.5 text-foreground/80">
                              {productColumnField === "__formula__"
                                ? "公式列（自动计算）"
                                : productColumnField
                                  ? productColumnField
                                  : "未配置列映射"}
                            </p>
                          </div>
                        )}

                        {/* Mapping select (only for writable cells) */}
                        {info?.writable && (
                          <div>
                            <Label className="text-[10px] text-muted-foreground">映射字段</Label>
                            <Select
                              value={currentFieldKey || "__none__"}
                              onValueChange={(val) => {
                                const newField = val === "__none__" ? "" : val;
                                handleAssignField(newField ? selectedCellRef : "", newField || currentFieldKey || "");
                              }}
                            >
                              <SelectTrigger size="sm" className="mt-0.5 w-full h-8 text-xs">
                                <SelectValue placeholder="（不映射）" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="__none__">（不映射）</SelectItem>
                                {allFieldOptions().map((opt) => (
                                  <SelectItem key={opt.key} value={opt.key}>{opt.label}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        )}

                        {/* Note textarea */}
                        <div>
                          <Label className="text-[10px] text-muted-foreground">备注</Label>
                          <Textarea
                            value={currentNote}
                            onChange={(e) => setCellAnnotations((prev) => ({ ...prev, [selectedCellRef]: e.target.value }))}
                            onBlur={(e) => handleSaveAnnotation(selectedCellRef, e.target.value)}
                            placeholder="如: 小数点后两位、格式 YYYY/MM/DD"
                            rows={2}
                            className="mt-0.5 text-xs min-h-[48px] resize-none"
                          />
                        </div>
                      </div>
                    );
                  })()
                ) : (
                  <div className="p-6 text-center text-muted-foreground">
                    <MousePointerClick className="h-6 w-6 mx-auto mb-2 opacity-40" />
                    <p className="text-xs">点击左侧 Excel 单元格查看详情</p>
                  </div>
                )}
              </div>

              {/* ── Writable Fields Checklist ── */}
              <ScrollArea className="flex-1">
                <div className="p-2">
                  {Object.keys(cellMap).length > 0 ? (
                    <>
                      {/* Grouped writable fields */}
                      {(["order", "supplier", "company"] as CellClassification["source_type"][]).map((type) => {
                        const items = writableByGroup[type];
                        if (!items || items.length === 0) return null;
                        const mappedCount = items.filter(({ info }) => {
                          if (!info.field_key) return false;
                          if (fieldPositions[info.field_key]) return true;
                          const mp = mappingPreview.find((m) => m.order_field_key === info.field_key);
                          return !!mp?.matched_position;
                        }).length;

                        return (
                          <div key={type} className="mb-3">
                            <div className="flex items-center gap-1.5 px-1 py-1 text-[10px] text-muted-foreground font-medium">
                              <span className={cn("w-2 h-2 rounded-full", LEGEND_ITEMS.find((l) => l.type === type)?.dotClass)} />
                              <span>{SOURCE_TYPE_LABELS[type]}字段</span>
                              <span className="ml-auto">{mappedCount}/{items.length}</span>
                            </div>
                            <div className="space-y-0.5">
                              {items.map(({ pos, info }) => {
                                const isMapped = (() => {
                                  if (!info.field_key) return false;
                                  if (fieldPositions[info.field_key]) return true;
                                  const mp = mappingPreview.find((m) => m.order_field_key === info.field_key);
                                  return !!mp?.matched_position;
                                })();

                                return (
                                  <button
                                    key={pos}
                                    type="button"
                                    className={cn(
                                      "w-full flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors text-xs text-left",
                                      selectedCellRef === pos ? "bg-primary/10" : "hover:bg-muted/50"
                                    )}
                                    onClick={() => {
                                      setSelectedCellRef(pos);
                                      scrollToCell(pos);
                                    }}
                                    onMouseEnter={() => setHighlightedFieldKey(info.field_key || pos)}
                                    onMouseLeave={() => setHighlightedFieldKey(null)}
                                  >
                                    {isMapped ? (
                                      <CircleCheck className="h-3.5 w-3.5 text-green-500 shrink-0" />
                                    ) : (
                                      <CircleAlert className="h-3.5 w-3.5 text-orange-500 shrink-0" />
                                    )}
                                    <span className="flex-1 truncate">{info.label || info.field_key || pos}</span>
                                    <Badge variant="outline" className="font-mono text-[9px] h-4 px-1 shrink-0">{pos}</Badge>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}

                      {/* Product table config summary */}
                      {hasProductTable && Object.keys(productColumns).length > 0 && (
                        <div className="mb-3">
                          <div className="flex items-center gap-1.5 px-1 py-1 text-[10px] text-muted-foreground font-medium">
                            <span className="w-2 h-2 rounded-full bg-amber-500" />
                            <span>产品表格</span>
                            <span className="ml-auto">第 {productStartRow} 行起</span>
                          </div>
                          <div className="space-y-0.5">
                            {Object.entries(productColumns).map(([fieldKey, colLetter]) => (
                              <div
                                key={fieldKey}
                                className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-muted-foreground"
                              >
                                <span className="w-3.5 shrink-0" />
                                <span className="flex-1 truncate">{fieldKey}</span>
                                <Badge variant="outline" className="font-mono text-[9px] h-4 px-1 shrink-0">{colLetter}</Badge>
                              </div>
                            ))}
                            {formulaColumns.length > 0 && (
                              <div className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-purple-400">
                                <span className="w-3.5 shrink-0" />
                                <span className="flex-1">公式列</span>
                                <span className="font-mono text-[9px]">{formulaColumns.join(", ")}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    /* ── Fallback: legacy POSITION_FIELDS manual input ── */
                    <div className="space-y-1">
                      <div className="px-1 py-1 text-[10px] text-muted-foreground font-medium">手动输入字段位置</div>
                      {POSITION_FIELDS.map((field) => (
                        <div
                          key={field.key}
                          className="flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors text-xs group hover:bg-muted/50"
                        >
                          <div className={cn(
                            "w-2 h-2 rounded-full shrink-0",
                            fieldPositions[field.key] ? "bg-green-500" : "bg-muted-foreground/30"
                          )} />
                          <span className="flex-1 truncate">{field.label}</span>
                          <Input
                            value={fieldPositions[field.key] ?? ""}
                            onChange={(e) => setFieldPositions((prev) => ({ ...prev, [field.key]: e.target.value.toUpperCase() }))}
                            placeholder="A1"
                            className="h-6 w-14 font-mono text-[10px] shrink-0 text-center"
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          </div>

          {/* Bottom action bar */}
          <div className="flex gap-2 justify-end">
            <Button variant="outline" size="sm" onClick={() => setStep(1)}>上一步</Button>
            <Button size="sm" onClick={handleSave} disabled={loading}>
              {loading ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />保存中...</> : "保存模板"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
