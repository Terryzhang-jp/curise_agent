"use client";

import { useEffect, useState, useCallback } from "react";
import type { CompanyConfigItem } from "@/lib/settings-api";
import { getCompanyConfig, updateCompanyConfig } from "@/lib/settings-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { toast } from "sonner";
import { Building2, Save } from "lucide-react";

export default function CompanyConfigTab() {
  const [items, setItems] = useState<CompanyConfigItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [edited, setEdited] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getCompanyConfig();
      setItems(data);
      setEdited({});
    } catch (e: unknown) {
      toast.error("加载失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleChange = (key: string, value: string) => {
    setEdited((prev) => ({ ...prev, [key]: value }));
  };

  const getValue = (item: CompanyConfigItem) => {
    return edited[item.key] !== undefined ? edited[item.key] : item.value;
  };

  const hasChanges = Object.keys(edited).length > 0;

  const handleSave = async () => {
    if (!hasChanges) return;
    setSaving(true);
    try {
      const payload = items.map((item) => ({
        key: item.key,
        value: edited[item.key] !== undefined ? edited[item.key] : item.value,
        label: item.label || undefined,
      }));
      await updateCompanyConfig(payload);
      toast.success("公司信息已更新");
      load();
    } catch (e: unknown) {
      toast.error("保存失败: " + (e instanceof Error ? e.message : "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="text-center py-8 text-muted-foreground">加载中...</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-muted-foreground" />
          <h3 className="text-lg font-semibold">公司信息</h3>
          <span className="text-sm text-muted-foreground">
            询价单中使用的公司联系方式
          </span>
        </div>
        <Button size="sm" onClick={handleSave} disabled={!hasChanges || saving}>
          <Save className="h-4 w-4 mr-1" />
          {saving ? "保存中..." : "保存"}
        </Button>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="grid gap-4 max-w-xl">
            {items.map((item) => (
              <div key={item.key} className="space-y-1.5">
                <Label>{item.label || item.key}</Label>
                <Input
                  value={getValue(item)}
                  onChange={(e) => handleChange(item.key, e.target.value)}
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
