"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { type ColumnDef } from "@tanstack/react-table";
import {
  listOrders,
  uploadOrder,
  deleteOrder,
  type OrderListItem,
  type OrderStatus,
  type FulfillmentStatus,
} from "@/lib/orders-api";
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
import { Plus, FileText, FileSpreadsheet, Trash2 } from "lucide-react";

const PROCESSING_STATUSES: OrderStatus[] = ["uploading", "extracting", "matching"];

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

export default function OrdersPage() {
  const router = useRouter();
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [totalOrders, setTotalOrders] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [fulfillmentFilter, setFulfillmentFilter] = useState("all");
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number } | null>(null);
  const [currentPage, setCurrentPage] = useState(0);

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

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      await uploadOrder(file);
      setShowUpload(false);
      toast.success("订单已上传，后台处理中");
      await fetchOrders();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
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

  const filteredOrders = fulfillmentFilter === "all"
    ? orders
    : orders.filter((o) => o.fulfillment_status === fulfillmentFilter);

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
      <Dialog open={showUpload} onOpenChange={setShowUpload}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>上传订单文件</DialogTitle>
          </DialogHeader>
          <FileDropZone
            onFile={handleUpload}
            accept=".pdf,.xlsx"
            label="拖放 PDF / XLSX 文件到此处"
            disabled={uploading}
          />
          {uploading && (
            <p className="text-xs text-muted-foreground text-center">上传处理中...</p>
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
