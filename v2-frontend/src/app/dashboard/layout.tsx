"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { getUser, clearAuth, isAuthenticated } from "@/lib/auth";
import { logoutApi } from "@/lib/api";
import type { User } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  FileText,
  MessageSquare,
  Database,
  Settings,
  Users,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Menu,
  Sun,
  Moon,
  User as UserIcon,
  KeyRound,
} from "lucide-react";
import { ChangePasswordDialog } from "@/components/change-password-dialog";
import { ErrorBoundary } from "@/components/error-boundary";

type RoleName = "superadmin" | "admin" | "finance" | "employee";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  roles: RoleName[];
}

const NAV_ITEMS: NavItem[] = [
  { label: "订单管理", href: "/dashboard/orders", icon: FileText, roles: ["superadmin", "admin", "finance", "employee"] },
  { label: "AI 助手", href: "/dashboard/workspace", icon: MessageSquare, roles: ["superadmin", "admin", "employee"] },
  { label: "数据管理", href: "/dashboard/data", icon: Database, roles: ["superadmin", "admin", "employee"] },
  { label: "设置中心", href: "/dashboard/settings", icon: Settings, roles: ["superadmin", "admin"] },
  { label: "用户管理", href: "/dashboard/users", icon: Users, roles: ["superadmin"] },
];

function getVisibleNavItems(role: string): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role as RoleName));
}

function SidebarNav({
  collapsed,
  pathname,
  onNavigate,
  items,
}: {
  collapsed: boolean;
  pathname: string;
  onNavigate: (href: string) => void;
  items: NavItem[];
}) {
  return (
    <nav className="flex flex-col gap-1 px-2">
      {items.map((item) => {
        const isActive = pathname.startsWith(item.href);
        const Icon = item.icon;

        const button = (
          <button
            key={item.href}
            onClick={() => onNavigate(item.href)}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors w-full",
              isActive
                ? "bg-primary/10 text-primary font-medium"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span>{item.label}</span>}
          </button>
        );

        if (collapsed) {
          return (
            <Tooltip key={item.href}>
              <TooltipTrigger asChild>{button}</TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                {item.label}
              </TooltipContent>
            </Tooltip>
          );
        }

        return button;
      })}
    </nav>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [user, setUser] = useState<User | null>(null);
  const [mounted, setMounted] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);

  const visibleItems = useMemo(
    () => (user ? getVisibleNavItems(user.role) : []),
    [user],
  );

  useEffect(() => {
    setMounted(true);
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setUser(getUser());
  }, [router]);

  // Route guard: redirect if current page is not accessible
  useEffect(() => {
    if (!user || visibleItems.length === 0) return;

    const isAllowed = visibleItems.some((item) => pathname.startsWith(item.href));
    // Also allow /dashboard root
    if (!isAllowed && pathname !== "/dashboard") {
      router.replace(visibleItems[0].href);
    }
  }, [user, pathname, visibleItems, router]);

  const handleLogout = async () => {
    await logoutApi();
    clearAuth();
    router.push("/login");
  };

  if (!mounted || !user) return null;

  return (
    <div className="h-screen bg-background flex overflow-hidden">
      {/* Desktop Sidebar */}
      <aside
        className={cn(
          "hidden md:flex flex-col border-r border-border/50 bg-card/30 shrink-0 transition-all duration-200",
          collapsed ? "w-16" : "w-56"
        )}
      >
        {/* Logo */}
        <div className={cn("flex items-center h-14 px-4 shrink-0", collapsed && "justify-center")}>
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                className="text-primary"
              >
                <path d="M2 12C2 7 7 2 12 2s10 5 10 10" />
                <path d="M2 12c0 5 5 10 10 10" />
                <path d="M12 22c3 0 6-2 8-5" />
              </svg>
            </div>
            {!collapsed && (
              <span className="font-display text-sm font-semibold tracking-tight">
                CruiseAgent
              </span>
            )}
          </div>
        </div>

        <Separator className="opacity-50" />

        {/* Nav */}
        <div className="flex-1 py-4 overflow-y-auto">
          <SidebarNav
            collapsed={collapsed}
            pathname={pathname}
            onNavigate={(href) => router.push(href)}
            items={visibleItems}
          />
        </div>

        {/* Bottom controls */}
        <div className="px-2 pb-3 flex flex-col gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="w-full h-8"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              >
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {theme === "dark" ? "切换浅色" : "切换深色"}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="w-full h-8"
                onClick={() => setCollapsed(!collapsed)}
              >
                {collapsed ? (
                  <ChevronRight className="h-4 w-4" />
                ) : (
                  <ChevronLeft className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {collapsed ? "展开侧栏" : "收起侧栏"}
            </TooltipContent>
          </Tooltip>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-14 border-b border-border/50 flex items-center justify-between px-4 shrink-0 bg-background/80 backdrop-blur-sm">
          {/* Mobile menu */}
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden">
                <Menu className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-56 p-0">
              <div className="flex items-center h-14 px-4">
                <span className="font-display text-sm font-semibold">
                  CruiseAgent
                </span>
              </div>
              <Separator />
              <div className="py-4">
                <SidebarNav
                  collapsed={false}
                  pathname={pathname}
                  onNavigate={(href) => router.push(href)}
                  items={visibleItems}
                />
              </div>
            </SheetContent>
          </Sheet>

          <div className="hidden md:block" />

          {/* User menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2 h-8">
                <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                  <UserIcon className="h-3 w-3 text-primary" />
                </div>
                <span className="text-xs">{user.full_name}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <div className="px-2 py-1.5">
                <p className="text-xs font-medium">{user.full_name}</p>
                <p className="text-xs text-muted-foreground">{user.role}</p>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setShowChangePassword(true)}>
                <KeyRound className="mr-2 h-3 w-3" />
                <span className="text-xs">修改密码</span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleLogout} className="text-destructive">
                <LogOut className="mr-2 h-3 w-3" />
                <span className="text-xs">退出登录</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-hidden">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>

      {/* Change password dialog */}
      <ChangePasswordDialog
        open={showChangePassword}
        onOpenChange={setShowChangePassword}
      />
    </div>
  );
}
