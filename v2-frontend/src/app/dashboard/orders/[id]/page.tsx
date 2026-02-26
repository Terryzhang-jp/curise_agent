"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getOrder,
  reviewOrder,
  reprocessOrder,
  runAnomalyCheck,
  runFinancialAnalysis,
  fetchDeliveryEnvironment,
  startGenerateInquiry,
  streamInquiryProgress,
  updateOrder,
  rematchOrder,
  downloadOrderFile,
  type Order,
  type OrderStatus,
  type OrderProduct,
  type InquiryStep,
  type FulfillmentStatus,
  type DeliveryEnvironment,
} from "@/lib/orders-api";
import { StatusBadge, ReviewedBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
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
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import {
  ArrowLeft,
  MoreHorizontal,
  Edit3,
  RefreshCw,
  Shield,
  DollarSign,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Plus,
  Trash2,
  Save,
  X,
  Download,
  Waves,
  CloudSun,
  Clock,
} from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import OrderDataPreview from "@/app/dashboard/workspace/artifacts/OrderDataPreview";
import MatchResultsPreview from "@/app/dashboard/workspace/artifacts/MatchResultsPreview";
import AnomalyPreview from "@/app/dashboard/workspace/artifacts/AnomalyPreview";
import FinancialPreview from "@/app/dashboard/workspace/artifacts/FinancialPreview";

const PROCESSING_STATUSES: OrderStatus[] = ["uploading", "extracting", "matching"];

const FULFILLMENT_STEPS: { key: FulfillmentStatus; label: string }[] = [
  { key: "pending", label: "待处理" },
  { key: "inquiry_sent", label: "已询价" },
  { key: "quoted", label: "已报价" },
  { key: "confirmed", label: "已确认" },
  { key: "delivering", label: "运送中" },
  { key: "delivered", label: "已交货" },
  { key: "invoiced", label: "已开票" },
  { key: "paid", label: "已付款" },
];

export default function OrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const orderId = Number(params.id);

  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
  const [actionLoading, setActionLoading] = useState("");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Edit mode
  const [isEditing, setIsEditing] = useState(false);
  const [editedMetadata, setEditedMetadata] = useState<Record<string, string>>({});
  const [editedProducts, setEditedProducts] = useState<OrderProduct[]>([]);
  const [saving, setSaving] = useState(false);

  // Add meta field dialog
  const [showAddFieldDialog, setShowAddFieldDialog] = useState(false);
  const [newFieldKey, setNewFieldKey] = useState("");

  // Confirm dialogs
  const [showRematchDialog, setShowRematchDialog] = useState(false);
  const [showInquiryOverwriteDialog, setShowInquiryOverwriteDialog] = useState(false);

  // Inquiry streaming
  const [inquiryGenerating, setInquiryGenerating] = useState(false);
  const [inquirySteps, setInquirySteps] = useState<InquiryStep[]>([]);
  const abortInquiryRef = useRef<(() => void) | null>(null);

  const fetchOrder = useCallback(async () => {
    try {
      const data = await getOrder(orderId);
      setOrder(data);
      return data;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
      return null;
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => {
    fetchOrder();
  }, [fetchOrder]);

  // Polling
  useEffect(() => {
    if (order && PROCESSING_STATUSES.includes(order.status)) {
      if (!pollingRef.current) {
        pollingRef.current = setInterval(fetchOrder, 2000);
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
  }, [order?.status, fetchOrder]);

  const handleAction = async (action: string, fn: () => Promise<Order | unknown>) => {
    setActionLoading(action);
    try {
      const result = await fn();
      if (result && typeof result === "object" && "id" in result) {
        setOrder(result as Order);
      } else {
        await fetchOrder();
      }
      toast.success("操作成功");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setActionLoading("");
    }
  };

  // Core metadata fields — always shown in edit mode even if null
  const CORE_META_KEYS = [
    "po_number", "ship_name", "vendor_name", "delivery_date",
    "order_date", "currency", "destination_port", "total_amount",
  ];

  // Edit mode handlers
  function enterEditMode() {
    if (!order) return;
    const meta = order.order_metadata || {};
    const metaStrings: Record<string, string> = {};
    // Ensure core fields always appear
    for (const key of CORE_META_KEYS) {
      metaStrings[key] = meta[key] != null ? String(meta[key]) : "";
    }
    // Add any extra fields from metadata (flatten extra_fields object)
    for (const [k, v] of Object.entries(meta)) {
      if (k === "extra_fields" && v && typeof v === "object") {
        for (const [ek, ev] of Object.entries(v as Record<string, unknown>)) {
          if (!(ek in metaStrings)) {
            metaStrings[ek] = ev != null ? String(ev) : "";
          }
        }
      } else if (!(k in metaStrings)) {
        metaStrings[k] = v != null ? String(v) : "";
      }
    }
    setEditedMetadata(metaStrings);
    setEditedProducts(JSON.parse(JSON.stringify(order.products || [])));
    setIsEditing(true);
  }

  function cancelEdit() {
    setIsEditing(false);
    setEditedMetadata({});
    setEditedProducts([]);
  }

  async function saveEdits() {
    if (!order) return;
    // Validate products
    for (const p of editedProducts) {
      if (!p.product_name || !p.product_name.trim()) {
        toast.error("产品名称不能为空");
        return;
      }
      if (p.quantity != null && Number(p.quantity) < 0) {
        toast.error("产品数量不能为负数");
        return;
      }
    }
    setSaving(true);
    try {
      const cleanMeta: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(editedMetadata)) {
        if (v === "") {
          cleanMeta[k] = null;
        } else {
          const num = Number(v);
          cleanMeta[k] = !isNaN(num) && v.trim() !== "" && k.includes("amount") ? num : v;
        }
      }
      const updated = await updateOrder(order.id, {
        order_metadata: cleanMeta,
        products: editedProducts,
      });
      setOrder(updated);
      setIsEditing(false);
      toast.success("数据已更新");
      setShowRematchDialog(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  // Inquiry streaming handler
  async function handleGenerateInquiry() {
    if (!order) return;
    setInquiryGenerating(true);
    setInquirySteps([]);

    try {
      await startGenerateInquiry(orderId);

      const abort = streamInquiryProgress(
        orderId,
        (step) => {
          setInquirySteps((prev) => [...prev, step]);
        },
        async () => {
          // Done — refresh order data
          await fetchOrder();
          setInquiryGenerating(false);
          setInquirySteps([]);
          toast.success("询价单生成完成");
        },
        (err) => {
          setInquiryGenerating(false);
          toast.error(err.message || "询价单生成失败");
        }
      );
      abortInquiryRef.current = abort;
    } catch (err) {
      setInquiryGenerating(false);
      toast.error(err instanceof Error ? err.message : "启动询价单生成失败");
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortInquiryRef.current) {
        abortInquiryRef.current();
      }
    };
  }, []);

  function updateMetaField(key: string, value: string) {
    setEditedMetadata((prev) => ({ ...prev, [key]: value }));
  }

  function deleteMetaField(key: string) {
    setEditedMetadata((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  function addMetaField() {
    setNewFieldKey("");
    setShowAddFieldDialog(true);
  }

  function confirmAddMetaField() {
    if (!newFieldKey.trim()) return;
    setEditedMetadata((prev) => ({ ...prev, [newFieldKey.trim()]: "" }));
    setShowAddFieldDialog(false);
  }

  function updateProduct(index: number, field: string, value: string) {
    setEditedProducts((prev) => {
      const next = [...prev];
      const rec = next[index] as unknown as Record<string, unknown>;
      const numFields = ["quantity", "unit_price", "total_price", "line_number"];
      if (numFields.includes(field)) {
        const num = Number(value);
        rec[field] = value === "" ? null : isNaN(num) ? value : num;
      } else {
        rec[field] = value;
      }
      return next;
    });
  }

  function deleteProduct(index: number) {
    setEditedProducts((prev) => prev.filter((_, i) => i !== index));
  }

  function addProduct() {
    setEditedProducts((prev) => [
      ...prev,
      { product_name: "", product_code: "", quantity: null, unit: "", unit_price: null, total_price: null },
    ]);
  }

  // Loading state
  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-4 mt-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      </div>
    );
  }

  if (!order) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-destructive">订单不存在</p>
          <Button variant="link" size="sm" onClick={() => router.push("/dashboard/orders")} className="mt-2">
            返回订单列表
          </Button>
        </div>
      </div>
    );
  }

  const metadata = order.order_metadata || {};
  const isProcessing = PROCESSING_STATUSES.includes(order.status);
  const isReady = order.status === "ready";
  const isError = order.status === "error";
  const canEdit = (isReady || isError) && !isEditing;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 px-6 py-4 border-b border-border/50">
        <Button
          variant="ghost"
          size="sm"
          className="mb-2 -ml-2 text-xs h-7"
          onClick={() => router.push("/dashboard/orders")}
        >
          <ArrowLeft className="mr-1 h-3 w-3" />
          返回列表
        </Button>

        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold truncate">{order.filename}</h1>
              <StatusBadge status={order.status} />
              {order.is_reviewed && <ReviewedBadge />}
              {isEditing && (
                <Badge variant="outline" className="text-amber-500 border-amber-500/30">编辑中</Badge>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
              {metadata.po_number && <span>PO: {String(metadata.po_number)}</span>}
              {metadata.ship_name && <span>船名: {String(metadata.ship_name)}</span>}
              {metadata.delivery_date && <span>交货: {String(metadata.delivery_date)}</span>}
              {order.processed_at && (
                <span>
                  处理于{" "}
                  {new Date(order.processed_at).toLocaleString("zh-CN", {
                    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
                  })}
                </span>
              )}
              {order.template_id && (
                <span className="flex items-center gap-1">
                  <FileSpreadsheet className="h-3 w-3" />
                  模板提取 ({order.template_match_method || "auto"})
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          {!isEditing && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" disabled={!!actionLoading}>
                  {actionLoading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canEdit && (
                  <DropdownMenuItem onClick={enterEditMode}>
                    <Edit3 className="mr-2 h-3.5 w-3.5" /> 编辑数据
                  </DropdownMenuItem>
                )}
                {(isReady || isError) && (
                  <DropdownMenuItem onClick={() => handleAction("rematch", () => rematchOrder(orderId))}>
                    <RefreshCw className="mr-2 h-3.5 w-3.5" /> 重新匹配
                  </DropdownMenuItem>
                )}
                {isReady && !order.anomaly_data && (
                  <DropdownMenuItem onClick={() => handleAction("anomaly", () => runAnomalyCheck(orderId))}>
                    <Shield className="mr-2 h-3.5 w-3.5" /> 运行异常检测
                  </DropdownMenuItem>
                )}
                {isReady && order.match_results && (
                  <DropdownMenuItem onClick={() => handleAction("financial", () => runFinancialAnalysis(orderId))}>
                    <DollarSign className="mr-2 h-3.5 w-3.5" />
                    {order.financial_data ? "重新计算财务分析" : "运行财务分析"}
                  </DropdownMenuItem>
                )}
                {isReady && order.match_statistics && !inquiryGenerating && (
                  <DropdownMenuItem onClick={() => {
                    if (order.inquiry_data) {
                      setShowInquiryOverwriteDialog(true);
                    } else {
                      handleGenerateInquiry();
                    }
                  }}>
                    <FileSpreadsheet className="mr-2 h-3.5 w-3.5" />
                    {order.inquiry_data ? "重新生成询价单" : "生成询价单"}
                  </DropdownMenuItem>
                )}
                {isReady && order.port_id && order.delivery_date && (
                  <DropdownMenuItem onClick={() =>
                    handleAction("delivery_env", () => fetchDeliveryEnvironment(orderId))
                  }>
                    <Waves className="mr-2 h-3.5 w-3.5" />
                    {order.delivery_environment ? "刷新送货环境" : "获取送货环境"}
                  </DropdownMenuItem>
                )}
                {isReady && !order.is_reviewed && (
                  <DropdownMenuItem onClick={() => handleAction("review", () => reviewOrder(orderId))}>
                    <CheckCircle2 className="mr-2 h-3.5 w-3.5" /> 标记已审核
                  </DropdownMenuItem>
                )}
                {isError && (
                  <DropdownMenuItem onClick={() => handleAction("reprocess", () => reprocessOrder(orderId))}>
                    <RefreshCw className="mr-2 h-3.5 w-3.5" /> 重新处理
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {/* Processing indicator */}
      {isProcessing && (
        <div className="px-6 py-3 bg-primary/5 border-b border-primary/10">
          <div className="flex items-center gap-3 text-xs">
            <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />
            <span className="text-primary font-medium">
              {order.status === "extracting" ? "正在提取数据..." : order.status === "matching" ? "正在匹配产品..." : "处理中..."}
            </span>
          </div>
          <Progress value={order.status === "matching" ? 66 : order.status === "extracting" ? 33 : 10} className="h-1 mt-2" />
        </div>
      )}

      {/* Error banner */}
      {isError && order.processing_error && (
        <div className="px-6 py-2 bg-destructive/5 border-b border-destructive/10">
          <div className="flex items-center gap-2 text-xs text-destructive">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>处理失败: {order.processing_error}</span>
          </div>
        </div>
      )}

      {/* Missing delivery_date warning */}
      {isReady && !order.match_results?.length && order.processing_error && (
        <div className="px-6 py-2 bg-amber-500/5 border-b border-amber-500/10">
          <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>{order.processing_error}</span>
          </div>
        </div>
      )}

      {/* Fulfillment progress bar */}
      {!isProcessing && (
        <FulfillmentProgressBar status={(order.fulfillment_status || "pending") as FulfillmentStatus} />
      )}

      {/* Inquiry generation progress */}
      {inquiryGenerating && (
        <InquiryProgress steps={inquirySteps} />
      )}

      {/* Tabs */}
      {!isProcessing && (
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col overflow-hidden">
          <div className="shrink-0 px-6 border-b border-border/50">
            <TabsList className="h-10 bg-transparent gap-2 p-0">
              <TabsTrigger value="overview" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                概览
              </TabsTrigger>
              {order.products && (
                <TabsTrigger value="products" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                  产品列表 ({order.product_count || 0})
                </TabsTrigger>
              )}
              {order.match_results && (
                <TabsTrigger value="matching" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                  匹配结果
                </TabsTrigger>
              )}
              {order.anomaly_data && (
                <TabsTrigger value="anomaly" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                  异常检测
                </TabsTrigger>
              )}
              {order.financial_data && (
                <TabsTrigger value="financial" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                  财务分析
                </TabsTrigger>
              )}
              {order.inquiry_data && (
                <TabsTrigger value="inquiry" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                  询价单
                </TabsTrigger>
              )}
              <TabsTrigger value="fulfillment" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-3 text-xs">
                履约
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 overflow-hidden">
            <TabsContent value="overview" className="h-full m-0">
              <OverviewTab
                order={order}
                isEditing={isEditing}
                editedMetadata={editedMetadata}
                onUpdateMeta={updateMetaField}
                onDeleteMeta={deleteMetaField}
                onAddMeta={addMetaField}
              />
            </TabsContent>
            <TabsContent value="products" className="h-full m-0">
              {isEditing ? (
                <EditableProductsTab
                  products={editedProducts}
                  onUpdate={updateProduct}
                  onDelete={deleteProduct}
                  onAdd={addProduct}
                />
              ) : order.products ? (
                <OrderDataPreview data={{ order_metadata: order.order_metadata || {}, products: order.products }} />
              ) : null}
            </TabsContent>
            <TabsContent value="matching" className="h-full m-0">
              {order.match_results && (
                <MatchResultsPreview data={{ match_results: order.match_results, statistics: order.match_statistics || {} }} />
              )}
            </TabsContent>
            <TabsContent value="anomaly" className="h-full m-0">
              {order.anomaly_data && (
                <AnomalyPreview data={order.anomaly_data as unknown as Record<string, unknown>} />
              )}
            </TabsContent>
            <TabsContent value="financial" className="h-full m-0">
              {order.financial_data && (
                <FinancialPreview data={order.financial_data} />
              )}
            </TabsContent>
            <TabsContent value="inquiry" className="h-full m-0">
              {order.inquiry_data && <InquiryTab order={order} />}
            </TabsContent>
            <TabsContent value="fulfillment" className="h-full m-0">
              <FulfillmentTab order={order} />
            </TabsContent>
          </div>
        </Tabs>
      )}

      {/* Edit mode bottom bar */}
      {isEditing && (
        <div className="shrink-0 px-6 py-3 border-t border-border/50 bg-card/50 flex items-center gap-3">
          <Button size="sm" onClick={saveEdits} disabled={saving}>
            {saving ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
            {saving ? "保存中..." : "保存"}
          </Button>
          <Button variant="outline" size="sm" onClick={cancelEdit} disabled={saving}>
            <X className="mr-1.5 h-3.5 w-3.5" />
            取消
          </Button>
          <span className="text-xs text-muted-foreground ml-auto">修改后保存可重新匹配</span>
        </div>
      )}

      {/* Add meta field dialog */}
      <Dialog open={showAddFieldDialog} onOpenChange={setShowAddFieldDialog}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-sm">添加字段</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label className="text-xs">字段名 (英文)</Label>
            <Input
              value={newFieldKey}
              onChange={(e) => setNewFieldKey(e.target.value)}
              placeholder="例如: remark"
              className="h-8 text-xs"
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); confirmAddMetaField(); } }}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setShowAddFieldDialog(false)}>取消</Button>
            <Button size="sm" onClick={confirmAddMetaField} disabled={!newFieldKey.trim()}>添加</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rematch confirmation dialog */}
      <AlertDialog open={showRematchDialog} onOpenChange={setShowRematchDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>重新匹配产品</AlertDialogTitle>
            <AlertDialogDescription>
              数据已保存成功。是否重新匹配产品？
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>跳过</AlertDialogCancel>
            <AlertDialogAction onClick={() => handleAction("rematch", () => rematchOrder(orderId))}>
              重新匹配
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Inquiry overwrite confirmation dialog */}
      <AlertDialog open={showInquiryOverwriteDialog} onOpenChange={setShowInquiryOverwriteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>重新生成询价单</AlertDialogTitle>
            <AlertDialogDescription>
              将覆盖现有询价单，确认重新生成？
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => { setShowInquiryOverwriteDialog(false); handleGenerateInquiry(); }}>
              确认生成
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ─── Overview Tab ───────────────────────────────────────────

function OverviewTab({
  order,
  isEditing,
  editedMetadata,
  onUpdateMeta,
  onDeleteMeta,
  onAddMeta,
}: {
  order: Order;
  isEditing: boolean;
  editedMetadata: Record<string, string>;
  onUpdateMeta: (key: string, value: string) => void;
  onDeleteMeta: (key: string) => void;
  onAddMeta: () => void;
}) {
  const metadata = order.order_metadata || {};
  const stats = order.match_statistics;

  return (
    <div className="h-full overflow-y-auto px-6 py-5 space-y-5">
      {/* Metadata */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">订单信息</CardTitle>
            {isEditing && (
              <Button variant="ghost" size="sm" className="text-xs h-7" onClick={onAddMeta}>
                <Plus className="mr-1 h-3 w-3" /> 添加字段
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isEditing ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(editedMetadata).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground shrink-0 w-20 truncate" title={key}>{key}</span>
                  <Input
                    value={value}
                    onChange={(e) => onUpdateMeta(key, e.target.value)}
                    className="h-7 text-xs flex-1"
                  />
                  <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => onDeleteMeta(key)}>
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-2.5 text-xs">
              <InfoRow label="PO 编号" value={metadata.po_number ? String(metadata.po_number) : undefined} />
              <InfoRow label="船名" value={metadata.ship_name ? String(metadata.ship_name) : undefined} />
              <InfoRow label="供应商" value={metadata.vendor_name ? String(metadata.vendor_name) : undefined} />
              <InfoRow label="交货日期" value={metadata.delivery_date ? String(metadata.delivery_date) : undefined} />
              <InfoRow label="订单日期" value={metadata.order_date ? String(metadata.order_date) : undefined} />
              <InfoRow label="币种" value={metadata.currency ? String(metadata.currency) : undefined} />
              <InfoRow label="目的港" value={metadata.destination_port ? String(metadata.destination_port) : undefined} />
              <InfoRow label="文件类型" value={order.file_type?.toUpperCase()} />
              <InfoRow label="产品数量" value={order.product_count ? String(order.product_count) : undefined} />
              <InfoRow label="总金额" value={order.total_amount != null ? String(order.total_amount) : undefined} />
              {order.template_id && (
                <InfoRow label="提取模板" value={`#${order.template_id} (${order.template_match_method || "auto"})`} />
              )}
              {Object.entries(metadata)
                .filter(([k]) => !["po_number", "ship_name", "vendor_name", "delivery_date", "order_date", "currency", "destination_port", "total_amount", "extra_fields"].includes(k))
                .map(([k, v]) => (
                  <InfoRow key={k} label={k} value={v != null ? String(v) : undefined} />
                ))}
              {typeof metadata.extra_fields === "object" && metadata.extra_fields != null &&
                Object.entries(metadata.extra_fields as Record<string, unknown>)
                  .filter(([, v]) => v != null)
                  .map(([k, v]) => (
                    <InfoRow key={`extra_${k}`} label={k} value={String(v)} />
                  ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Match stats */}
      {stats && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">匹配统计</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-3 mb-4">
              <StatBlock value={stats.total} label="总计" />
              <StatBlock value={stats.matched} label="已匹配" className="text-emerald-500" />
              <StatBlock value={stats.possible_match} label="可能匹配" className="text-amber-500" />
              <StatBlock value={stats.not_matched} label="未匹配" className="text-destructive" />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">匹配率</span>
                <span className="font-medium">{stats.match_rate}%</span>
              </div>
              <Progress value={stats.match_rate} className="h-1.5" />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Anomaly summary */}
      {order.anomaly_data && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">异常检测摘要</CardTitle>
          </CardHeader>
          <CardContent>
            {order.anomaly_data.total_anomalies === 0 ? (
              <div className="flex items-center gap-2 text-xs text-emerald-500">
                <CheckCircle2 className="h-3.5 w-3.5" />
                未发现异常
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs text-amber-500">
                <AlertTriangle className="h-3.5 w-3.5" />
                发现 {order.anomaly_data.total_anomalies} 个异常
                <span className="text-muted-foreground">
                  (价格: {order.anomaly_data.price_anomalies?.length || 0},
                  数量: {order.anomaly_data.quantity_anomalies?.length || 0},
                  完整性: {order.anomaly_data.completeness_issues?.length || 0})
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Financial summary */}
      {order.financial_data && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">财务分析摘要</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-3 mb-3">
              <StatBlock
                value={order.financial_data.summary.total_revenue.toLocaleString()}
                label={`总收入${order.financial_data.summary.currency ? ` (${order.financial_data.summary.currency})` : ""}`}
              />
              <StatBlock
                value={order.financial_data.summary.total_cost.toLocaleString()}
                label="总成本"
              />
              <StatBlock
                value={order.financial_data.summary.total_profit.toLocaleString()}
                label="总利润"
                className={order.financial_data.summary.total_profit >= 0 ? "text-emerald-500" : "text-destructive"}
              />
              <StatBlock
                value={`${order.financial_data.summary.overall_margin}%`}
                label="利润率"
                className={
                  order.financial_data.summary.overall_margin > 10
                    ? "text-emerald-500"
                    : order.financial_data.summary.overall_margin >= 0
                    ? "text-amber-500"
                    : "text-destructive"
                }
              />
            </div>
            <div className="text-xs text-muted-foreground">
              已分析 {order.financial_data.summary.analyzed_count}/{order.financial_data.summary.total_products} 个产品
              {order.financial_data.warnings.length > 0 && (
                <span className="text-amber-500 ml-1">
                  ({order.financial_data.warnings.length} 个警告)
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Review info */}
      {order.is_reviewed && (
        <Card className="border-emerald-500/20 bg-emerald-500/5">
          <CardContent className="pt-4">
            <div className="flex items-center gap-2 text-xs text-emerald-500 font-medium mb-1">
              <CheckCircle2 className="h-3.5 w-3.5" /> 已审核
            </div>
            <p className="text-xs text-muted-foreground">
              审核时间: {order.reviewed_at ? new Date(order.reviewed_at).toLocaleString("zh-CN") : "-"}
            </p>
            {order.review_notes && (
              <p className="text-xs mt-1">备注: {order.review_notes}</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Delivery environment */}
      {order.delivery_environment && (
        <DeliveryEnvironmentCard data={order.delivery_environment} />
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value || "-"}</span>
    </div>
  );
}

function StatBlock({ value, label, className = "" }: { value: number | string; label: string; className?: string }) {
  return (
    <div className="text-center">
      <div className={`text-lg font-semibold ${className}`}>{value}</div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}

// ─── Delivery Environment Card ───────────────────────────────

function DeliveryEnvironmentCard({ data }: { data: DeliveryEnvironment }) {
  const w = data.weather;
  const marine = data.marine;
  const waveChartData = (marine?.hourly_waves || []).map(w => ({
    time: w.time,
    height: w.wave_height_m,
  }));
  const hasWaveChart = waveChartData.length > 0;
  const forecastAvailable = data.forecast_available !== false;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Waves className="h-4 w-4 text-blue-500" />
            送货环境 — {data.location}
          </CardTitle>
          <span className="text-[10px] text-muted-foreground">{data.date}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Forecast not yet available */}
        {!forecastAvailable && (
          <div className="flex items-start gap-3 p-4 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30">
            <Clock className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="text-xs space-y-1">
              <div className="font-medium text-amber-700 dark:text-amber-400">预报数据暂不可用</div>
              <div className="text-muted-foreground">
                天气和海况预报仅支持未来 16 天内的数据。距离交货日期还有约 {(data.days_until_available ?? 0) + 16} 天，
                预报数据将在交货前 16 天（约 {data.days_until_available ?? 0} 天后）可用。届时可点击「刷新送货环境」获取最新预报。
              </div>
            </div>
          </div>
        )}

        {/* Wave height chart */}
        {forecastAvailable && hasWaveChart && (
          <div>
            <div className="text-[10px] text-muted-foreground mb-1.5">24小时浪高 (m)</div>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={waveChartData}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10 }}
                    interval={2}
                  />
                  <YAxis tick={{ fontSize: 10 }} unit="m" domain={[0, "auto"]} />
                  <Tooltip
                    contentStyle={{ fontSize: 11 }}
                    formatter={(val: number | undefined) => [`${(val ?? 0).toFixed(2)}m`, "浪高"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="height"
                    stroke="#3b82f6"
                    fill="#3b82f6"
                    fillOpacity={0.15}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Marine summary cards */}
        {forecastAvailable && marine && marine.max_wave_height_m != null && (
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            <div className="text-center p-2 rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
              <div className="text-xs font-medium">最大浪高</div>
              <div className="text-sm font-semibold">{marine.max_wave_height_m}m</div>
            </div>
            {marine.max_wave_period_s != null && (
              <div className="text-center p-2 rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
                <div className="text-xs font-medium">最大波周期</div>
                <div className="text-sm font-semibold">{marine.max_wave_period_s}s</div>
              </div>
            )}
            {w && w.max_wind_kph != null && (
              <div className="text-center p-2 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950">
                <div className="text-xs font-medium">最大风速</div>
                <div className="text-sm font-semibold">{w.max_wind_kph} km/h</div>
              </div>
            )}
          </div>
        )}

        {/* Weather summary */}
        {forecastAvailable && w && w.condition && (
          <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/40">
            <CloudSun className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
            <div className="text-xs space-y-1">
              <div className="font-medium">{w.condition}</div>
              <div className="text-muted-foreground">
                温度 {w.min_temp_c}~{w.max_temp_c}°C
                · 风速 {w.max_wind_kph} km/h
                {w.max_wind_gusts_kph != null && <> · 阵风 {w.max_wind_gusts_kph} km/h</>}
                · 降水 {w.total_precip_mm} mm
                {w.uv != null && <> · UV {w.uv}</>}
              </div>
            </div>
          </div>
        )}

        {/* AI summary */}
        {forecastAvailable && data.ai_summary && (
          <div className="text-xs text-muted-foreground whitespace-pre-wrap border-l-2 border-blue-300 pl-3">
            {data.ai_summary}
          </div>
        )}

        <div className="text-[10px] text-muted-foreground text-right">
          数据来源: {data.source} · 获取于 {new Date(data.fetched_at).toLocaleString("zh-CN")}
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Editable Products Tab ─────────────────────────────────

function EditableProductsTab({
  products,
  onUpdate,
  onDelete,
  onAdd,
}: {
  products: OrderProduct[];
  onUpdate: (index: number, field: string, value: string) => void;
  onDelete: (index: number) => void;
  onAdd: () => void;
}) {
  const fields = [
    { key: "product_name", label: "产品名称", width: "flex-[3]" },
    { key: "product_code", label: "代码", width: "flex-1" },
    { key: "quantity", label: "数量", width: "w-20" },
    { key: "unit", label: "单位", width: "w-16" },
    { key: "unit_price", label: "单价", width: "w-24" },
    { key: "total_price", label: "总价", width: "w-24" },
  ];

  return (
    <div className="h-full overflow-auto px-4 py-3">
      <div className="flex items-center gap-2 px-2 py-2 text-[10px] text-muted-foreground uppercase tracking-wider border-b">
        <div className="w-8 shrink-0">#</div>
        {fields.map((f) => (
          <div key={f.key} className={f.width}>{f.label}</div>
        ))}
        <div className="w-8 shrink-0" />
      </div>

      {products.map((product, i) => (
        <div key={i} className="flex items-center gap-2 px-2 py-1.5 border-b border-border/30 hover:bg-muted/30">
          <div className="w-8 shrink-0 text-[10px] text-muted-foreground">{i + 1}</div>
          {fields.map((f) => (
            <div key={f.key} className={f.width}>
              <Input
                value={
                  (product as unknown as Record<string, unknown>)[f.key] != null
                    ? String((product as unknown as Record<string, unknown>)[f.key])
                    : ""
                }
                onChange={(e) => onUpdate(i, f.key, e.target.value)}
                className="h-7 text-xs"
                placeholder={f.label}
              />
            </div>
          ))}
          <div className="w-8 shrink-0">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onDelete(i)}>
              <Trash2 className="h-3 w-3 text-muted-foreground" />
            </Button>
          </div>
        </div>
      ))}

      <div className="px-2 py-3">
        <Button variant="ghost" size="sm" className="text-xs" onClick={onAdd}>
          <Plus className="mr-1 h-3 w-3" /> 添加产品
        </Button>
      </div>
    </div>
  );
}

// ─── Inquiry Progress ────────────────────────────────────────

function InquiryProgress({ steps }: { steps: InquiryStep[] }) {
  // Build display steps: group tool_call + tool_result pairs
  const displaySteps: {
    tool_label: string;
    tool_name: string;
    elapsed: number;
    completed: boolean;
    duration_ms?: number;
  }[] = [];

  const seen = new Set<string>();

  for (const step of steps) {
    if (step.type === "tool_call" && step.tool_name) {
      const key = `${step.tool_name}-${step.step_index}`;
      if (!seen.has(key)) {
        seen.add(key);
        displaySteps.push({
          tool_label: step.tool_label || step.tool_name,
          tool_name: step.tool_name,
          elapsed: step.elapsed_seconds,
          completed: false,
        });
      }
    } else if (step.type === "tool_result" && step.tool_name) {
      // Mark the last matching uncompleted step as completed
      for (let i = displaySteps.length - 1; i >= 0; i--) {
        if (displaySteps[i].tool_name === step.tool_name && !displaySteps[i].completed) {
          displaySteps[i].completed = true;
          displaySteps[i].duration_ms = step.duration_ms;
          break;
        }
      }
    }
  }

  const completedCount = displaySteps.filter((s) => s.completed).length;
  const lastStep = steps[steps.length - 1];
  const totalElapsed = lastStep?.elapsed_seconds || 0;

  return (
    <div className="px-6 py-3 bg-blue-50/50 dark:bg-blue-950/20 border-b border-blue-200/30 dark:border-blue-800/30">
      <div className="flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400 font-medium mb-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>
          生成询价单中... ({completedCount} 步, {totalElapsed.toFixed(1)}s)
        </span>
      </div>
      <div className="space-y-1">
        {displaySteps.map((step, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            {step.completed ? (
              <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />
            ) : (
              <Loader2 className="h-3 w-3 text-blue-500 animate-spin shrink-0" />
            )}
            <span className={step.completed ? "text-muted-foreground" : "text-foreground"}>
              {step.tool_label}
            </span>
            <span className="text-muted-foreground/50 text-[10px] ml-auto tabular-nums">
              {step.completed && step.duration_ms != null
                ? `${(step.duration_ms / 1000).toFixed(1)}s`
                : `${step.elapsed.toFixed(1)}s`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Inquiry Tab ────────────────────────────────────────────

const SELECTION_METHOD_LABELS: Record<string, string> = {
  supplier: "供应商匹配",
  country: "国家匹配",
  single: "唯一模板",
  none: "通用格式",
};

function InquiryTab({ order }: { order: Order }) {
  const inquiry = order.inquiry_data;
  const [downloadingFile, setDownloadingFile] = useState<string | null>(null);
  if (!inquiry) return null;

  const files = inquiry.generated_files || [];

  async function handleDownload(filename: string) {
    setDownloadingFile(filename);
    try {
      await downloadOrderFile(order.id, filename);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "下载失败");
    } finally {
      setDownloadingFile(null);
    }
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5 space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">询价单文件</CardTitle>
          <p className="text-xs text-muted-foreground">
            共 {inquiry.supplier_count} 个供应商，{files.length} 份询价单
            {inquiry.unassigned_count > 0 && (
              <span className="text-amber-500 ml-1">({inquiry.unassigned_count} 个产品未分配)</span>
            )}
            {inquiry.agent_elapsed_seconds != null && (
              <span className="ml-2">
                Agent 耗时 {inquiry.agent_elapsed_seconds}s
                {inquiry.agent_steps != null && <>, {inquiry.agent_steps} 步</>}
              </span>
            )}
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {files.map((file, i) => (
            <div key={i} className="rounded-lg border">
              <div className="flex items-center justify-between px-3 py-2.5">
                <div className="flex items-center gap-3">
                  <FileSpreadsheet className="h-4 w-4 text-emerald-500 shrink-0" />
                  <div>
                    <div className="text-xs font-medium">{file.filename || `供应商 #${file.supplier_id}`}</div>
                    <div className="text-[10px] text-muted-foreground flex items-center gap-1 flex-wrap">
                      <span>供应商 #{file.supplier_id}</span>
                      <span>&middot;</span>
                      <span>{file.product_count} 个产品</span>
                      {file.template_name && (
                        <>
                          <span>&middot;</span>
                          <span>模板: {file.template_name}</span>
                        </>
                      )}
                      {file.selection_method && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] bg-muted">
                          {SELECTION_METHOD_LABELS[file.selection_method] || file.selection_method}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                {file.filename ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs h-7"
                    disabled={downloadingFile === file.filename}
                    onClick={() => handleDownload(file.filename!)}
                  >
                    {downloadingFile === file.filename ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <Download className="mr-1 h-3 w-3" />
                    )}
                    下载
                  </Button>
                ) : file.error ? (
                  <span className="text-xs text-destructive">{file.error}</span>
                ) : null}
              </div>

              {/* AI field mapping details */}
              {file.field_mapping && Object.keys(file.field_mapping).length > 0 && (
                <div className="px-3 pb-2.5 border-t">
                  <div className="text-[10px] text-muted-foreground mt-2 mb-1">AI 字段映射</div>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(file.field_mapping).map(([tplField, metaKey]) => (
                      <span key={tplField} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                        {tplField === metaKey ? tplField : `${tplField} ← ${metaKey}`}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Review warnings */}
              {file.review_issues && file.review_issues.length > 0 && (
                <div className="px-3 pb-2.5 border-t">
                  <div className="text-[10px] text-amber-600 mt-2 mb-1">AI 审查警告</div>
                  <div className="space-y-1">
                    {file.review_issues.map((issue, j) => (
                      <div key={j} className="text-[10px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-2 py-1">
                        <span className="font-mono">{issue.cell}</span> {issue.field}: {issue.issue}
                        {issue.suggestion && <span className="text-muted-foreground ml-1">({issue.suggestion})</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      {inquiry.agent_summary && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Agent 总结</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground whitespace-pre-wrap">{inquiry.agent_summary}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ─── Fulfillment Progress Bar ─────────────────────────────────

function FulfillmentProgressBar({ status }: { status: FulfillmentStatus }) {
  const currentIndex = FULFILLMENT_STEPS.findIndex((s) => s.key === status);

  return (
    <div className="shrink-0 px-6 py-3 border-b border-border/50 bg-card/30">
      <div className="flex items-center justify-between">
        {FULFILLMENT_STEPS.map((step, i) => {
          const isDone = i < currentIndex;
          const isCurrent = i === currentIndex;
          return (
            <div key={step.key} className="flex items-center flex-1 last:flex-none">
              <div className="flex flex-col items-center">
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-medium border-2 transition-colors ${
                    isDone
                      ? "bg-emerald-500 border-emerald-500 text-white"
                      : isCurrent
                      ? "bg-primary border-primary text-primary-foreground"
                      : "bg-muted border-border text-muted-foreground"
                  }`}
                >
                  {isDone ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    i + 1
                  )}
                </div>
                <span
                  className={`text-[10px] mt-1 whitespace-nowrap ${
                    isCurrent ? "text-primary font-medium" : isDone ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"
                  }`}
                >
                  {step.label}
                </span>
              </div>
              {i < FULFILLMENT_STEPS.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-1 mt-[-14px] ${
                    i < currentIndex ? "bg-emerald-500" : "bg-border"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Fulfillment Tab ──────────────────────────────────────────

const FULFILLMENT_STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  inquiry_sent: "已询价",
  quoted: "已报价",
  confirmed: "已确认",
  delivering: "运送中",
  delivered: "已交货",
  invoiced: "已开票",
  paid: "已付款",
};

function FulfillmentTab({ order }: { order: Order }) {
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

  return (
    <div className="h-full overflow-y-auto px-6 py-5 space-y-5">
      {/* Current status */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">当前履约状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <Badge variant="default" className="text-xs">
              {FULFILLMENT_STATUS_LABELS[order.fulfillment_status || "pending"] || order.fulfillment_status || "pending"}
            </Badge>
            {order.fulfillment_notes && (
              <span className="text-xs text-muted-foreground">{order.fulfillment_notes}</span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Delivery receipt */}
      {order.delivery_data && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">交货验收</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-2 text-xs">
              <InfoRow label="交货时间" value={order.delivery_data.delivered_at} />
              <InfoRow label="收货人" value={order.delivery_data.received_by} />
              <InfoRow label="接收总量" value={String(order.delivery_data.total_accepted)} />
              <InfoRow label="拒收总量" value={order.delivery_data.total_rejected > 0 ? String(order.delivery_data.total_rejected) : "0"} />
            </div>
            <p className="text-xs text-muted-foreground">{order.delivery_data.summary}</p>

            {order.delivery_data.items.length > 0 && (
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-muted/50 border-b">
                      <th className="text-left px-3 py-2 font-medium">产品</th>
                      <th className="text-right px-3 py-2 font-medium">订购量</th>
                      <th className="text-right px-3 py-2 font-medium">接收量</th>
                      <th className="text-right px-3 py-2 font-medium">拒收量</th>
                      <th className="text-left px-3 py-2 font-medium">原因</th>
                      <th className="text-left px-3 py-2 font-medium">备注</th>
                    </tr>
                  </thead>
                  <tbody>
                    {order.delivery_data.items.map((item, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="px-3 py-2">
                          <div>{item.product_name}</div>
                          {item.product_code && (
                            <div className="text-[10px] text-muted-foreground font-mono">{item.product_code}</div>
                          )}
                        </td>
                        <td className="text-right px-3 py-2">{item.ordered_qty}</td>
                        <td className="text-right px-3 py-2 text-emerald-600">{item.accepted_qty}</td>
                        <td className={`text-right px-3 py-2 ${item.rejected_qty > 0 ? "text-destructive font-medium" : ""}`}>
                          {item.rejected_qty}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">{item.rejection_reason || "-"}</td>
                        <td className="px-3 py-2 text-muted-foreground">{item.notes || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Invoice info */}
      {order.invoice_number && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">发票信息</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-2 text-xs">
              <InfoRow label="发票号" value={order.invoice_number} />
              <InfoRow label="金额" value={order.invoice_amount != null ? String(order.invoice_amount) : undefined} />
              <InfoRow label="日期" value={order.invoice_date} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Payment info */}
      {order.payment_amount != null && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">付款信息</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-2 text-xs">
              <InfoRow label="金额" value={String(order.payment_amount)} />
              <InfoRow label="日期" value={order.payment_date} />
              <InfoRow label="参考号" value={order.payment_reference} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Attachments */}
      {order.attachments && order.attachments.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">附件 ({order.attachments.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {order.attachments.map((att, i) => {
                const isImage = /\.(jpg|jpeg|png|webp)$/i.test(att.filename);
                const fileUrl = `${API_BASE}/uploads/${att.filename}`;
                return (
                  <div key={i} className="flex items-center gap-3 p-2 border rounded-lg">
                    {isImage ? (
                      <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="shrink-0">
                        <img
                          src={fileUrl}
                          alt={att.description || att.original_name}
                          className="w-16 h-16 object-cover rounded"
                        />
                      </a>
                    ) : (
                      <div className="w-16 h-16 bg-muted rounded flex items-center justify-center shrink-0">
                        <FileSpreadsheet className="h-6 w-6 text-muted-foreground" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium truncate">{att.original_name}</div>
                      {att.description && (
                        <div className="text-[10px] text-muted-foreground">{att.description}</div>
                      )}
                      <div className="text-[10px] text-muted-foreground">
                        {att.uploaded_at ? new Date(att.uploaded_at).toLocaleString("zh-CN") : ""}
                      </div>
                    </div>
                    <a href={fileUrl} target="_blank" rel="noopener noreferrer">
                      <Button variant="ghost" size="sm" className="text-xs h-7">
                        <Download className="mr-1 h-3 w-3" /> 查看
                      </Button>
                    </a>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!order.delivery_data && !order.invoice_number && order.payment_amount == null && (!order.attachments || order.attachments.length === 0) && (
        <div className="text-center py-10 text-xs text-muted-foreground">
          <p>暂无履约数据。</p>
          <p className="mt-1">可以在 AI 助手中通过对话更新履约状态。</p>
        </div>
      )}
    </div>
  );
}
