"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { type ColumnDef } from "@tanstack/react-table";
import {
  listOrders,
  uploadOrder,
  getOrder,
  deleteOrder,
  setOrderTemplate,
  type OrderListItem,
  type OrderStatus,
  type FulfillmentStatus,
} from "@/lib/orders-api";
import { listOrderTemplates, type OrderFormatTemplate } from "@/lib/settings-api";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge, ReviewedBadge } from "@/components/status-badge";
import { EmptyState } from "@/components/empty-state";
import { FileDropZone } from "@/components/file-drop-zone";
import { Button } from "@/components/ui/button";
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
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Plus, FileText, FileSpreadsheet, Trash2, Check, Loader2, AlertCircle } from "lucide-react";

const PROCESSING_STATUSES: OrderStatus[] = ["uploading", "pending_template", "extracting", "matching"];

const FULFILLMENT_LABELS: Record<string, string> = {
  pending: "待处理",
  inquiry_sent: "已询价",
  quoted: "已报价",
  confirmed: "已确认",
  delivering: "运送中",
  delivered: "已交货",
  invoiced: "已开票",
  paid: "已付款",
};

const FULFILLMENT_COLORS: Record<string, string> = {
  pending: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  inquiry_sent: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  quoted: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
  confirmed: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300",
  delivering: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
  delivered: "bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300",
  invoiced: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300",
  paid: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
};

const formatTime = (iso: string) =>
  new Date(iso).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

const ORDERS_PAGE_SIZE = 20;

const UPLOAD_STEPS = [
  { key: "uploading", label: "上传文件", desc: "解析文件格式..." },
  { key: "pending_template", label: "选择模板", desc: "请选择订单模板以优化提取质量" },
  { key: "extracting", label: "提取数据", desc: "AI 识别订单信息与产品列表..." },
  { key: "matching", label: "产品匹配", desc: "与数据库产品进行匹配..." },
  { key: "ready", label: "处理完成", desc: "" },
] as const;

