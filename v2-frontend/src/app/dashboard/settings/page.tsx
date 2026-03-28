"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/page-header";
import FieldSchemaTab from "./FieldSchemaTab";
import OrderFormatTab from "./OrderFormatTab";
import SupplierTemplateTab from "./SupplierTemplateTab";
import AIConfigTab from "./AIConfigTab";
import SupplierInfoTab from "./SupplierInfoTab";
import DeliveryLocationTab from "./DeliveryLocationTab";
import CompanyConfigTab from "./CompanyConfigTab";
import AgentMemoryTab from "./AgentMemoryTab";

export default function SettingsPage() {
  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 px-6 pt-6">
        <PageHeader
          title="设置中心"
          description="管理字段定义、订单格式、供应商模板、业务配置和 AI 配置"
        />
      </div>

      <Tabs defaultValue="fields" className="flex-1 flex flex-col overflow-hidden px-6 mt-4">
        <TabsList className="shrink-0 w-fit">
          <TabsTrigger value="fields">字段管理</TabsTrigger>
          <TabsTrigger value="orders">订单格式</TabsTrigger>
          <TabsTrigger value="suppliers">供应商模板</TabsTrigger>
          <TabsTrigger value="supplier-info">供应商信息</TabsTrigger>
          <TabsTrigger value="delivery">配送点</TabsTrigger>
          <TabsTrigger value="company">公司信息</TabsTrigger>
          <TabsTrigger value="ai">AI 配置</TabsTrigger>
          <TabsTrigger value="memory">Agent 记忆</TabsTrigger>
        </TabsList>

        <TabsContent value="fields" className="flex-1 overflow-y-auto py-6">
          <FieldSchemaTab />
        </TabsContent>
        <TabsContent value="orders" className="flex-1 overflow-y-auto py-6">
          <OrderFormatTab />
        </TabsContent>
        <TabsContent value="suppliers" className="flex-1 overflow-y-auto py-6">
          <SupplierTemplateTab />
        </TabsContent>
        <TabsContent value="supplier-info" className="flex-1 overflow-y-auto py-6">
          <SupplierInfoTab />
        </TabsContent>
        <TabsContent value="delivery" className="flex-1 overflow-y-auto py-6">
          <DeliveryLocationTab />
        </TabsContent>
        <TabsContent value="company" className="flex-1 overflow-y-auto py-6">
          <CompanyConfigTab />
        </TabsContent>
        <TabsContent value="ai" className="flex-1 overflow-y-auto py-6">
          <AIConfigTab />
        </TabsContent>
        <TabsContent value="memory" className="flex-1 overflow-y-auto py-6">
          <AgentMemoryTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
