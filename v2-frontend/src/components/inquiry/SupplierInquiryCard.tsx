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
  FileSpreadsheet,
  Loader2,
  RotateCw,
  XCircle,
} from "lucide-react";
import type { SupplierInquiryData, VerifyResult } from "@/lib/orders-api";
import type { SupplierTemplate } from "@/lib/settings-api";

const SELECTION_METHOD_LABELS: Record<string, string> = {
  exact: "精确绑定",
  user_selected: "手动选择",
  agent_selected: "Agent 选择",
  supplier: "供应商匹配",
  country: "国家匹配",
  single: "唯一模板",
  none: "通用格式",
  candidates: "候选列表",
  generic: "通用格式",
};

export interface SupplierInquiryCardProps {
  supplierId: number;
  data: SupplierInquiryData;
  allTemplates: SupplierTemplate[];
  selectedTemplateId: number | null;
  onTemplateChange: (templateId: number | null) => void;
  onPreview: () => void;
  onDownload: (filename: string) => void;
  onRedo: () => void;
  downloadingFile: string | null;
  expanded: boolean;
  onToggle: () => void;
}

export default function SupplierInquiryCard({
  supplierId,
  data,
  allTemplates,
  selectedTemplateId,
  onTemplateChange,
  onPreview,
  onDownload,
  onRedo,
  downloadingFile,
  expanded,
  onToggle,
}: SupplierInquiryCardProps) {
  const file = data.file;
  const template = data.template;
  const verifyResults = data.verify_results || [];
  const passCount = verifyResults.filter((r) => r.status === "pass").length;
  const failCount = verifyResults.filter((r) => r.status === "fail").length;

  const statusConfig = {
    completed: { label: "完成", variant: "default" as const, color: "border-emerald-500" },
    pending: { label: "待生成", variant: "outline" as const, color: "border-muted-foreground/30" },
    generating: { label: "生成中", variant: "secondary" as const, color: "border-blue-500" },
    error: { label: "失败", variant: "destructive" as const, color: "border-destructive" },
  };

  const sc = statusConfig[data.status] || statusConfig.pending;
  const isCompleted = data.status === "completed";
  // Template selector is always editable — user can change then click "重做"
  const canChangeTemplate = data.status !== "generating";

  // Resolve display template name
  const templateName = template?.name
    || (template?.method ? SELECTION_METHOD_LABELS[template.method] : null)
    || (template?.selection_method ? SELECTION_METHOD_LABELS[template.selection_method] : null)
    || "通用格式";

  return (
    <div
      className={`rounded-lg border-2 transition-all ${sc.color} ${
        expanded ? "col-span-full" : ""
      } ${!expanded ? "cursor-pointer hover:shadow-md hover:border-primary/30" : ""}`}
      onClick={expanded ? undefined : onToggle}
    >
      {/* ── Collapsed content (always shown) ── */}
      <div className={`p-4 ${expanded ? "cursor-pointer hover:bg-muted/30" : ""}`} onClick={expanded ? onToggle : undefined}>
        {/* Status badge */}
        <div className="mb-2">
          <Badge variant={sc.variant} className="text-[10px] h-5 px-2">
            {sc.label}
          </Badge>
        </div>

        {/* Supplier name — full display, multi-line */}
        <h3 className="text-sm font-medium leading-snug break-words">
          {data.supplier_name || `供应商 #${supplierId}`}
        </h3>

        {/* Summary row */}
        <div className="text-xs text-muted-foreground mt-1.5 flex items-center gap-1.5 flex-wrap">
          <span>{data.product_count ?? file?.product_count ?? 0} 产品</span>
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

        {/* Template tag */}
        <div className="mt-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] bg-muted text-muted-foreground">
            #{templateName}
          </span>
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
                  value={selectedTemplateId != null ? String(selectedTemplateId) : "generic"}
                  onValueChange={(val) => onTemplateChange(val === "generic" ? null : Number(val))}
                >
                  <SelectTrigger className="h-7 text-xs max-w-[240px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="generic">通用格式</SelectItem>
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
            {template?.method && (
              <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                {SELECTION_METHOD_LABELS[template.method] || template.method}
              </span>
            )}
          </div>

          {/* Missing fields warning */}
          {data.missing_fields && data.missing_fields.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 rounded-md px-3 py-2">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span>
                缺少:{" "}
                {data.missing_fields
                  .map((f: string) =>
                    ({ contact: "联系人", email: "邮箱", phone: "电话" }[f] || f)
                  )
                  .join("、")}
              </span>
            </div>
          )}

          {/* Error message */}
          {data.error && (
            <div className="flex items-start gap-1.5 text-xs text-destructive bg-destructive/5 rounded-md px-3 py-2">
              <XCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span className="break-all">{data.error}</span>
            </div>
          )}

          {/* Verify results */}
          {verifyResults.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs text-muted-foreground flex items-center gap-2">
                <span>验证:</span>
                {passCount > 0 && (
                  <span className="flex items-center gap-0.5 text-emerald-600">
                    <CheckCircle2 className="h-3 w-3" /> {passCount} pass
                  </span>
                )}
                {failCount > 0 && (
                  <span className="flex items-center gap-0.5 text-destructive">
                    <XCircle className="h-3 w-3" /> {failCount} fail
                  </span>
                )}
              </div>
              {failCount > 0 && (
                <div className="space-y-1">
                  {verifyResults
                    .filter((r) => r.status === "fail")
                    .map((r, j) => (
                      <div
                        key={j}
                        className="text-[10px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-2 py-1"
                      >
                        <span className="font-mono">{r.cell}</span>: {r.reason}
                        {r.suggestion && (
                          <span className="text-muted-foreground ml-1">
                            (建议: {r.suggestion})
                          </span>
                        )}
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-1">
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