function UploadProgressTracker({
  status,
  error,
  failedStep,
  productCount,
  matchRate,
  templates,
  selectedTemplateId,
  onSelectTemplate,
  onConfirmTemplate,
  confirmingTemplate,
}: {
  status: OrderStatus;
  error: string | null;
  failedStep: OrderStatus;
  productCount: number | null;
  matchRate: number | null;
  templates?: OrderFormatTemplate[];
  selectedTemplateId?: string;
  onSelectTemplate?: (id: string) => void;
  onConfirmTemplate?: () => void;
  confirmingTemplate?: boolean;
}) {
  const isError = status === "error";
  const isDone = status === "ready";
  const isPendingTemplate = status === "pending_template";
  // For error state, use failedStep to determine which step failed
  const effectiveStatus = isError ? failedStep : status;
  const stepIndex = UPLOAD_STEPS.findIndex((s) => s.key === effectiveStatus);

  return (
    <div className="py-2 space-y-3">
      {UPLOAD_STEPS.map((step, i) => {
        const isStepCompleted = stepIndex > i;
        const isStepCurrent = stepIndex === i;
        const isStepFailed = isError && isStepCurrent;
        const isTemplateStep = step.key === "pending_template" && isPendingTemplate;

        return (
          <div key={step.key} className="flex items-start gap-3">
            {/* Step indicator */}
            <div className="mt-0.5 shrink-0">
              {isStepFailed ? (
                <div className="h-5 w-5 rounded-full bg-destructive flex items-center justify-center">
                  <AlertCircle className="h-3 w-3 text-white" />
                </div>
              ) : isStepCompleted || (isDone && i === UPLOAD_STEPS.length - 1) ? (
                <div className="h-5 w-5 rounded-full bg-emerald-500 flex items-center justify-center">
                  <Check className="h-3 w-3 text-white" />
                </div>
              ) : isTemplateStep ? (
                <div className="h-5 w-5 rounded-full bg-amber-500 flex items-center justify-center">
                  <AlertCircle className="h-3 w-3 text-white" />
                </div>
              ) : isStepCurrent && !isDone ? (
                <div className="h-5 w-5 rounded-full bg-primary flex items-center justify-center">
                  <Loader2 className="h-3 w-3 text-white animate-spin" />
                </div>
              ) : (
                <div className="h-5 w-5 rounded-full border-2 border-muted" />
              )}
            </div>
            {/* Step text */}
            <div className="min-w-0 flex-1">
              <p className={`text-sm font-medium ${
                isStepFailed
                  ? "text-destructive"
                  : isStepCompleted || (isDone && i === UPLOAD_STEPS.length - 1)
                    ? "text-emerald-600 dark:text-emerald-400"
                    : isTemplateStep
                      ? "text-amber-600 dark:text-amber-400"
                      : isStepCurrent && !isDone
                        ? "text-foreground"
                        : "text-muted-foreground"
              }`}>
                {step.label}
                {/* Show extra info for completed steps */}
                {isStepCompleted && step.key === "extracting" && productCount != null && (
                  <span className="font-normal text-xs text-muted-foreground ml-2">
                    {productCount} 个产品
                  </span>
                )}
                {(isStepCompleted || isDone) && step.key === "matching" && matchRate != null && (
                  <span className="font-normal text-xs text-muted-foreground ml-2">
                    匹配率 {matchRate}%
                  </span>
                )}
              </p>
              {/* Template selection UI */}
              {isTemplateStep && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-muted-foreground">
                    未匹配到订单模板，请选择一个模板以确保大 PDF 提取准确
                  </p>
                  {(templates || []).length === 0 ? (
                    <p className="text-xs text-amber-600 dark:text-amber-400">
                      暂无可用的 PDF 模板，请先在设置中创建订单模板
                    </p>
                  ) : (
                    <>
                      <Select value={selectedTemplateId} onValueChange={onSelectTemplate}>
                        <SelectTrigger className="w-full h-8 text-xs">
                          <SelectValue placeholder="请选择订单模板" />
                        </SelectTrigger>
                        <SelectContent>
                          {templates!.map((t) => (
                            <SelectItem key={t.id} value={String(t.id)}>
                              {t.name}{t.source_company ? ` — ${t.source_company}` : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        size="sm"
                        className="w-full"
                        disabled={!selectedTemplateId || confirmingTemplate}
                        onClick={onConfirmTemplate}
                      >
                        {confirmingTemplate ? (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        确认并继续处理
                      </Button>
                    </>
                  )}
                </div>
              )}
              {isStepCurrent && !isDone && !isError && !isTemplateStep && step.desc && (
                <p className="text-xs text-muted-foreground mt-0.5">{step.desc}</p>
              )}
              {isStepFailed && error && (
                <p className="text-xs text-destructive mt-0.5">{error}</p>
              )}
            </div>
          </div>
        );
      })}

      {/* Progress bar */}
      <div className="pt-1">
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ease-out ${
              isError ? "bg-destructive" : isDone ? "bg-emerald-500" : isPendingTemplate ? "bg-amber-500" : "bg-primary"
            }`}
            style={{
              width: isError
                ? `${((stepIndex + 1) / UPLOAD_STEPS.length) * 100}%`
                : `${((isDone ? UPLOAD_STEPS.length : stepIndex + 0.5) / UPLOAD_STEPS.length) * 100}%`,
            }}
          />
        </div>
      </div>
    </div>
  );
}

export default function OrdersPage() {
  const router = useRouter();
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [totalOrders, setTotalOrders] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [fulfillmentFilter, setFulfillmentFilter] = useState("all");
  const [countryFilter, setCountryFilter] = useState("all");
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadOrderId, setUploadOrderId] = useState<number | null>(null);
  const [uploadStatus, setUploadStatus] = useState<OrderStatus>("uploading");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadFailedStep, setUploadFailedStep] = useState<OrderStatus>("uploading");
  const [uploadProductCount, setUploadProductCount] = useState<number | null>(null);
  const [uploadMatchRate, setUploadMatchRate] = useState<number | null>(null);
  const uploadPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number } | null>(null);
  const [currentPage, setCurrentPage] = useState(0);
  // Template selection for pending_template state
  const [pendingTemplateOrderId, setPendingTemplateOrderId] = useState<number | null>(null);
  const [availableTemplates, setAvailableTemplates] = useState<OrderFormatTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [confirmingTemplate, setConfirmingTemplate] = useState(false);

  const fetchOrders = useCallback(async (page?: number) => {
    try {
      const p = page ?? 0;
      const { total, items } = await listOrders({
        status: statusFilter !== "all" ? statusFilter : undefined,
        limit: ORDERS_PAGE_SIZE,
        offset: p * ORDERS_PAGE_SIZE,
      });
      setOrders(items);
      setTotalOrders(total);
    } catch (err) {
      if (process.env.NODE_ENV === "development") console.error("Failed to load orders:", err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    setCurrentPage(0);
    fetchOrders(0);
  }, [fetchOrders]);

  // Polling for processing orders
  useEffect(() => {
    const hasProcessing = orders.some((o) =>
      PROCESSING_STATUSES.includes(o.status)
    );
    if (hasProcessing) {
      if (!pollingRef.current) {
        pollingRef.current = setInterval(() => fetchOrders(currentPage), 2000);
      }
    } else {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [orders, fetchOrders]);

  // Cleanup upload polling on unmount or dialog close
  const stopUploadPolling = useCallback(() => {
    if (uploadPollingRef.current) {
      clearInterval(uploadPollingRef.current);
      uploadPollingRef.current = null;
    }
  }, []);

  const resetUploadState = useCallback(() => {
    stopUploadPolling();
    setUploadOrderId(null);
    setUploadStatus("uploading");
    setUploadError(null);
    setUploadFailedStep("uploading");
    setUploadProductCount(null);
    setUploadMatchRate(null);
    setUploading(false);
    setPendingTemplateOrderId(null);
    setAvailableTemplates([]);
    setSelectedTemplateId("");
    setConfirmingTemplate(false);
  }, [stopUploadPolling]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    setUploadStatus("uploading");
    setUploadProductCount(null);
    setUploadMatchRate(null);
    try {
      const order = await uploadOrder(file);
      setUploadOrderId(order.id);
      setUploadStatus("uploading");
      // Start polling for this specific order
      uploadPollingRef.current = setInterval(async () => {
        try {
          const updated = await getOrder(order.id);
          setUploadStatus(updated.status);
          if (updated.status !== "error") setUploadFailedStep(updated.status);
          if (updated.product_count) setUploadProductCount(updated.product_count);
          if (updated.match_statistics?.match_rate != null) setUploadMatchRate(updated.match_statistics.match_rate);
          if (updated.status === "ready") {
            stopUploadPolling();
            await fetchOrders(currentPage);
            // Auto-close after a short delay to show completion
            setTimeout(() => {
              setShowUpload(false);
              resetUploadState();
            }, 1500);
          } else if (updated.status === "pending_template") {
            stopUploadPolling();
            setPendingTemplateOrderId(order.id);
            // Load available templates for selection
            try {
              const templates = await listOrderTemplates();
              // Only show active PDF templates
              setAvailableTemplates(templates.filter(t => t.is_active && t.file_type === "pdf"));
            } catch {
              setAvailableTemplates([]);
            }
          } else if (updated.status === "error") {
            stopUploadPolling();
            setUploadError(updated.processing_error || "处理失败");
            await fetchOrders(currentPage);
          }
        } catch {
          // polling error, ignore
        }
      }, 1200);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败");
      setUploading(false);
    }
  };

  const handleConfirmTemplate = async () => {
    if (!pendingTemplateOrderId || !selectedTemplateId) return;
    setConfirmingTemplate(true);
    try {
      await setOrderTemplate(pendingTemplateOrderId, Number(selectedTemplateId));
      // Resume polling to track the rest of processing
      setUploadStatus("uploading");
      setPendingTemplateOrderId(null);
      uploadPollingRef.current = setInterval(async () => {
        try {
          const updated = await getOrder(pendingTemplateOrderId);
          setUploadStatus(updated.status);
          if (updated.status !== "error") setUploadFailedStep(updated.status);
          if (updated.product_count) setUploadProductCount(updated.product_count);
          if (updated.match_statistics?.match_rate != null) setUploadMatchRate(updated.match_statistics.match_rate);
          if (updated.status === "ready") {
            stopUploadPolling();
            await fetchOrders(currentPage);
            setTimeout(() => {
              setShowUpload(false);
              resetUploadState();
            }, 1500);
          } else if (updated.status === "error") {
            stopUploadPolling();
            setUploadError(updated.processing_error || "处理失败");
            await fetchOrders(currentPage);
          }
        } catch {
          // polling error, ignore
        }
      }, 1200);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "设置模板失败");
    } finally {
      setConfirmingTemplate(false);
    }
  };

  const handleDelete = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteTarget({ id });
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteOrder(deleteTarget.id);
      setOrders((prev) => prev.filter((o) => o.id !== deleteTarget.id));
      toast.success("订单已删除");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleteTarget(null);
    }
  };

  const countryOptions = Array.from(
    new Set(orders.map((o) => o.country_name).filter(Boolean) as string[])
  ).sort();

  const filteredOrders = orders.filter((o) => {
    if (fulfillmentFilter !== "all" && o.fulfillment_status !== fulfillmentFilter) return false;
    if (countryFilter !== "all" && (o.country_name || "") !== countryFilter) return false;
    return true;
  });

  const columns: ColumnDef<OrderListItem>[] = [
    {
      accessorKey: "filename",
      header: "文件名",
      cell: ({ row }) => (
        <div className="flex items-center gap-2 max-w-[220px]">
          <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="truncate font-medium">{row.original.filename}</span>
          {row.original.is_reviewed && <ReviewedBadge />}
        </div>
      ),
    },
    {
      accessorKey: "order_metadata.po_number",
      header: "PO 号",
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground">
          {row.original.order_metadata?.po_number || "-"}
        </span>
      ),
    },
    {
      accessorKey: "order_metadata.ship_name",
      header: "船名",
      cell: ({ row }) => row.original.order_metadata?.ship_name || "-",
    },
    {
      accessorKey: "country_name",
      header: "国家",
      cell: ({ row }) => row.original.country_name || "-",
    },
    {
      accessorKey: "status",
      header: "处理状态",
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    },
    {
      accessorKey: "fulfillment_status",
      header: "履约状态",
      cell: ({ row }) => {
        const fs = row.original.fulfillment_status || "pending";
        return (
          <Badge variant="secondary" className={`text-[10px] px-1.5 py-0 font-normal ${FULFILLMENT_COLORS[fs] || ""}`}>
            {FULFILLMENT_LABELS[fs] || fs}
          </Badge>
        );
      },
    },
    {
      accessorKey: "product_count",
      header: () => <div className="text-right">产品数</div>,
      cell: ({ row }) => (
        <div className="text-right">{row.original.product_count || "-"}</div>
      ),
    },
    {
      accessorKey: "match_statistics.match_rate",
      header: () => <div className="text-right">匹配率</div>,
      cell: ({ row }) => {
        const rate = row.original.match_statistics?.match_rate;
        if (rate == null) return <div className="text-right text-muted-foreground">-</div>;
        return (
          <div className={`text-right font-medium ${
            rate >= 80 ? "text-emerald-500" : rate >= 50 ? "text-amber-500" : "text-destructive"
          }`}>
            {rate}%
          </div>
        );
      },
    },
    {
      accessorKey: "has_inquiry",
      header: () => <div className="text-center">询价</div>,
      size: 60,
      cell: ({ row }) => (
        <div className="text-center">
          {row.original.has_inquiry ? (
            <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-500 inline-block" />
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </div>
      ),
    },
    {
      accessorKey: "created_at",
      header: "上传时间",
      cell: ({ row }) => (
        <span className="text-muted-foreground">{formatTime(row.original.created_at)}</span>
      ),
    },
    {
      id: "actions",
      header: "",
      size: 50,
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={(e) => handleDelete(row.original.id, e)}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      ),
    },
  ];

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-64" />
        <div className="space-y-2 mt-8">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 px-6 py-4 border-b border-border/50">
        <PageHeader
          title="订单管理"
          description="上传订单文件，系统自动提取、数字化和匹配产品"
          action={
            <Button size="sm" onClick={() => setShowUpload(true)}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              上传订单
            </Button>
          }
        />

        {/* Filters */}
        <div className="flex items-center gap-3 mt-3">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-32 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="ready">已完成</SelectItem>
              <SelectItem value="error">出错</SelectItem>
              <SelectItem value="extracting">处理中</SelectItem>
            </SelectContent>
          </Select>
          <Select value={fulfillmentFilter} onValueChange={setFulfillmentFilter}>
            <SelectTrigger className="w-32 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部履约</SelectItem>
              {Object.entries(FULFILLMENT_LABELS).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={countryFilter} onValueChange={setCountryFilter}>
            <SelectTrigger className="w-32 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部国家</SelectItem>
              {countryOptions.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-muted-foreground text-xs ml-auto">
            {totalOrders} 条订单
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-hidden">
        <DataTable
          columns={columns}
          data={filteredOrders}
          searchKey="filename"
          searchPlaceholder="搜索文件名..."
          pageSize={ORDERS_PAGE_SIZE}
          totalRows={totalOrders}
          onPageChange={(pageIndex) => {
            setCurrentPage(pageIndex);
            fetchOrders(pageIndex);
          }}
          onRowClick={(order) => router.push(`/dashboard/orders/${order.id}`)}
          emptyState={
            <EmptyState
              icon={FileText}
              title="暂无订单"
              description="上传订单文件开始使用"
              action={
                <Button size="sm" variant="outline" onClick={() => setShowUpload(true)}>
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  上传订单
                </Button>
              }
            />
          }
        />
      </div>

      {/* Upload dialog */}
      <Dialog open={showUpload} onOpenChange={(open) => {
        if (!open) {
          resetUploadState();
        }
        setShowUpload(open);
      }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>上传订单文件</DialogTitle>
          </DialogHeader>
          {!uploadOrderId ? (
            <FileDropZone
              onFile={handleUpload}
              accept=".pdf,.xlsx"
              label="拖放 PDF / XLSX 文件到此处"
              disabled={uploading}
              maxSizeMB={25}
            />
          ) : (
            <UploadProgressTracker
              status={uploadStatus}
              error={uploadError}
              failedStep={uploadFailedStep}
              productCount={uploadProductCount}
              matchRate={uploadMatchRate}
              templates={availableTemplates}
              selectedTemplateId={selectedTemplateId}
              onSelectTemplate={setSelectedTemplateId}
              onConfirmTemplate={handleConfirmTemplate}
              confirmingTemplate={confirmingTemplate}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Delete confirm dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除此订单吗？此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
