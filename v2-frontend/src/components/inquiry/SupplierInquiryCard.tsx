"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  Loader2,
  Pencil,
  RotateCw,
  XCircle,
} from "lucide-react";
import type { SupplierReadiness, FieldGap, VerifyResult } from "@/lib/orders-api";
import type { SupplierTemplate } from "@/lib/settings-api";

const SELECTION_METHOD_LABELS: Record<string, string> = {
  exact: "精确绑定",
  user_selected: "手动选择",
  agent_selected: "Agent 选择",
  supplier: "供应商匹配",
  country: "国家匹配",
  single: "唯一模板",
  none: "未绑定模板",
  candidates: "候选列表",
};

const GAP_CATEGORY_LABELS: Record<string, string> = {
  order: "订单",
  supplier: "供应商",
  company: "公司",
  delivery: "交付",
};

export interface SupplierInquiryCardProps {
  supplierId: number;
  data: SupplierReadiness;
  allTemplates: SupplierTemplate[];
  selectedTemplateId: number | null;
  onTemplateChange: (templateId: number | null) => void;
  onPreview: () => void;
  onDataPreview: () => void;
  onDownload: (filename: string) => void;
  onRedo: () => void;
  downloadingFile: string | null;
  expanded: boolean;
  onToggle: () => void;
  /** Inline gap editing: called when user types a value for a missing field */
  onFieldOverride?: (cell: string, value: string) => void;
  /** Current inline override values for this supplier */
  fieldOverrideValues?: Record<string, string>;
  /** Whether overrides are being saved */
  savingOverrides?: boolean;
  /** Inline save feedback text */
  saveFeedback?: string;
  /** Inline save feedback tone */
  saveFeedbackTone?: "idle" | "saving" | "saved" | "error";
}

