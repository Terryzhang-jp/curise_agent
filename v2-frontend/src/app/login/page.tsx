"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";
import { saveAuth, isAuthenticated } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { ChangePasswordDialog } from "@/components/change-password-dialog";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [showForceChangePassword, setShowForceChangePassword] = useState(false);
  const [submitAttempted, setSubmitAttempted] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (isAuthenticated()) {
      router.replace("/dashboard");
    }
  }, [router]);

  const emailError = submitAttempted
    ? !email.trim()
      ? "请输入邮箱地址"
      : !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      ? "请输入有效的邮箱格式"
      : ""
    : "";
  const passwordError = submitAttempted && !password ? "请输入密码" : "";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitAttempted(true);
    if (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !password) return;
    setLoading(true);

    try {
      const res = await login({ email, password });
      saveAuth(res.access_token, res.user, res.refresh_token);

      if (res.user.is_default_password) {
        setShowForceChangePassword(true);
      } else {
        router.push("/dashboard");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordChanged = () => {
    setShowForceChangePassword(false);
    router.push("/dashboard");
  };

  if (!mounted) return null;

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-background">
      {/* Subtle background gradient */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-primary/3 rounded-full blur-[120px]" />
      </div>

      <div className="relative w-full max-w-sm space-y-8">
        {/* Logo + Tagline */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-primary/10">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className="text-primary"
            >
              <path d="M2 12C2 7 7 2 12 2s10 5 10 10" />
              <path d="M2 12c0 5 5 10 10 10" />
              <path d="M12 22c3 0 6-2 8-5" />
              <path d="M6 8.5c1.5-1.5 3.5-2.5 6-2.5s4.5 1 6 2.5" />
              <path d="M4 14c1 2 3 3.5 5.5 4" />
            </svg>
          </div>
          <div>
            <h1 className="font-display text-2xl font-semibold tracking-tight">
              CruiseAgent
            </h1>
            <p className="text-muted-foreground text-sm mt-1">
              智能邮轮供应链代理
            </p>
          </div>
        </div>

        {/* Login form */}
        <Card className="border-border/50 bg-card/50 backdrop-blur-sm">
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">邮箱</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  autoComplete="email"
                  autoFocus
                  aria-invalid={emailError ? true : undefined}
                />
                {emailError && <p className="text-xs text-destructive">{emailError}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">密码</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="输入密码"
                  autoComplete="current-password"
                  aria-invalid={passwordError ? true : undefined}
                />
                {passwordError && <p className="text-xs text-destructive">{passwordError}</p>}
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={loading}
              >
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {loading ? "登录中..." : "登录"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-muted-foreground text-xs text-center">
          CruiseAgent v2.0
        </p>
      </div>

      {/* Forced password change dialog */}
      <ChangePasswordDialog
        open={showForceChangePassword}
        onOpenChange={handlePasswordChanged}
        forced
      />
    </div>
  );
}
