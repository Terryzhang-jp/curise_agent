"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/page-header";
import { Sparkles } from "lucide-react";
import ProductsTab from "./ProductsTab";
import SuppliersTab from "./SuppliersTab";
import CountriesTab from "./CountriesTab";
import PortsTab from "./PortsTab";
import CategoriesTab from "./CategoriesTab";
import AIQueryTab from "./AIQueryTab";

export default function DataPage() {
  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 px-6 pt-6">
        <PageHeader
          title="数据管理"
          description="查看系统数据库中的产品、供应商等基础数据"
        />
      </div>

      <Tabs defaultValue="products" className="flex-1 flex flex-col overflow-hidden px-6 mt-4">
        <TabsList className="shrink-0 w-fit">
          <TabsTrigger value="products">产品</TabsTrigger>
          <TabsTrigger value="suppliers">供应商</TabsTrigger>
          <TabsTrigger value="countries">国家</TabsTrigger>
          <TabsTrigger value="ports">港口</TabsTrigger>
          <TabsTrigger value="categories">类别</TabsTrigger>
          <TabsTrigger value="ai-query">
            <Sparkles className="h-3.5 w-3.5 mr-1" />
            AI 查询
          </TabsTrigger>
        </TabsList>

        <TabsContent value="products" className="flex-1 overflow-hidden py-4">
          <ProductsTab />
        </TabsContent>
        <TabsContent value="suppliers" className="flex-1 overflow-hidden py-4">
          <SuppliersTab />
        </TabsContent>
        <TabsContent value="countries" className="flex-1 overflow-hidden py-4">
          <CountriesTab />
        </TabsContent>
        <TabsContent value="ports" className="flex-1 overflow-hidden py-4">
          <PortsTab />
        </TabsContent>
        <TabsContent value="categories" className="flex-1 overflow-hidden py-4">
          <CategoriesTab />
        </TabsContent>
        <TabsContent value="ai-query" className="flex-1 overflow-hidden py-4">
          <AIQueryTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