export default function SupplierInquiryCard({
  supplierId,
  data,
  allTemplates,
  selectedTemplateId,
  onTemplateChange,
  onPreview,
  onDataPreview,
  onDownload,
  onRedo,
  downloadingFile,
  expanded,
  onToggle,
  onFieldOverride,
  fieldOverrideValues = {},
  savingOverrides,
  saveFeedback,
  saveFeedbackTone = "idle",
}: SupplierInquiryCardProps) {
  const file = data.file;
  const template = data.template;
  const verifyResults = data.verify_results || [];
  const passCount = verifyResults.filter((r: VerifyResult) => r.status === "pass").length;
  const failCount = verifyResults.filter((r: VerifyResult) => r.status === "fail").length;
  const gaps = data.gaps || [];
  const blockingGaps = gaps.filter((g: FieldGap) => g.severity === "blocking");
  const warningGaps = gaps.filter((g: FieldGap) => g.severity === "warning");
  const hasGaps = gaps.length > 0;

  // Border color based on readiness status
  const borderColor =
    data.status === "completed" ? "border-emerald-500" :
    data.status === "blocked" ? "border-destructive" :
    data.status === "needs_input" ? "border-amber-500" :
    data.gen_status === "generating" ? "border-blue-500" :
    data.gen_status === "error" ? "border-destructive" :
    "border-muted-foreground/30";

  const statusBadge = (() => {
    if (data.gen_status === "completed") return { label: "完成", variant: "default" as const };
    if (data.gen_status === "generating") return { label: "生成中", variant: "secondary" as const };
    if (data.gen_status === "error") return { label: "失败", variant: "destructive" as const };
    if (data.status === "blocked") {
      const label = data.error?.includes("zone_config 模板") ? "无模板" : "缺必填";
      return { label, variant: "destructive" as const };
    }
    if (data.status === "needs_input") return { label: "需补充", variant: "outline" as const };
    return { label: "待生成", variant: "outline" as const };
  })();

  const isCompleted = data.gen_status === "completed";
  const canChangeTemplate = data.gen_status !== "generating";

  const templateName = template.name
    || (template.method ? SELECTION_METHOD_LABELS[template.method] : null)
    || "未绑定模板";

  /** Render a single gap row with optional inline input */
  function GapRow({ g, variant }: { g: FieldGap; variant: "blocking" | "warning" }) {
    const isBlocking = variant === "blocking";
    const overrideValue = fieldOverrideValues[g.cell] ?? "";
    const isFilled = overrideValue.trim().length > 0;

    return (
      <div
        className={`text-[11px] rounded px-2.5 py-1.5 flex items-center gap-2 ${
          isBlocking
            ? "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400"
            : "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400"
        }`}
      >
        {isBlocking ? (
          <XCircle className="h-3 w-3 shrink-0" />
        ) : (
          <AlertTriangle className="h-3 w-3 shrink-0" />
        )}
        <span className="shrink-0 min-w-[4rem]">{g.label}</span>
        {/* Inline input for filling the gap */}
        {onFieldOverride ? (
          <input
            className={`flex-1 min-w-0 bg-white dark:bg-background border rounded px-1.5 py-0.5 text-[11px] outline-none transition-colors ${
              isFilled
                ? "border-primary/50 text-foreground"
                : "border-border text-muted-foreground"
            } focus:border-primary focus:ring-1 focus:ring-primary/20`}
            placeholder={`输入${g.label}...`}
            value={overrideValue}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onFieldOverride(g.cell, e.target.value)}
          />
        ) : (
          <span className="flex-1 text-muted-foreground/50 italic">未填写</span>
        )}
        <span className="text-[9px] text-muted-foreground/50 shrink-0">
          {GAP_CATEGORY_LABELS[g.category] || g.category}
        </span>
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg border-2 transition-all ${borderColor} ${
        expanded ? "col-span-full" : ""
      } ${!expanded ? "cursor-pointer hover:shadow-md hover:border-primary/30" : ""}`}
      onClick={expanded ? undefined : onToggle}
    >
      {/* ── Collapsed content (always shown) ── */}
      <div className={`p-4 ${expanded ? "cursor-pointer hover:bg-muted/30" : ""}`} onClick={expanded ? onToggle : undefined}>
        {/* Status badges row */}
        <div className="mb-2 flex items-center gap-1.5 flex-wrap">
          <Badge variant={statusBadge.variant} className="text-[10px] h-5 px-2">
            {statusBadge.label}
          </Badge>
          {blockingGaps.length > 0 && (
            <Badge variant="destructive" className="text-[10px] h-5 px-1.5">
              {blockingGaps.length} 必填缺失
            </Badge>
          )}
          {warningGaps.length > 0 && (
            <Badge className="text-[10px] h-5 px-1.5 bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30 hover:bg-amber-500/20">
              {warningGaps.length} 可选缺失
            </Badge>
          )}
          {failCount > 0 && isCompleted && (
            <Badge className="text-[10px] h-5 px-1.5 bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30 hover:bg-red-500/15">
              {failCount} 验证失败
            </Badge>
          )}
        </div>

        {/* Supplier name */}
        <h3 className="text-sm font-medium leading-snug break-words">
          {data.supplier_name || `供应商 #${supplierId}`}
        </h3>

        {/* Summary row */}
        <div className="text-xs text-muted-foreground mt-1.5 flex items-center gap-1.5 flex-wrap">
          <span>{data.product_count ?? 0} 产品</span>
          {data.subtotal != null && data.subtotal > 0 && (
            <>
              <span className="text-muted-foreground/40">&middot;</span>
              <span>{data.currency || "¥"}{data.subtotal.toLocaleString()}</span>
            </>
          )}
          {isCompleted && data.elapsed_seconds != null && (
            <>
              <span className="text-muted-foreground/40">&middot;</span>
              <span className="flex items-center gap-0.5">
                <Clock className="h-3 w-3" />
                {data.elapsed_seconds}s
              </span>
            </>
          )}
        </div>

        {/* Template tag + readiness indicator */}
        <div className="mt-2 flex items-center gap-1.5">
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] bg-muted text-muted-foreground">
            #{templateName}
          </span>
          {data.gap_summary.total > 0 && (
            <span className="text-[10px] text-muted-foreground">
              {data.gap_summary.resolved}/{data.gap_summary.total} 字段已填
            </span>
          )}
        </div>
      </div>

      {/* ── Expanded content ── */}
      {expanded && (
        <div className="px-4 pb-4 border-t space-y-3">
          {/* Metadata */}
          <div className="text-xs text-muted-foreground pt-3 flex items-center gap-2 flex-wrap">
            <span>供应商 #{supplierId}</span>
            {data.subtotal != null && data.subtotal > 0 && (
              <>
                <span>&middot;</span>
                <span>{data.currency || "¥"}{data.subtotal.toLocaleString()}</span>
              </>
            )}
            {data.elapsed_seconds != null && (
              <>
                <span>&middot;</span>
                <span>{data.elapsed_seconds}s</span>
              </>
            )}
          </div>

          {/* Template selector */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="text-xs text-muted-foreground shrink-0">模板:</span>
              {canChangeTemplate ? (
                <Select
                  value={selectedTemplateId != null ? String(selectedTemplateId) : "__unassigned__"}
                  onValueChange={(val) => {
                    if (val === "__unassigned__") return;
                    onTemplateChange(Number(val));
                  }}
                >
                  <SelectTrigger className="h-7 text-xs max-w-[240px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedTemplateId == null && (
                      <SelectItem value="__unassigned__" disabled>未绑定可用模板</SelectItem>
                    )}
                    {allTemplates.map((t) => (
                      <SelectItem key={t.id} value={String(t.id)}>
                        {t.template_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <span className="text-xs">{templateName}</span>
              )}
            </div>
            {template.method && (
              <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                {SELECTION_METHOD_LABELS[template.method] || template.method}
              </span>
            )}
          </div>

          {/* ── Inline editable gaps (P0: core UX improvement) ── */}
          {hasGaps && (
            <div className="space-y-1.5">
              <div className="text-xs text-muted-foreground flex items-center gap-2">
                <span>缺失字段</span>
                {blockingGaps.length > 0 && (
                  <span className="text-destructive">{blockingGaps.length} 必填</span>
                )}
                {warningGaps.length > 0 && (
                  <span className="text-amber-600 dark:text-amber-400">{warningGaps.length} 可选</span>
                )}
                {saveFeedback && (
                  <span
                    className={`flex items-center gap-1 ${
                      saveFeedbackTone === "error"
                        ? "text-destructive"
                        : saveFeedbackTone === "saved"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-muted-foreground/60"
                    }`}
                  >
                    {saveFeedbackTone === "saving" ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : saveFeedbackTone === "saved" ? (
                      <CheckCircle2 className="h-3 w-3" />
                    ) : saveFeedbackTone === "error" ? (
                      <XCircle className="h-3 w-3" />
                    ) : null}
                    {saveFeedback}
                  </span>
                )}
              </div>
              <div className="space-y-1">
                {blockingGaps.map((g) => <GapRow key={g.cell} g={g} variant="blocking" />)}
                {warningGaps.map((g) => <GapRow key={g.cell} g={g} variant="warning" />)}
              </div>
            </div>
          )}

          {/* Error message */}
          {data.error && (
            <div className="flex items-start gap-1.5 text-xs text-destructive bg-destructive/5 rounded-md px-3 py-2">
              <XCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span className="break-all">{data.error}</span>
            </div>
          )}

          {/* Verify results — label-first, cell ref as secondary */}
          {verifyResults.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs text-muted-foreground flex items-center gap-2">
                <span>验证结果</span>
                {passCount > 0 && (
                  <span className="flex items-center gap-0.5 text-emerald-600">
                    <CheckCircle2 className="h-3 w-3" /> {passCount} 通过
                  </span>
                )}
                {failCount > 0 && (
                  <span className="flex items-center gap-0.5 text-destructive">
                    <XCircle className="h-3 w-3" /> {failCount} 失败
                  </span>
                )}
              </div>
              {failCount > 0 && (
                <div className="space-y-1">
                  {verifyResults
                    .filter((r: VerifyResult) => r.status === "fail")
                    .map((r: VerifyResult, j: number) => (
                      <div
                        key={j}
                        className="text-[11px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-2.5 py-1.5 flex items-center gap-1.5"
                      >
                        <XCircle className="h-3 w-3 shrink-0" />
                        <span>{r.annotation || r.cell}</span>
                        {r.reason && <span className="text-muted-foreground">— {r.reason}</span>}
                        {r.suggestion && (
                          <span className="ml-auto text-emerald-600 dark:text-emerald-400 shrink-0">
                            → {r.suggestion}
                          </span>
                        )}
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-1 flex-wrap">
            {/* P0: Renamed from "数据预览" to "编辑字段", highlighted when blocking gaps exist */}
            <Button
              variant={blockingGaps.length > 0 ? "default" : "outline"}
              size="sm"
              className="text-xs h-7"
              onClick={(e) => {
                e.stopPropagation();
                onDataPreview();
              }}
            >
              <Pencil className="mr-1 h-3 w-3" /> 编辑字段
            </Button>
            {file?.filename && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-xs h-7"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPreview();
                  }}
                >
                  <Eye className="mr-1 h-3 w-3" /> 预览
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-xs h-7"
                  disabled={downloadingFile === file.filename}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDownload(file.filename);
                  }}
                >
                  {downloadingFile === file.filename ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <Download className="mr-1 h-3 w-3" />
                  )}
                  下载
                </Button>
              </>
            )}
            <Button
              variant="outline"
              size="sm"
              className="text-xs h-7"
              onClick={(e) => {
                e.stopPropagation();
                onRedo();
              }}
            >
              <RotateCw className="mr-1 h-3 w-3" /> 重做
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
