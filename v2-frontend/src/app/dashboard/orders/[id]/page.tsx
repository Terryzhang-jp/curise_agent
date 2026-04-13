"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const toUTC = (s: string) => s.endsWith("Z") || s.includes("+") ? s : s + "Z";
import { useParams, useRouter } from "next/navigation";
import {
  getOrder,
  reviewOrder,
  reprocessOrder,
  runAnomalyCheck,
  runFinancialAnalysis,
  fetchDeliveryEnvironment,
  startGenerateInquiry,
  cancelGenerateInquiry,
  streamInquiryProgress,
  startGenerateInquirySingleSupplier,
  streamInquiryProgressWithKey,
  getInquiryPreview,
  getInquiryDataPreview,
  saveInquiryFieldOverrides,
  getInquiryReadiness,
  type InquiryDataPreview,
  type InquiryReadiness,
  updateOrder,
  rematchOrder,
  downloadOrderFile,
  getOrderFilePreview,
  getPortsList,
  getCountriesList,
  type Order,
  type OrderStatus,
  type OrderProduct,
  type InquiryStep,
  type FulfillmentStatus,
  type DeliveryEnvironment,
  type PortItem,
  type CountryItem,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { MarkdownContent } from "@/components/markdown-content";
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
  FileText,
  Maximize2,
  MessageSquare,
  ChevronDown,
  Send,
  StopCircle,
  Wrench,
  CheckCheck,
  AlertCircle,
  Sparkles,
  SquarePen,
  Eye,
  RotateCw,
  Pencil,
  XCircle,
} from "lucide-react";
import {
  createChatSession,
  sendChatMessage,
  streamChatMessages,
  cancelChatAgent,
  type ChatMessage,
} from "@/lib/chat-api";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import OrderDataPreview from "@/app/dashboard/workspace/artifacts/OrderDataPreview";
import MatchResultsPreview from "@/app/dashboard/workspace/artifacts/MatchResultsPreview";
import AnomalyPreview from "@/app/dashboard/workspace/artifacts/AnomalyPreview";
import FinancialPreview from "@/app/dashboard/workspace/artifacts/FinancialPreview";
import { listSupplierTemplates, type SupplierTemplate } from "@/lib/settings-api";

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
  const [editedPortId, setEditedPortId] = useState<number | null>(null);
  const [editedCountryId, setEditedCountryId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  // Ports / countries for geo selector
  const [portsList, setPortsList] = useState<PortItem[]>([]);
  const [countriesList, setCountriesList] = useState<CountryItem[]>([]);

  // Add meta field dialog
  const [showAddFieldDialog, setShowAddFieldDialog] = useState(false);
  const [newFieldKey, setNewFieldKey] = useState("");

  // Confirm dialogs
  const [showRematchDialog, setShowRematchDialog] = useState(false);

  // Financial analysis currency change
  const [changingCurrency, setChangingCurrency] = useState(false);
  const [showCurrencyDialog, setShowCurrencyDialog] = useState(false);
  const [selectedCurrency, setSelectedCurrency] = useState("JPY");
  const [orderCurrency, setOrderCurrency] = useState("AUD");

  // PDF preview
  const [pdfPreviewOpen, setPdfPreviewOpen] = useState(false);
  const [pdfPreviewFullscreen, setPdfPreviewFullscreen] = useState(false);
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null);
  const [pdfPreviewLoading, setPdfPreviewLoading] = useState(false);

  // AI assistant drawer
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [agentStatus, setAgentStatus] = useState<"idle" | "running" | "stopping" | "done" | "error">("idle");
  const [agentMessages, setAgentMessages] = useState<ChatMessage[]>([]);
  const [agentSessionId, setAgentSessionId] = useState<string | null>(null);
  const [agentInput, setAgentInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const agentAbortRef = useRef<(() => void) | null>(null);
  const assistantScrollRef = useRef<HTMLDivElement>(null);

  // Inquiry streaming
  const [inquiryGenerating, setInquiryGenerating] = useState(false);
  const [inquiryStopping, setInquiryStopping] = useState(false);
  const [activeInquiryStreamKey, setActiveInquiryStreamKey] = useState<string | null>(null);
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
    // Load ports and countries for geo editing
    getPortsList().then(setPortsList);
    getCountriesList().then(setCountriesList);
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

  const handleChangeCurrency = async (currency: string) => {
    setChangingCurrency(true);
    try {
      const knownOrderCurrency = order?.financial_data?.summary?.order_currency || orderCurrency || undefined;
      const result = await runFinancialAnalysis(orderId, currency, knownOrderCurrency);
      setOrder(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "切换币种失败");
    } finally {
      setChangingCurrency(false);
    }
  };

  async function openPdfPreview() {
    if (pdfPreviewUrl) {
      setPdfPreviewOpen(true);
      return;
    }
    setPdfPreviewLoading(true);
    setPdfPreviewOpen(true);
    try {
      const { url } = await getOrderFilePreview(orderId);
      setPdfPreviewUrl(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "无法加载预览");
      setPdfPreviewOpen(false);
    } finally {
      setPdfPreviewLoading(false);
    }
  }

  // Auto-scroll assistant on new messages
  useEffect(() => {
    if (assistantScrollRef.current) {
      assistantScrollRef.current.scrollTop = assistantScrollRef.current.scrollHeight;
    }
  }, [agentMessages]);

  async function sendOrderAgentMessage() {
    const text = agentInput.trim();
    if (!text || agentBusy) return;
    setAgentInput("");
    setAgentBusy(true);
    setAgentStatus("running");

    try {
      // Lazy-create session
      let sid = agentSessionId;
      if (!sid) {
        const session = await createChatSession("订单助手");
        sid = session.id;
        setAgentSessionId(sid);
      }

      // Build context prefix on first message
      const unmatchedItems = order?.match_results?.filter(
        (r) => r.match_status === "not_matched"
      ) ?? [];
      const unmatchedNames = unmatchedItems
        .slice(0, 10)
        .map((r) => r.product_name)
        .filter(Boolean)
        .join(", ");

      const isFirstMessage = agentMessages.length === 0;
      const contextPrefix = isFirstMessage
        ? `[订单上下文] 订单ID=${orderId}, 文件=${order?.filename || ""}, 未匹配产品数=${unmatchedItems.length}${unmatchedNames ? `, 未匹配产品: ${unmatchedNames}` : ""}.\n\n`
        : "";

      const fullContent = contextPrefix + text;

      // Optimistically append user message
      const userMsg: ChatMessage = {
        id: Date.now(),
        role: "user",
        content: text,
        msg_type: "user_input",
        created_at: new Date().toISOString(),
      };
      setAgentMessages((prev) => [...prev, userMsg]);

      const { last_msg_id } = await sendChatMessage(sid, fullContent, null, "order_processing");

      const abort = streamChatMessages(
        sid,
        last_msg_id,
        (msg) => {
          setAgentMessages((prev) => {
            const existing = prev.find((m) => m.id === msg.id);
            if (existing) return prev.map((m) => (m.id === msg.id ? msg : m));
            return [...prev, msg];
          });
        },
        () => {
          setAgentStatus("done");
          setAgentBusy(false);
          agentAbortRef.current = null;
        },
        (err) => {
          setAgentStatus("error");
          setAgentBusy(false);
          agentAbortRef.current = null;
          toast.error(err.message || "助手出错");
        },
        (token) => {
          setAgentMessages((prev) => {
            const existing = prev.find((m) => m.id === token.msg_id);
            if (existing) {
              return prev.map((m) =>
                m.id === token.msg_id
                  ? { ...m, content: m.content + token.content, streaming: true }
                  : m
              );
            }
            return [
              ...prev,
              {
                id: token.msg_id,
                role: "assistant" as const,
                content: token.content,
                msg_type: "text" as const,
                created_at: new Date().toISOString(),
                streaming: true,
              },
            ];
          });
        },
        (done) => {
          setAgentMessages((prev) =>
            prev.map((m) =>
              m.id === done.msg_id
                ? { ...m, content: done.full_content, streaming: false }
                : m
            )
          );
        }
      );
      agentAbortRef.current = abort;
    } catch (err) {
      setAgentStatus("error");
      setAgentBusy(false);
      toast.error(err instanceof Error ? err.message : "发送失败");
    }
  }

  async function stopOrderAgent() {
    if (!agentSessionId || agentStatus !== "running") return;
    setAgentStatus("stopping");
    try {
      await cancelChatAgent(agentSessionId);
    } catch {
      // ignore
    } finally {
      setAgentBusy(false);
      agentAbortRef.current?.();
      agentAbortRef.current = null;
    }
  }

  async function newOrderAgentSession() {
    // Stop any running agent first
    if (agentStatus === "running") {
      agentAbortRef.current?.();
      agentAbortRef.current = null;
    }
    setAgentMessages([]);
    setAgentInput("");
    setAgentSessionId(null);
    setAgentStatus("idle");
    setAgentBusy(false);
  }

  function resetInquiryRun() {
    setInquiryGenerating(false);
    setInquiryStopping(false);
    setActiveInquiryStreamKey(null);
    setInquirySteps([]);
    abortInquiryRef.current = null;
  }

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
    setEditedPortId(order.port_id ?? null);
    setEditedCountryId(order.country_id ?? null);
    setIsEditing(true);
  }

  function cancelEdit() {
    setIsEditing(false);
    setEditedMetadata({});
    setEditedProducts([]);
    setEditedPortId(null);
    setEditedCountryId(null);
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
        port_id: editedPortId ?? undefined,
        country_id: editedCountryId ?? undefined,
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
  async function handleGenerateInquiry(
    templateOverrides?: Record<number, number | null>,
    supplierIds?: number[],
  ) {
    if (!order) return;
    setInquiryGenerating(true);
    setInquiryStopping(false);
    setInquirySteps([]);
    setActiveTab("inquiry");

    try {
      const { stream_key } = await startGenerateInquiry(orderId, templateOverrides, supplierIds);
      setActiveInquiryStreamKey(stream_key);

      const abort = streamInquiryProgress(
        orderId,
        (step) => {
          setInquirySteps((prev) => [...prev, step]);
        },
        async () => {
          // Done — refresh order data
          await fetchOrder();
          resetInquiryRun();
          toast.success("询价单生成完成");
        },
        (err) => {
          const message = err.message || "询价单生成失败";
          resetInquiryRun();
          if (message.includes("已停止") || message.includes("已取消")) {
            toast.success("询价生成已停止");
          } else {
            toast.error(message);
          }
        }
      );
      abortInquiryRef.current = abort;
    } catch (err) {
      resetInquiryRun();
      toast.error(err instanceof Error ? err.message : "启动询价单生成失败");
    }
  }

  // Single supplier redo
  async function handleRedoSupplier(supplierId: number, templateId?: number) {
    if (!order) return;
    setInquiryGenerating(true);
    setInquiryStopping(false);
    setInquirySteps([]);
    setActiveTab("inquiry");

    try {
      const { stream_key } = await startGenerateInquirySingleSupplier(orderId, supplierId, templateId);
      setActiveInquiryStreamKey(stream_key);

      // SSE with supplier-specific stream_key
      const abort = streamInquiryProgressWithKey(
        orderId,
        stream_key,
        (step) => {
          setInquirySteps((prev) => [...prev, step]);
        },
        async () => {
          await fetchOrder();
          resetInquiryRun();
          toast.success(`供应商 #${supplierId} 询价单重新生成完成`);
        },
        (err) => {
          const message = err.message || "重新生成失败";
          resetInquiryRun();
          if (message.includes("已停止") || message.includes("已取消")) {
            toast.success("询价生成已停止");
          } else {
            toast.error(message);
          }
        }
      );
      abortInquiryRef.current = abort;
    } catch (err) {
      resetInquiryRun();
      toast.error(err instanceof Error ? err.message : "启动重新生成失败");
    }
  }

  const cancelInquiryRun = useCallback(async () => {
    if (!order || !activeInquiryStreamKey || inquiryStopping) return;
    setInquiryStopping(true);
    try {
      await cancelGenerateInquiry(order.id, activeInquiryStreamKey);
    } catch (err) {
      setInquiryStopping(false);
      toast.error(err instanceof Error ? err.message : "停止失败");
    }
  }, [activeInquiryStreamKey, inquiryStopping, order]);

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
  const isReady = order.status === "ready" || order.status === "extracted";
  const hasInquiryWorkbench = Boolean(order.match_results?.length);
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
                  {new Date(toUTC(order.processed_at)).toLocaleString("zh-CN", {
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
              {order.document_id ? (
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => router.push(`/dashboard/documents/${order.document_id}`)}
                >
                  查看源文档 #{order.document_id}
                </button>
              ) : null}
            </div>
          </div>

          {/* Actions */}
          {!isEditing && (
            <div className="flex items-center gap-2">
            {order.file_url && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 text-xs"
                onClick={openPdfPreview}
              >
                <FileText className="h-3.5 w-3.5" />
                原始文档
              </Button>
            )}
            {canEdit && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 text-xs"
                onClick={enterEditMode}
              >
                <Edit3 className="h-3.5 w-3.5" />
                编辑
              </Button>
            )}
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
                  <DropdownMenuItem onClick={() => {
                    const knownOrderCurrency = order.order_metadata?.currency || order.financial_data?.summary?.order_currency || "";
                    if (knownOrderCurrency) setOrderCurrency(knownOrderCurrency);
                    const analysisCurrency = order.financial_data?.summary?.base_currency || "JPY";
                    setSelectedCurrency(analysisCurrency);
                    setShowCurrencyDialog(true);
                  }}>
                    <DollarSign className="mr-2 h-3.5 w-3.5" />
                    {order.financial_data ? "重新计算财务分析" : "运行财务分析"}
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
            </div>
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
              {hasInquiryWorkbench && (
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
                portsList={portsList}
                countriesList={countriesList}
                editedPortId={editedPortId}
                editedCountryId={editedCountryId}
                onUpdatePort={setEditedPortId}
                onUpdateCountry={setEditedCountryId}
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
                <FinancialPreview
                  data={order.financial_data}
                  onChangeCurrency={handleChangeCurrency}
                  changingCurrency={changingCurrency}
                />
              )}
            </TabsContent>
            <TabsContent value="inquiry" className="h-full m-0">
              {hasInquiryWorkbench && (
                <InquiryTab
                  order={order}
                  onRedoSupplier={handleRedoSupplier}
                  onGenerateAll={handleGenerateInquiry}
                  inquiryGenerating={inquiryGenerating}
                  inquiryStopping={inquiryStopping}
                  inquirySteps={inquirySteps}
                  onCancelInquiry={cancelInquiryRun}
                />
              )}
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
      {/* Currency selection dialog for financial analysis */}
      <Dialog open={showCurrencyDialog} onOpenChange={setShowCurrencyDialog}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>财务分析设置</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">订单价格币种</label>
              <p className="text-xs text-muted-foreground">邮轮公司 PO 中的价格单位（即你的收入币种）</p>
              <Select value={orderCurrency} onValueChange={setOrderCurrency}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["USD", "JPY", "AUD", "EUR", "GBP", "KRW", "THB", "SGD", "CNY", "NZD"].map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">分析输出币种</label>
              <p className="text-xs text-muted-foreground">所有金额统一换算到该币种输出</p>
              <Select value={selectedCurrency} onValueChange={setSelectedCurrency}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["USD", "JPY", "AUD", "EUR", "GBP", "KRW", "THB", "SGD", "CNY", "NZD"].map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCurrencyDialog(false)}>取消</Button>
            <Button onClick={() => {
              setShowCurrencyDialog(false);
              handleAction("financial", () => runFinancialAnalysis(orderId, selectedCurrency, orderCurrency));
            }}>
              开始分析
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* AI Assistant Drawer */}
      <AssistantDrawer
        open={assistantOpen}
        onToggle={() => setAssistantOpen((v) => !v)}
        messages={agentMessages}
        input={agentInput}
        onInputChange={setAgentInput}
        onSend={sendOrderAgentMessage}
        onStop={stopOrderAgent}
        onNewSession={newOrderAgentSession}
        busy={agentBusy}
        agentStatus={agentStatus}
        scrollRef={assistantScrollRef}
        unmatchedCount={
          order?.match_results?.filter(
            (r) => r.match_status === "not_matched"
          ).length ?? 0
        }
        pdfOpen={pdfPreviewOpen}
      />

      {/* PDF Preview Side Panel */}
      {pdfPreviewOpen && (
        <div className="fixed right-0 top-0 h-full w-[44%] bg-background border-l border-border/60 shadow-2xl z-40 flex flex-col">
          <div className="shrink-0 px-4 py-3 border-b border-border/50 flex items-center gap-3">
            <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-sm font-medium truncate flex-1">{order.filename}</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
              title="全屏查看"
              onClick={() => setPdfPreviewFullscreen(true)}
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
              onClick={() => setPdfPreviewOpen(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex-1 overflow-hidden">
            {pdfPreviewLoading ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 className="animate-spin h-5 w-5 text-muted-foreground" />
              </div>
            ) : pdfPreviewUrl && order.file_type === "pdf" ? (
              <iframe
                src={pdfPreviewUrl}
                className="w-full h-full border-none"
                title="原始文档预览"
              />
            ) : pdfPreviewUrl ? (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-center px-6">
                <FileText className="h-10 w-10 text-muted-foreground/50" />
                <p className="text-sm text-muted-foreground">Excel 文件不支持在线预览</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => downloadOrderFile(orderId, order.filename)}
                >
                  <Download className="mr-1.5 h-3.5 w-3.5" />
                  下载文件
                </Button>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* PDF Preview Full Screen Dialog */}
      <Dialog open={pdfPreviewFullscreen} onOpenChange={setPdfPreviewFullscreen}>
        <DialogContent className="max-w-[96vw] w-[96vw] h-[94vh] p-0 flex flex-col gap-0">
          <DialogHeader className="shrink-0 px-4 py-3 border-b border-border/50">
            <DialogTitle className="text-sm font-medium truncate">{order.filename}</DialogTitle>
          </DialogHeader>
          {pdfPreviewUrl && order.file_type === "pdf" ? (
            <iframe
              src={pdfPreviewUrl}
              className="flex-1 w-full border-none min-h-0"
              title="原始文档全屏预览"
            />
          ) : null}
        </DialogContent>
      </Dialog>
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
  portsList,
  countriesList,
  editedPortId,
  editedCountryId,
  onUpdatePort,
  onUpdateCountry,
}: {
  order: Order;
  isEditing: boolean;
  editedMetadata: Record<string, string>;
  onUpdateMeta: (key: string, value: string) => void;
  onDeleteMeta: (key: string) => void;
  onAddMeta: () => void;
  portsList: PortItem[];
  countriesList: CountryItem[];
  editedPortId: number | null;
  editedCountryId: number | null;
  onUpdatePort: (id: number | null) => void;
  onUpdateCountry: (id: number | null) => void;
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
            <div className="space-y-4">
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(editedMetadata).map(([key, value]) => {
                // destination_port 用港口下拉替代文本输入
                if (key === "destination_port") {
                  return (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground shrink-0 w-20 truncate" title="目的港">目的港</span>
                      <Select
                        value={editedPortId ? String(editedPortId) : "__none__"}
                        onValueChange={(v) => {
                          if (v === "__none__") {
                            onUpdatePort(null);
                            onUpdateCountry(null);
                            onUpdateMeta("destination_port", "");
                          } else {
                            const port = portsList.find((p) => p.id === Number(v));
                            if (port) {
                              onUpdatePort(port.id);
                              if (port.country_id) onUpdateCountry(port.country_id);
                              onUpdateMeta("destination_port", port.name);
                            }
                          }
                        }}
                      >
                        <SelectTrigger className="h-7 text-xs flex-1">
                          <SelectValue placeholder="选择港口" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__" className="text-xs">无</SelectItem>
                          {portsList.map((p) => (
                            <SelectItem key={p.id} value={String(p.id)} className="text-xs">
                              {p.name}{p.country_name ? ` · ${p.country_name}` : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  );
                }
                return (
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
                );
              })}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-2.5 text-xs">
              <InfoRow label="PO 编号" value={metadata.po_number ? String(metadata.po_number) : undefined} />
              <InfoRow label="船名" value={metadata.ship_name ? String(metadata.ship_name) : undefined} />
              <InfoRow label="供应商" value={metadata.vendor_name ? String(metadata.vendor_name) : undefined} />
              <InfoRow label="交货日期" value={metadata.delivery_date ? String(metadata.delivery_date) : undefined} />
              <InfoRow label="订单日期" value={metadata.order_date ? String(metadata.order_date) : undefined} />
              <InfoRow label="币种" value={metadata.currency ? String(metadata.currency) : undefined} />
              <InfoRow label="目的港" value={
                (() => {
                  if (order.port_id) {
                    const port = portsList.find((p) => p.id === order.port_id);
                    if (port) return port.country_name ? `${port.name} · ${port.country_name}` : port.name;
                  }
                  return metadata.destination_port ? String(metadata.destination_port) : undefined;
                })()
              } />
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
            <div className="grid grid-cols-3 gap-3 mb-4">
              <StatBlock value={stats.total} label="总计" />
              <StatBlock value={stats.matched} label="已匹配" className="text-emerald-500" />
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
              审核时间: {order.reviewed_at ? new Date(toUTC(order.reviewed_at)).toLocaleString("zh-CN") : "-"}
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
          数据来源: {data.source} · 获取于 {new Date(toUTC(data.fetched_at)).toLocaleString("zh-CN")}
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

// Human-readable action descriptions (no jargon)
const STEP_DESCRIPTIONS: Record<string, string> = {
  read_template: "读取模板",
  select_template: "选择模板",
  read_order_data: "读取订单数据",
  write_cells: "填写表头",
  write_product_rows: "填写产品明细",
  verify: "校验数据",
  save: "保存文件",
  think: "分析中",
};

interface SupplierProgress {
  supplier_id: number;
  supplier_name: string;
  product_count: number;
  done: boolean;
  error: boolean;
  currentAction: string | null;  // what's happening right now
  completedSteps: number;
  elapsedSeconds: number;
}

function InquiryProgress({
  steps,
  order,
  onCancel,
  stopping,
}: {
  steps: InquiryStep[];
  order?: Order | null;
  onCancel?: () => void;
  stopping?: boolean;
}) {
  const groups = useMemo(() => {
    const map = new Map<number, SupplierProgress>();
    let currentSid: number | null = null;

    const preNames: Record<number, string> = {};
    if (order?.inquiry_data?.suppliers) {
      for (const [k, v] of Object.entries(order.inquiry_data.suppliers)) {
        if (v.supplier_name) preNames[Number(k)] = v.supplier_name;
      }
    }

    for (const step of steps) {
      if (step.type === "supplier_start" && step.supplier_id != null) {
        currentSid = step.supplier_id;
        map.set(currentSid, {
          supplier_id: currentSid,
          supplier_name: step.supplier_name || preNames[currentSid] || `供应商 #${currentSid}`,
          product_count: step.product_count ?? 0,
          done: false,
          error: false,
          currentAction: null,
          completedSteps: 0,
          elapsedSeconds: 0,
        });
      } else if (step.type === "supplier_done" && step.supplier_id != null) {
        const g = map.get(step.supplier_id);
        if (g) {
          g.done = true;
          g.error = step.status === "error";
          g.currentAction = null;
          if (step.elapsed_seconds != null) g.elapsedSeconds = step.elapsed_seconds;
        }
      } else if (step.type === "thinking") {
        const sid = step.supplier_id ?? currentSid;
        if (sid != null) {
          const g = map.get(sid);
          if (g && !g.done) g.currentAction = "分析中...";
        }
      } else if (step.type === "tool_call" && step.tool_name) {
        const sid = step.supplier_id ?? currentSid;
        if (sid != null) {
          const g = map.get(sid);
          if (g && !g.done) {
            g.currentAction = (STEP_DESCRIPTIONS[step.tool_name] || step.tool_label || step.tool_name) + "...";
          }
        }
      } else if (step.type === "tool_result" && step.tool_name) {
        const sid = step.supplier_id ?? currentSid;
        if (sid != null) {
          const g = map.get(sid);
          if (g) {
            g.completedSteps++;
            if (step.elapsed_seconds != null) g.elapsedSeconds = step.elapsed_seconds;
          }
        }
      }
    }
    return Array.from(map.values());
  }, [steps, order]);

  const isLegacy = groups.length === 0 && steps.length > 0;

  let totalElapsed = 0;
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].type !== "preview" && steps[i].elapsed_seconds != null) {
      totalElapsed = steps[i].elapsed_seconds!;
      break;
    }
  }

  const doneCount = groups.filter((g) => g.done).length;
  const progress = groups.length > 0 ? (doneCount / groups.length) * 100 : 0;

  if (isLegacy) {
    return <LegacyInquiryProgress steps={steps} onCancel={onCancel} stopping={stopping} />;
  }

  return (
    <div className="px-6 py-5 border-b border-border/40">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="relative h-5 w-5 flex items-center justify-center">
            <FileSpreadsheet className="h-4 w-4 text-primary" />
            {doneCount < groups.length && (
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
            )}
          </div>
          <span className="text-sm font-medium">
            生成询价单
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground tabular-nums">
            {doneCount}/{groups.length} · {totalElapsed.toFixed(1)}s
          </span>
          {onCancel && (
            <Button
              variant="destructive"
              size="sm"
              className="h-7 text-xs"
              disabled={stopping}
              onClick={onCancel}
            >
              {stopping ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <X className="mr-1 h-3 w-3" />
              )}
              {stopping ? "停止中..." : "停止生成"}
            </Button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1 bg-muted rounded-full mb-5 overflow-hidden">
        <div
          className="h-full bg-primary rounded-full transition-all duration-700 ease-out"
          style={{ width: `${Math.max(progress, groups.length > 0 ? 3 : 0)}%` }}
        />
      </div>

      {/* Supplier list */}
      <div className="space-y-1">
        {groups.map((g) => (
          <div
            key={g.supplier_id}
            className="flex items-center gap-3 py-2 px-1"
          >
            {/* Status indicator */}
            <div className="shrink-0 w-5 flex justify-center">
              {g.done && !g.error ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              ) : g.done && g.error ? (
                <AlertTriangle className="h-4 w-4 text-destructive" />
              ) : g.currentAction ? (
                <Loader2 className="h-4 w-4 text-primary animate-spin" />
              ) : (
                <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30" />
              )}
            </div>

            {/* Supplier info */}
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className={`text-sm truncate ${
                  g.done ? "text-muted-foreground" : "text-foreground font-medium"
                }`}>
                  {g.supplier_name}
                </span>
                <span className="text-[11px] text-muted-foreground/60 shrink-0">
                  {g.product_count} 产品
                </span>
              </div>
              {/* Current action — subtle, single line */}
              {!g.done && g.currentAction && (
                <p className="text-[11px] text-muted-foreground/70 mt-0.5 truncate">
                  {g.currentAction}
                </p>
              )}
            </div>

            {/* Duration (only when done) */}
            {g.done && (
              <span className="text-[11px] text-muted-foreground/50 tabular-nums shrink-0">
                {g.elapsedSeconds.toFixed(1)}s
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function LegacyInquiryProgress({
  steps,
  onCancel,
  stopping,
}: {
  steps: InquiryStep[];
  onCancel?: () => void;
  stopping?: boolean;
}) {
  let currentAction = "";
  let completedCount = 0;
  for (const step of steps) {
    if (step.type === "tool_call" && step.tool_name) {
      currentAction = (STEP_DESCRIPTIONS[step.tool_name] || step.tool_label || step.tool_name) + "...";
    } else if (step.type === "tool_result") {
      completedCount++;
    }
  }
  let totalElapsed = 0;
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].type !== "preview" && steps[i].elapsed_seconds != null) { totalElapsed = steps[i].elapsed_seconds!; break; }
  }

  return (
    <div className="px-6 py-5 border-b border-border/40">
      <div className="flex items-center gap-2.5 mb-3">
        <div className="relative h-5 w-5 flex items-center justify-center">
          <FileSpreadsheet className="h-4 w-4 text-primary" />
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
        </div>
        <span className="text-sm font-medium">生成询价单</span>
        <span className="text-xs text-muted-foreground tabular-nums ml-auto">
          {completedCount} 步 · {totalElapsed.toFixed(1)}s
        </span>
        {onCancel && (
          <Button
            variant="destructive"
            size="sm"
            className="h-7 text-xs"
            disabled={stopping}
            onClick={onCancel}
          >
            {stopping ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <X className="mr-1 h-3 w-3" />
            )}
            {stopping ? "停止中..." : "停止生成"}
          </Button>
        )}
      </div>
      {currentAction && (
        <p className="text-xs text-muted-foreground/70 pl-[30px]">{currentAction}</p>
      )}
    </div>
  );
}

// ─── Inquiry Tab ────────────────────────────────────────────

const GAP_CATEGORY_LABELS: Record<string, string> = {
  order: "订单", supplier: "供应商", company: "公司", delivery: "交付",
};

const INQUIRY_TEMPLATE_METHOD_LABELS: Record<string, string> = {
  exact: "精确绑定", user_selected: "手动", manual_override: "手动",
  agent_selected: "Agent", candidate_auto: "自动匹配",
  supplier: "供应商匹配", country: "国家匹配", single: "唯一模板", none: "未绑定",
};

function InquiryTab({
  order,
  onRedoSupplier,
  onGenerateAll,
  inquiryGenerating,
  inquiryStopping,
  inquirySteps,
  onCancelInquiry,
}: {
  order: Order;
  onRedoSupplier?: (supplierId: number, templateId?: number) => void;
  onGenerateAll?: (templateOverrides?: Record<number, number | null>, supplierIds?: number[]) => void;
  inquiryGenerating?: boolean;
  inquiryStopping?: boolean;
  inquirySteps?: InquiryStep[];
  onCancelInquiry?: () => void;
}) {
  const [downloadingFile, setDownloadingFile] = useState<string | null>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [previewSupplierId, setPreviewSupplierId] = useState<number | null>(null);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);
  const [previewHtml, setPreviewHtml] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [allTemplates, setAllTemplates] = useState<SupplierTemplate[]>([]);
  const [templateOverrides, setTemplateOverrides] = useState<Record<number, number | null>>({});
  // master-detail: selectedSupplierId replaces expandedSupplierId
  const [selectedSupplierId, setSelectedSupplierId] = useState<number | null>(null);
  // field editing state for the detail panel
  const [detailEdits, setDetailEdits] = useState<Record<string, string>>({});
  const [detailDirty, setDetailDirty] = useState(false);
  const [detailSaving, setDetailSaving] = useState(false);
  const [dataPreview, setDataPreview] = useState<InquiryDataPreview | null>(null);
  const [dataPreviewLoading, setDataPreviewLoading] = useState(false);
  const [dataPreviewOpen, setDataPreviewOpen] = useState(false);
  const [confirmGenerateOpen, setConfirmGenerateOpen] = useState(false);
  const [confirmAutoMatchOpen, setConfirmAutoMatchOpen] = useState(false);
  const [confirmOverwriteOpen, setConfirmOverwriteOpen] = useState(false);

  // ── Readiness data (primary data source) ──
  const [readiness, setReadiness] = useState<InquiryReadiness | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const prevGeneratingRef = useRef(false);

  const loadReadiness = useCallback(async (overrides?: Record<number, number | null>) => {
    setReadinessLoading(true);
    setReadinessError(null);
    try {
      const data = await getInquiryReadiness(order.id, overrides);
      setReadiness(data);
    } catch (err) {
      setReadinessError(err instanceof Error ? err.message : "加载询价工作台失败");
    } finally {
      setReadinessLoading(false);
    }
  }, [order.id]);

  useEffect(() => {
    listSupplierTemplates().then(setAllTemplates).catch(() => {});
  }, []);

  useEffect(() => {
    if (order.match_results && order.match_results.length > 0) {
      loadReadiness(templateOverrides);
    }
  }, [order.id, order.match_results?.length, loadReadiness, templateOverrides]);

  // Reload readiness once after generation completes (true → false transition)
  useEffect(() => {
    if (prevGeneratingRef.current && !inquiryGenerating) {
      loadReadiness(templateOverrides);
    }
    prevGeneratingRef.current = !!inquiryGenerating;
  }, [inquiryGenerating, loadReadiness]);


  // Derive supplier list
  const inquiry = order.inquiry_data;
  const readinessSuppliers = readiness?.suppliers || {};
  const readinessIds = Object.keys(readinessSuppliers).map(Number).sort((a, b) => a - b);
  const displaySupplierIds = readinessIds.length > 0
    ? readinessIds
    : Object.keys(inquiry?.suppliers || {}).map(Number).sort((a, b) => a - b);

  const totalProducts = displaySupplierIds.reduce((sum, sid) => {
    const rd = readinessSuppliers[String(sid)];
    return sum + (rd?.product_count ?? 0);
  }, 0);
  const totalElapsed = inquiry?.total_elapsed_seconds;
  const summary = readiness?.summary;

  // Completed files for "download all"
  const completedFiles = useMemo(() => {
    const files: { supplierId: number; filename: string }[] = [];
    for (const sid of displaySupplierIds) {
      const rd = readinessSuppliers[String(sid)];
      if (rd?.file?.filename) {
        files.push({ supplierId: sid, filename: rd.file.filename });
      }
    }
    return files;
  }, [displaySupplierIds, readinessSuppliers]);

  // Blocked supplier names (for confirm dialog)
  const blockedSuppliers = useMemo(() => {
    return displaySupplierIds
      .filter((sid) => readinessSuppliers[String(sid)]?.status === "blocked")
      .map((sid) => {
        const item = readinessSuppliers[String(sid)];
        return {
          supplierId: sid,
          name: item?.supplier_name || `#${sid}`,
          reason: item?.error || "缺少必填字段",
        };
      });
  }, [displaySupplierIds, readinessSuppliers]);

  const readySupplierIds = useMemo(() => {
    return displaySupplierIds.filter((sid) => readinessSuppliers[String(sid)]?.status !== "blocked");
  }, [displaySupplierIds, readinessSuppliers]);

  // Suppliers using auto-matched template (no exact binding) — need user confirmation
  const autoMatchSuppliers = useMemo(() => {
    return displaySupplierIds
      .filter((sid) => readinessSuppliers[String(sid)]?.template?.method === "candidate_auto")
      .map((sid) => {
        const item = readinessSuppliers[String(sid)];
        return {
          supplierId: sid,
          name: item?.supplier_name || `#${sid}`,
          templateName: item?.template?.name || "未知模板",
        };
      });
  }, [displaySupplierIds, readinessSuppliers]);

  // Initialize detail edits when selected supplier changes OR readiness finishes loading
  useEffect(() => {
    if (selectedSupplierId == null) return;
    if (readinessLoading) return; // wait for data before initializing
    const rd = readinessSuppliers[String(selectedSupplierId)];
    if (!rd) return;
    const init: Record<string, string> = {};
    for (const f of rd.fields || []) {
      if (f.status === "overridden" && f.value) init[f.cell] = f.value;
    }
    setDetailEdits(init);
    setDetailDirty(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSupplierId, readinessLoading]);

  // Save detail edits (explicit button)
  async function handleDetailSave() {
    if (selectedSupplierId == null) return;
    setDetailSaving(true);
    try {
      await saveInquiryFieldOverrides(order.id, selectedSupplierId, detailEdits);
      setDetailDirty(false);
      toast.success("已保存");
      loadReadiness(templateOverrides);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setDetailSaving(false);
    }
  }

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

  async function handleDownloadAll() {
    setDownloadingAll(true);
    try {
      for (const f of completedFiles) {
        await downloadOrderFile(order.id, f.filename);
        // Small delay between downloads to avoid browser blocking
        if (completedFiles.length > 1) {
          await new Promise((r) => setTimeout(r, 300));
        }
      }
      toast.success(`${completedFiles.length} 个文件下载完成`);
    } catch {
      toast.error("部分文件下载失败");
    } finally {
      setDownloadingAll(false);
    }
  }

  async function handlePreview(supplierId: number) {
    setPreviewSupplierId(supplierId);
    setPreviewLoading(true);
    try {
      const html = await getInquiryPreview(order.id, supplierId);
      setPreviewHtml(html);
    } catch {
      setPreviewHtml("<p>预览加载失败，请下载文件查看。</p>");
    } finally {
      setPreviewLoading(false);
    }
  }

  function getSelectedTemplateId(sid: number): number | null {
    if (sid in templateOverrides) return templateOverrides[sid];
    const rd = readinessSuppliers[String(sid)];
    return rd?.template?.id ?? null;
  }

  function buildOverridesForGenerate(): Record<number, number | null> | undefined {
    const overrides: Record<number, number | null> = {};
    let hasOverride = false;
    for (const sid of displaySupplierIds) {
      if (sid in templateOverrides) {
        overrides[sid] = templateOverrides[sid];
        hasOverride = true;
      }
    }
    return hasOverride ? overrides : undefined;
  }

  function handleGenerateClick() {
    if (readySupplierIds.length === 0) {
      toast.error("当前没有可生成询价单的供应商");
      return;
    }
    if (order.inquiry_data) {
      setConfirmOverwriteOpen(true);
      return;
    }
    if (autoMatchSuppliers.length > 0) {
      setConfirmAutoMatchOpen(true);
    } else if (blockedSuppliers.length > 0) {
      setConfirmGenerateOpen(true);
    } else {
      onGenerateAll?.(buildOverridesForGenerate());
    }
  }

  // Product data dialog (read-only view of product rows)
  async function handleProductDataPreview(sid: number) {
    setDataPreviewLoading(true);
    setDataPreviewOpen(true);
    try {
      const tid = getSelectedTemplateId(sid);
      const preview = await getInquiryDataPreview(order.id, sid, tid);
      setDataPreview(preview);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
      setDataPreviewOpen(false);
    } finally {
      setDataPreviewLoading(false);
    }
  }

  if (!inquiry && displaySupplierIds.length === 0) {
    return (
      <div className="h-full overflow-y-auto px-6 py-5">
        <Card>
          <CardContent className="py-10">
            <div className="flex flex-col items-center justify-center gap-3 text-center">
              {readinessLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              ) : (
                <FileSpreadsheet className="h-5 w-5 text-muted-foreground" />
              )}
              <div className="space-y-1">
                <p className="text-sm font-medium">询价工作台</p>
                <p className="text-xs text-muted-foreground">
                  {readinessError
                    ? readinessError
                    : "当前没有可生成询价单的供应商。请先完成产品匹配。"}
                </p>
              </div>
              {readinessError && (
                <Button variant="outline" size="sm" className="text-xs" onClick={() => loadReadiness(templateOverrides)}>
                  重试加载
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const readyCount = summary?.ready ?? 0;
  const blockedCount = (summary?.blocked ?? 0) + (summary?.needs_input ?? 0);
  const totalCount = summary?.total ?? displaySupplierIds.length;

  // selected supplier data
  const selectedRd = selectedSupplierId != null ? readinessSuppliers[String(selectedSupplierId)] : null;
  const selectedFields = selectedRd?.fields || [];
  const selectedBlockingGaps = selectedFields.filter((f) => f.status === "missing" && f.severity === "blocking");

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Progress bar (when generating) ── */}
      {inquiryGenerating && inquirySteps && (
        <InquiryProgress
          steps={inquirySteps}
          order={order}
          onCancel={onCancelInquiry}
          stopping={inquiryStopping}
        />
      )}

      {/* ── Top bar ── */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b shrink-0">
        <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
          <span className="font-medium text-foreground text-sm">询价单</span>
          <span className="text-muted-foreground/50">&middot;</span>
          <span>{displaySupplierIds.length} 供应商</span>
          <span className="text-muted-foreground/50">&middot;</span>
          <span>{totalProducts} 产品</span>
          {totalElapsed != null && <><span className="text-muted-foreground/50">&middot;</span><span>{totalElapsed}s</span></>}
          {summary && <>
            <span className="text-muted-foreground/50">&middot;</span>
            {summary.ready > 0 && <span className="text-emerald-600 flex items-center gap-0.5"><CheckCircle2 className="h-3 w-3" />{summary.ready} 就绪</span>}
            {summary.needs_input > 0 && <span className="text-amber-600 flex items-center gap-0.5"><AlertTriangle className="h-3 w-3" />{summary.needs_input} 需补充</span>}
            {summary.blocked > 0 && <span className="text-destructive flex items-center gap-0.5"><X className="h-3 w-3" />{summary.blocked} 阻塞</span>}
          </>}
          {readinessLoading && <Loader2 className="h-3 w-3 animate-spin" />}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {completedFiles.length > 1 && (
            <Button variant="outline" size="sm" className="text-xs h-7" disabled={downloadingAll} onClick={handleDownloadAll}>
              {downloadingAll ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Download className="mr-1 h-3 w-3" />}
              全部下载 ({completedFiles.length})
            </Button>
          )}
          {onGenerateAll && (
            <Button size="sm" className="text-xs h-7" disabled={inquiryGenerating || inquiryStopping} onClick={handleGenerateClick}>
              {inquiryGenerating || inquiryStopping ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <FileSpreadsheet className="mr-1 h-3 w-3" />}
              {inquiryStopping ? "停止中..." : inquiryGenerating ? "生成中..." : blockedCount > 0 ? `生成 ${readyCount}/${totalCount}` : "全部生成"}
            </Button>
          )}
        </div>
      </div>

      {readinessError && (
        <div className="flex items-center justify-between gap-3 mx-4 mt-3 rounded-md border border-amber-500/30 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-500/20 dark:bg-amber-950/30 dark:text-amber-300 shrink-0">
          <div className="flex items-center gap-2"><AlertTriangle className="h-3.5 w-3.5 shrink-0" /><span>{readinessError}</span></div>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => loadReadiness(templateOverrides)}>重试</Button>
        </div>
      )}

      {/* ── Master-detail layout ── */}
      <div className="flex flex-1 min-h-0">
        {/* Left: supplier list */}
        <div className="w-64 shrink-0 border-r overflow-y-auto">
          {displaySupplierIds.map((sid) => {
            const rd = readinessSuppliers[String(sid)];
            if (!rd) return null;
            const isSelected = selectedSupplierId === sid;
            const blocking = (rd.fields || []).filter((f) => f.status === "missing" && f.severity === "blocking").length;
            const warning = (rd.fields || []).filter((f) => f.status === "missing" && f.severity === "warning").length;
            const statusColor =
              rd.gen_status === "completed" ? "text-emerald-600 dark:text-emerald-400" :
              rd.gen_status === "error" ? "text-destructive" :
              rd.status === "blocked" ? "text-destructive" :
              rd.status === "needs_input" ? "text-amber-600" :
              "text-muted-foreground";
            const statusLabel =
              rd.gen_status === "completed" ? "已完成" :
              rd.gen_status === "generating" ? "生成中" :
              rd.gen_status === "error" ? "失败" :
              rd.status === "blocked" ? "无模板" :
              rd.status === "needs_input" ? `缺 ${blocking} 必填` :
              "待生成";
            return (
              <button
                key={sid}
                onClick={() => setSelectedSupplierId(sid)}
                className={`w-full text-left px-4 py-3 border-b transition-colors ${
                  isSelected ? "bg-primary/5 border-l-2 border-l-primary" : "hover:bg-muted/50 border-l-2 border-l-transparent"
                }`}
              >
                <div className="text-sm font-medium truncate">{rd.supplier_name || `供应商 #${sid}`}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[11px] text-muted-foreground">{rd.product_count ?? 0} 产品</span>
                  <span className={`text-[11px] ${statusColor}`}>{statusLabel}</span>
                  {warning > 0 && rd.gen_status !== "completed" && (
                    <span className="text-[11px] text-amber-500">{warning} 可选</span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Right: detail panel */}
        {selectedRd ? (
          <div className="flex-1 overflow-y-auto flex flex-col">
            {/* Detail header */}
            <div className="px-5 py-4 border-b shrink-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold truncate">{selectedRd.supplier_name || `供应商 #${selectedSupplierId}`}</h2>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    <span className="text-xs text-muted-foreground">{selectedRd.product_count ?? 0} 产品</span>
                    {selectedRd.subtotal != null && selectedRd.subtotal > 0 && (
                      <span className="text-xs text-muted-foreground">&middot; {selectedRd.currency || "¥"}{selectedRd.subtotal.toLocaleString()}</span>
                    )}
                    {selectedRd.gen_status === "completed" && selectedRd.elapsed_seconds != null && (
                      <span className="text-xs text-muted-foreground">&middot; {selectedRd.elapsed_seconds}s</span>
                    )}
                  </div>
                </div>
                {/* Action buttons */}
                <div className="flex items-center gap-1.5 shrink-0">
                  {selectedRd.file?.filename && (
                    <>
                      <Button variant="outline" size="sm" className="text-xs h-7" onClick={() => selectedSupplierId != null && handlePreview(selectedSupplierId)}>
                        <Eye className="mr-1 h-3 w-3" /> 预览
                      </Button>
                      <Button
                        variant="outline" size="sm" className="text-xs h-7"
                        disabled={downloadingFile === selectedRd.file.filename}
                        onClick={() => selectedRd.file?.filename && handleDownload(selectedRd.file.filename)}
                      >
                        {downloadingFile === selectedRd.file.filename
                          ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          : <Download className="mr-1 h-3 w-3" />}
                        下载
                      </Button>
                    </>
                  )}
                  <Button
                    variant="outline" size="sm" className="text-xs h-7"
                    onClick={() => selectedSupplierId != null && onRedoSupplier?.(selectedSupplierId, templateOverrides[selectedSupplierId] ?? undefined)}
                  >
                    <RotateCw className="mr-1 h-3 w-3" /> 重做
                  </Button>
                  {selectedRd.gen_status === "completed" && (
                    <Button variant="outline" size="sm" className="text-xs h-7"
                      onClick={() => selectedSupplierId != null && handleProductDataPreview(selectedSupplierId)}>
                      <FileSpreadsheet className="mr-1 h-3 w-3" /> 产品明细
                    </Button>
                  )}
                </div>
              </div>

              {/* Template selector */}
              <div className="flex items-center gap-2 mt-3">
                <span className="text-xs text-muted-foreground shrink-0">模板:</span>
                {selectedRd.gen_status !== "generating" ? (
                  <Select
                    value={getSelectedTemplateId(selectedSupplierId!) != null ? String(getSelectedTemplateId(selectedSupplierId!)) : "__none__"}
                    onValueChange={(val) => {
                      if (val === "__none__") return;
                      setTemplateOverrides((prev) => ({ ...prev, [selectedSupplierId!]: Number(val) }));
                    }}
                  >
                    <SelectTrigger className="h-7 text-xs max-w-[220px]">
                      <SelectValue placeholder="未选择" />
                    </SelectTrigger>
                    <SelectContent>
                      {getSelectedTemplateId(selectedSupplierId!) == null && (
                        <SelectItem value="__none__" disabled>未绑定可用模板</SelectItem>
                      )}
                      {allTemplates.map((t) => (
                        <SelectItem key={t.id} value={String(t.id)}>{t.template_name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <span className="text-xs">{selectedRd.template?.name || "—"}</span>
                )}
                {selectedRd.template?.method && (
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                    {INQUIRY_TEMPLATE_METHOD_LABELS[selectedRd.template.method] || selectedRd.template.method}
                  </span>
                )}
              </div>
            </div>

            {/* Error */}
            {selectedRd.error && (
              <div className="mx-5 mt-4 flex items-start gap-1.5 text-xs text-destructive bg-destructive/5 rounded-md px-3 py-2 shrink-0">
                <XCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                <span className="break-all">{selectedRd.error}</span>
              </div>
            )}

            {/* Field list */}
            {selectedFields.length > 0 && (
              <div className="px-5 py-4 flex-1">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium">表头字段</span>
                    {selectedBlockingGaps.length > 0 && (
                      <span className="text-xs text-destructive">{selectedBlockingGaps.length} 必填缺失</span>
                    )}
                  </div>
                  <Button
                    size="sm"
                    className="text-xs h-7"
                    disabled={!detailDirty || detailSaving}
                    onClick={handleDetailSave}
                  >
                    {detailSaving ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Save className="mr-1 h-3 w-3" />}
                    保存字段
                  </Button>
                </div>
                <div className="space-y-1.5">
                  {selectedFields.map((f) => {
                    const editVal = detailEdits[f.cell] ?? "";
                    if (f.status === "resolved") {
                      return (
                        <div key={f.cell} className="flex items-center gap-3 px-3 py-2 rounded-md bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400 text-xs">
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                          <span className="w-28 shrink-0 text-emerald-700/80 dark:text-emerald-400/70">{f.label}</span>
                          <span className="flex-1 truncate">{f.value ?? "—"}</span>
                          <span className="text-[10px] text-muted-foreground/40 shrink-0">{GAP_CATEGORY_LABELS[f.category] || f.category}</span>
                        </div>
                      );
                    }
                    const isBlocking = f.severity === "blocking";
                    const inputBg = f.status === "overridden"
                      ? "bg-blue-50 dark:bg-blue-950/30"
                      : isBlocking ? "bg-red-50 dark:bg-red-950/40" : "bg-amber-50 dark:bg-amber-950/40";
                    const labelColor = f.status === "overridden"
                      ? "text-blue-700 dark:text-blue-400"
                      : isBlocking ? "text-red-700 dark:text-red-400" : "text-amber-700 dark:text-amber-400";
                    return (
                      <div key={f.cell} className={`flex items-center gap-3 px-3 py-1.5 rounded-md ${inputBg} text-xs`}>
                        {f.status === "overridden"
                          ? <Pencil className={`h-3.5 w-3.5 shrink-0 ${labelColor}`} />
                          : isBlocking ? <XCircle className={`h-3.5 w-3.5 shrink-0 ${labelColor}`} />
                          : <AlertTriangle className={`h-3.5 w-3.5 shrink-0 ${labelColor}`} />}
                        <span className={`w-28 shrink-0 ${labelColor}`}>{f.label}</span>
                        <input
                          className="flex-1 min-w-0 bg-white dark:bg-background border border-border rounded px-2 py-1 text-xs text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 transition-colors"
                          placeholder={`输入${f.label}...`}
                          value={editVal || (f.status === "overridden" ? f.value ?? "" : "")}
                          onChange={(e) => {
                            setDetailEdits((prev) => ({ ...prev, [f.cell]: e.target.value }));
                            setDetailDirty(true);
                          }}
                        />
                        <span className="text-[10px] text-muted-foreground/40 shrink-0">{GAP_CATEGORY_LABELS[f.category] || f.category}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Verify results */}
            {(selectedRd.verify_results || []).filter((r) => r.status === "fail").length > 0 && (
              <div className="px-5 pb-4 shrink-0">
                <p className="text-xs font-medium text-muted-foreground mb-2">校验失败</p>
                <div className="space-y-1">
                  {(selectedRd.verify_results || []).filter((r) => r.status === "fail").map((r, i) => (
                    <div key={i} className="text-[11px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded px-2.5 py-1.5 flex items-center gap-1.5">
                      <XCircle className="h-3 w-3 shrink-0" />
                      <span>{r.annotation || r.cell}</span>
                      {r.reason && <span className="text-muted-foreground">— {r.reason}</span>}
                      {r.suggestion && <span className="ml-auto text-emerald-600 dark:text-emerald-400 shrink-0">→ {r.suggestion}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            <div className="text-center space-y-2">
              <FileSpreadsheet className="h-8 w-8 mx-auto text-muted-foreground/30" />
              <p>选择左侧供应商查看详情</p>
            </div>
          </div>
        )}
      </div>

      {/* ── Dialogs ── */}

      {/* Confirm auto-matched templates */}
      <AlertDialog open={confirmAutoMatchOpen} onOpenChange={setConfirmAutoMatchOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>以下供应商未绑定模板</AlertDialogTitle>
            <AlertDialogDescription>
              以下供应商没有精确绑定的模板，系统将自动选择候选模板生成。
              <span className="block mt-2 space-y-1">
                {autoMatchSuppliers.map((item) => (
                  <span key={item.supplierId} className="block text-xs text-foreground">
                    {item.name}：将使用「{item.templateName}」
                  </span>
                ))}
              </span>
              <span className="block mt-2">是否继续？</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => {
              setConfirmAutoMatchOpen(false);
              if (blockedSuppliers.length > 0) setConfirmGenerateOpen(true);
              else onGenerateAll?.(buildOverridesForGenerate());
            }}>继续生成</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm blocked suppliers */}
      <AlertDialog open={confirmGenerateOpen} onOpenChange={setConfirmGenerateOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>部分供应商缺必填字段</AlertDialogTitle>
            <AlertDialogDescription>
              以下供应商当前不参与生成：
              <span className="block mt-2 space-y-1">
                {blockedSuppliers.map((item) => (
                  <span key={item.supplierId} className="block text-xs text-muted-foreground">{item.name}: {item.reason}</span>
                ))}
              </span>
              <span className="block mt-2">是否跳过这些供应商，只生成其余可用供应商？</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => { setConfirmGenerateOpen(false); onGenerateAll?.(buildOverridesForGenerate(), readySupplierIds); }}>继续生成</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Preview side panel */}
      {previewSupplierId !== null && (
        <div className="fixed inset-y-0 right-0 z-40 w-[44%] border-l bg-background shadow-2xl flex flex-col">
          <div className="flex items-center justify-between gap-3 px-4 py-3 border-b">
            <div className="min-w-0">
              <p className="text-sm font-medium truncate">{readinessSuppliers[String(previewSupplierId)]?.supplier_name || `供应商 #${previewSupplierId}`}</p>
              <p className="text-xs text-muted-foreground">询价单预览</p>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setPreviewFullscreen(true)}><Maximize2 className="h-4 w-4" /></Button>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => { setPreviewSupplierId(null); setPreviewFullscreen(false); }}><X className="h-4 w-4" /></Button>
            </div>
          </div>
          <div className="flex-1 overflow-auto">
            {previewLoading ? <div className="flex items-center justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              : <div className="excel-preview p-2" dangerouslySetInnerHTML={{ __html: previewHtml }} />}
          </div>
        </div>
      )}

      <Dialog open={previewFullscreen} onOpenChange={setPreviewFullscreen}>
        <DialogContent className="max-w-[95vw] w-[95vw] max-h-[95vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="text-sm">
              {previewSupplierId != null ? readinessSuppliers[String(previewSupplierId)]?.supplier_name || `供应商 #${previewSupplierId}` : "询价单预览"}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-auto">
            {previewLoading ? <div className="flex items-center justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              : <div className="excel-preview p-2" dangerouslySetInnerHTML={{ __html: previewHtml }} />}
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOverwriteOpen} onOpenChange={setConfirmOverwriteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>重新生成询价单</AlertDialogTitle>
            <AlertDialogDescription>
              当前订单已生成过询价单，重新生成将覆盖已有结果。是否继续？
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setConfirmOverwriteOpen(false);
                if (autoMatchSuppliers.length > 0) {
                  setConfirmAutoMatchOpen(true);
                } else if (blockedSuppliers.length > 0) {
                  setConfirmGenerateOpen(true);
                } else {
                  onGenerateAll?.(buildOverridesForGenerate());
                }
              }}
            >
              继续生成
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Product data dialog (read-only) */}
      <Dialog open={dataPreviewOpen} onOpenChange={setDataPreviewOpen}>
        <DialogContent className="max-w-5xl w-[90vw] max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="text-sm flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4" />
              产品明细 — {dataPreview?.supplier_name || "加载中..."}
              {dataPreview?.template.name && (
                <span className="text-xs font-normal text-muted-foreground ml-1">模板: {dataPreview.template.name}</span>
              )}
            </DialogTitle>
          </DialogHeader>
          {dataPreviewLoading ? (
            <div className="flex items-center justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : dataPreview ? (
            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {dataPreview.warnings.length > 0 && (
                <div className="space-y-1">
                  {dataPreview.warnings.map((w, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-xs text-amber-600 bg-amber-50 dark:bg-amber-950/50 rounded px-3 py-1.5">
                      <AlertTriangle className="h-3 w-3 shrink-0" /><span>{w}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Product data */}
              {dataPreview.products.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium mb-2 text-muted-foreground">
                    产品数据 ({dataPreview.total_products} 行{dataPreview.total_products > 20 ? "，显示前 20" : ""})
                  </h4>
                  <div className="overflow-x-auto rounded border border-border/50">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted/50">
                          <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">#</th>
                          {dataPreview.product_columns ? (
                            dataPreview.product_columns.map(([col, field]) => (
                              <th key={col} className="px-2 py-1.5 text-left font-medium text-muted-foreground">
                                {field}
                              </th>
                            ))
                          ) : (
                            <>
                              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">代码</th>
                              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">品名</th>
                              <th className="px-2 py-1.5 text-right font-medium text-muted-foreground">数量</th>
                              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">单位</th>
                              <th className="px-2 py-1.5 text-right font-medium text-muted-foreground">单价</th>
                            </>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {dataPreview.products.map((p, i) => (
                          <tr key={i} className="border-t border-border/30 hover:bg-muted/20">
                            <td className="px-2 py-1 text-muted-foreground/50">{p._index as number}</td>
                            {dataPreview.product_columns ? (
                              dataPreview.product_columns.map(([col, field]) => (
                                <td key={col} className={`px-2 py-1 ${
                                  field === "quantity" || field === "unit_price" ? "text-right font-mono" : ""
                                } ${p[field] == null ? "text-muted-foreground/30 italic" : ""}`}>
                                  {p[field] != null ? String(p[field]) : "—"}
                                </td>
                              ))
                            ) : (
                              <>
                                <td className="px-2 py-1 font-mono">{String(p.product_code ?? "")}</td>
                                <td className="px-2 py-1 max-w-[200px] truncate">{String(p.product_name ?? "")}</td>
                                <td className="px-2 py-1 text-right font-mono">{p.quantity != null ? String(p.quantity) : "—"}</td>
                                <td className="px-2 py-1">{String(p.unit ?? "")}</td>
                                <td className="px-2 py-1 text-right font-mono">{p.unit_price != null ? String(p.unit_price) : "—"}</td>
                              </>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Formula columns */}
              {dataPreview.formula_columns && dataPreview.formula_columns.length > 0 && (
                <div className="text-xs text-muted-foreground">
                  <span className="font-medium">公式列: </span>
                  {dataPreview.formula_columns.map((c) => (
                    <span key={c} className="inline-block font-mono bg-purple-500/10 text-purple-400 px-1.5 py-0.5 rounded mr-1">{c}</span>
                  ))}
                </div>
              )}

              {/* Summary formulas */}
              {dataPreview.summary_formulas && dataPreview.summary_formulas.length > 0 && (
                <div className="text-xs text-muted-foreground">
                  <span className="font-medium">汇总公式: </span>
                  {dataPreview.summary_formulas.map((sf, i) => (
                    <span key={i} className="inline-block font-mono bg-amber-500/10 text-amber-400 px-1.5 py-0.5 rounded mr-1">
                      {sf.cell} ({sf.label || sf.type})
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
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
                        {att.uploaded_at ? new Date(toUTC(att.uploaded_at)).toLocaleString("zh-CN") : ""}
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

// ─── Assistant Drawer ───────────────────────────────────────

type ActivityItemType =
  | { type: "user"; content: string; id: number }
  | { type: "answer"; content: string; id: number; streaming?: boolean }
  | { type: "thinking"; content: string; id: number }
  | { type: "tool_running"; label: string; id: number }
  | { type: "tool_done"; label: string; id: number }
  | { type: "tool_error"; label: string; id: number }
  | { type: "error"; content: string; id: number };

function messagesToActivityItems(messages: ChatMessage[]): ActivityItemType[] {
  const items: ActivityItemType[] = [];
  for (const msg of messages) {
    if (msg.role === "user") {
      items.push({ type: "user", content: msg.content, id: msg.id });
    } else if (msg.msg_type === "thinking") {
      items.push({ type: "thinking", content: msg.content, id: msg.id });
    } else if (msg.msg_type === "action") {
      let label = msg.content;
      try {
        const parsed = JSON.parse(msg.content);
        label = parsed.tool_name ? `调用工具: ${parsed.tool_name}` : label;
      } catch { /* ok */ }
      items.push({ type: "tool_running", label, id: msg.id });
    } else if (msg.msg_type === "observation") {
      // Find matching action
      const actionItem = items.findLast?.((i) => i.type === "tool_running");
      const label = actionItem?.type === "tool_running" ? actionItem.label : "工具调用完成";
      items.push({ type: "tool_done", label, id: msg.id });
    } else if (msg.msg_type === "error_observation") {
      items.push({ type: "tool_error", label: msg.content.slice(0, 80), id: msg.id });
    } else if (msg.msg_type === "error" || msg.role === "tool") {
      items.push({ type: "error", content: msg.content, id: msg.id });
    } else if (msg.role === "assistant") {
      items.push({ type: "answer", content: msg.content, id: msg.id, streaming: msg.streaming });
    }
  }
  return items;
}

function AssistantDrawer({
  open,
  onToggle,
  messages,
  input,
  onInputChange,
  onSend,
  onStop,
  onNewSession,
  busy,
  agentStatus,
  scrollRef,
  unmatchedCount,
  pdfOpen,
}: {
  open: boolean;
  onToggle: () => void;
  messages: ChatMessage[];
  input: string;
  onInputChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  onNewSession?: () => void;
  busy: boolean;
  agentStatus: "idle" | "running" | "stopping" | "done" | "error";
  scrollRef: React.RefObject<HTMLDivElement | null>;
  unmatchedCount: number;
  pdfOpen: boolean;
}) {
  const items = messagesToActivityItems(messages);
  const rightOffset = pdfOpen ? "right-[calc(44%+16px)]" : "right-4";

  return (
    <div
      className={`fixed bottom-0 ${rightOffset} z-50 w-[360px] transition-all duration-200`}
      style={{ maxHeight: open ? "460px" : "44px" }}
    >
      {/* Header / toggle bar */}
      <div className="w-full h-11 px-4 flex items-center gap-2 bg-card border border-border/60 rounded-t-xl shadow-lg">
        <button
          type="button"
          className="flex items-center gap-2 flex-1 min-w-0 hover:opacity-70 transition-opacity"
          onClick={onToggle}
        >
          <Sparkles className="h-3.5 w-3.5 text-primary shrink-0" />
          <span className="text-xs font-medium flex-1 text-left">AI 助手</span>
        </button>
        {unmatchedCount > 0 && !open && (
          <span className="text-[10px] bg-destructive/10 text-destructive px-1.5 py-0.5 rounded-full font-medium shrink-0">
            {unmatchedCount} 未匹配
          </span>
        )}
        {agentStatus === "running" && (
          <Loader2 className="h-3 w-3 text-primary animate-spin shrink-0" />
        )}
        {open && onNewSession && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onNewSession(); }}
            className="p-1 rounded hover:bg-muted/50 transition-colors shrink-0"
            title="新建对话"
          >
            <SquarePen className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
          </button>
        )}
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground shrink-0 transition-transform duration-200 ${open ? "rotate-0" : "rotate-180"}`}
          onClick={onToggle}
        />
      </div>

      {/* Body */}
      {open && (
        <div className="flex flex-col bg-card border-x border-b border-border/60 shadow-lg rounded-b-xl overflow-hidden"
          style={{ height: "416px" }}>
          {/* Messages */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-3 py-3 space-y-2 text-xs"
          >
            {items.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-4">
                <MessageSquare className="h-8 w-8 text-muted-foreground/30" />
                <p className="text-muted-foreground text-[11px]">
                  和 AI 助手对话，查询产品信息、分析未匹配原因或更新履约状态
                </p>
                {unmatchedCount > 0 && (
                  <p className="text-destructive/70 text-[10px]">
                    当前有 {unmatchedCount} 个未匹配产品
                  </p>
                )}
              </div>
            ) : (
              items.map((item) => {
                if (item.type === "user") {
                  return (
                    <div key={item.id} className="flex justify-end">
                      <div className="max-w-[85%] bg-primary/10 text-foreground rounded-lg px-3 py-1.5 text-[11px] leading-relaxed">
                        {item.content}
                      </div>
                    </div>
                  );
                }
                if (item.type === "answer") {
                  return (
                    <div key={item.id} className="flex gap-2">
                      <Sparkles className="h-3 w-3 text-primary mt-0.5 shrink-0" />
                      <div className="flex-1 text-[11px] leading-relaxed text-foreground/90">
                        {item.streaming ? (
                          <span className="whitespace-pre-wrap">
                            {item.content}
                            <span className="inline-block w-1 h-3 bg-primary/60 animate-pulse ml-0.5 align-middle" />
                          </span>
                        ) : (
                          <MarkdownContent content={item.content} />
                        )}
                      </div>
                    </div>
                  );
                }
                if (item.type === "thinking") {
                  return (
                    <div key={item.id} className="flex gap-2 opacity-60">
                      <Loader2 className="h-3 w-3 text-muted-foreground mt-0.5 shrink-0 animate-spin" />
                      <span className="text-[10px] text-muted-foreground italic line-clamp-2">{item.content}</span>
                    </div>
                  );
                }
                if (item.type === "tool_running") {
                  return (
                    <div key={item.id} className="flex gap-2 opacity-70">
                      <Wrench className="h-3 w-3 text-amber-500 mt-0.5 shrink-0" />
                      <span className="text-[10px] text-muted-foreground line-clamp-1">{item.label}</span>
                    </div>
                  );
                }
                if (item.type === "tool_done") {
                  return (
                    <div key={item.id} className="flex gap-2 opacity-50">
                      <CheckCheck className="h-3 w-3 text-emerald-500 mt-0.5 shrink-0" />
                      <span className="text-[10px] text-muted-foreground line-clamp-1">{item.label}</span>
                    </div>
                  );
                }
                if (item.type === "tool_error" || item.type === "error") {
                  return (
                    <div key={item.id} className="flex gap-2">
                      <AlertCircle className="h-3 w-3 text-destructive mt-0.5 shrink-0" />
                      <span className="text-[10px] text-destructive line-clamp-2">
                        {item.type === "tool_error" ? item.label : item.content}
                      </span>
                    </div>
                  );
                }
                return null;
              })
            )}
          </div>

          {/* Input */}
          <div className="shrink-0 px-3 py-2 border-t border-border/40 flex items-center gap-2">
            <input
              className="flex-1 bg-muted/40 rounded-lg px-3 py-1.5 text-xs outline-none focus:ring-1 focus:ring-primary/30 placeholder:text-muted-foreground/50"
              placeholder="输入问题..."
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !busy) {
                  e.preventDefault();
                  onSend();
                }
              }}
              disabled={busy}
            />
            {agentStatus === "running" ? (
              <button
                type="button"
                className="h-7 w-7 flex items-center justify-center rounded-lg text-destructive hover:bg-destructive/10 transition-colors shrink-0"
                onClick={onStop}
                title="停止"
              >
                <StopCircle className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="button"
                className="h-7 w-7 flex items-center justify-center rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 transition-colors shrink-0"
                onClick={onSend}
                disabled={!input.trim() || busy}
                title="发送"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
