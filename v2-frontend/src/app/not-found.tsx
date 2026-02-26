import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center max-w-md px-6">
        <div className="text-7xl font-bold text-muted-foreground/30 mb-4">404</div>
        <h1 className="text-lg font-semibold mb-2">页面未找到</h1>
        <p className="text-sm text-muted-foreground mb-6">
          您访问的页面不存在或已被移除。
        </p>
        <Link
          href="/dashboard"
          className="inline-flex items-center justify-center rounded-md text-sm font-medium bg-primary text-primary-foreground h-9 px-4 hover:bg-primary/90 transition-colors"
        >
          返回首页
        </Link>
      </div>
    </div>
  );
}
