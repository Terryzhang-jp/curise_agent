"use client";

import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

interface AnomalyPreviewProps {
  data: Record<string, unknown>;
}

const SECTION_CONFIG = {
  price: {
    label: "价格异常",
    icon: XCircle,
    color: "text-destructive",
    dotColor: "bg-destructive",
    bgColor: "bg-destructive/5 border-destructive/15",
  },
  quantity: {
    label: "数量异常",
    icon: AlertTriangle,
    color: "text-amber-500",
    dotColor: "bg-amber-500",
    bgColor: "bg-amber-500/5 border-amber-500/15",
  },
  completeness: {
    label: "完整性问题",
    icon: AlertTriangle,
    color: "text-amber-500",
    dotColor: "bg-amber-500",
    bgColor: "bg-amber-500/5 border-amber-500/15",
  },
} as const;

export default function AnomalyPreview({ data }: AnomalyPreviewProps) {
  const priceAnomalies = (data.price_anomalies || []) as Array<Record<string, unknown>>;
  const quantityAnomalies = (data.quantity_anomalies || []) as Array<Record<string, unknown>>;
  const completenessIssues = (data.completeness_issues || []) as Array<Record<string, unknown>>;

  const totalIssues = priceAnomalies.length + quantityAnomalies.length + completenessIssues.length;

  const sections: { key: keyof typeof SECTION_CONFIG; items: Array<Record<string, unknown>> }[] = [
    { key: "price", items: priceAnomalies },
    { key: "quantity", items: quantityAnomalies },
    { key: "completeness", items: completenessIssues },
  ];

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border/50">
        <div className="text-sm font-semibold">异常检测详情</div>
        <div className="text-[10px] text-muted-foreground mt-0.5">Phase 4: ANOMALY_DETECTION</div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-3">
          {sections.map(({ key, items }) => {
            const config = SECTION_CONFIG[key];
            const hasIssues = items.length > 0;
            return (
              <Card key={key} className={cn("text-center", hasIssues && config.bgColor)}>
                <CardContent className="pt-4 pb-3">
                  <div className={cn("text-lg font-semibold", hasIssues ? config.color : "text-foreground")}>
                    {items.length}
                  </div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">
                    {config.label}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* All clear */}
        {totalIssues === 0 && (
          <Card className="bg-emerald-500/10 border-emerald-500/20">
            <CardContent className="pt-5 pb-4 text-center">
              <CheckCircle2 className="h-5 w-5 text-emerald-500 mx-auto mb-2" />
              <div className="text-emerald-500 text-sm font-medium">未发现异常</div>
              <div className="text-emerald-500/70 text-xs mt-1">数据质量良好，可以继续处理</div>
            </CardContent>
          </Card>
        )}

        {/* Anomaly sections */}
        {sections.map(({ key, items }) => {
          if (items.length === 0) return null;
          const config = SECTION_CONFIG[key];

          return (
            <Card key={key}>
              <CardHeader className="pb-0">
                <CardTitle className="flex items-center gap-2">
                  <span className={cn("w-2 h-2 rounded-full", config.dotColor)} />
                  <span className={cn("text-xs font-medium uppercase tracking-wider", config.color)}>
                    {config.label}
                  </span>
                  <Badge variant="secondary" className="text-[10px] ml-auto">
                    {items.length}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-3">
                <div className="divide-y divide-border/50">
                  {items.map((item, i) => (
                    <AnomalyItem key={i} item={item} type={key} />
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function AnomalyItem({
  item,
  type,
}: {
  item: Record<string, unknown>;
  type: "price" | "quantity" | "completeness";
}) {
  const config = SECTION_CONFIG[type];

  if (type === "completeness") {
    const text =
      typeof item === "string"
        ? item
        : String(item.issue || item.description || JSON.stringify(item));
    return (
      <div className="py-2.5">
        <div className="text-xs text-muted-foreground">{text}</div>
        {item.product_name ? (
          <div className="text-[10px] text-muted-foreground/70 mt-1">
            产品: {String(item.product_name)}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="py-2.5">
      <div className="text-xs font-medium">{String(item.product_name || "未知产品")}</div>
      <div className="text-[10px] text-muted-foreground mt-1">
        {String(item.description || JSON.stringify(item))}
      </div>
      {type === "price" && (item.expected_price != null || item.actual_price != null) && (
        <div className="flex gap-3 mt-1.5 text-[10px]">
          {item.expected_price != null && (
            <span className="text-muted-foreground">
              预期: <span className="text-foreground">{String(item.expected_price)}</span>
            </span>
          )}
          {item.actual_price != null && (
            <span className="text-muted-foreground">
              实际: <span className={cn("font-medium", config.color)}>{String(item.actual_price)}</span>
            </span>
          )}
          {item.deviation != null && (
            <span className="text-muted-foreground">
              偏差: <span className={cn("font-medium", config.color)}>{String(item.deviation)}</span>
            </span>
          )}
        </div>
      )}
      {type === "quantity" && (item.expected_quantity != null || item.actual_quantity != null) && (
        <div className="flex gap-3 mt-1.5 text-[10px]">
          {item.expected_quantity != null && (
            <span className="text-muted-foreground">
              预期: <span className="text-foreground">{String(item.expected_quantity)}</span>
            </span>
          )}
          {item.actual_quantity != null && (
            <span className="text-muted-foreground">
              实际: <span className={cn("font-medium", config.color)}>{String(item.actual_quantity)}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
