import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { CheckCircle2, AlertCircle, Loader2, Clock } from "lucide-react";

type OrderStatus = "uploading" | "extracting" | "matching" | "ready" | "error";

const STATUS_CONFIG: Record<
  OrderStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ElementType; className: string }
> = {
  uploading: { label: "上传中", variant: "secondary", icon: Loader2, className: "animate-spin" },
  extracting: { label: "提取中", variant: "secondary", icon: Loader2, className: "animate-spin" },
  matching: { label: "匹配中", variant: "secondary", icon: Loader2, className: "animate-spin" },
  ready: { label: "已完成", variant: "default", icon: CheckCircle2, className: "text-emerald-500" },
  error: { label: "出错", variant: "destructive", icon: AlertCircle, className: "" },
};

export function StatusBadge({ status }: { status: OrderStatus }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.error;
  const Icon = config.icon;

  return (
    <Badge variant={config.variant} className="gap-1 text-[10px] font-medium">
      <Icon className={cn("h-3 w-3", config.className)} />
      {config.label}
    </Badge>
  );
}

export function ReviewedBadge() {
  return (
    <Badge variant="outline" className="gap-1 text-[10px] font-medium border-emerald-500/30 text-emerald-500">
      <CheckCircle2 className="h-3 w-3" />
      已审核
    </Badge>
  );
}
