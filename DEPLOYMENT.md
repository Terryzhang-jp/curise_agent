# 部署指南 — Curise Agent (v2)

## 目录

- [项目结构](#项目结构)
- [环境要求](#环境要求)
- [安全注意事项](#安全注意事项)
- [本地开发](#本地开发)
- [部署教程](#部署教程)
  - [后端部署 (Google Cloud Run)](#后端部署-google-cloud-run)
  - [前端部署 (Vercel)](#前端部署-vercel)
- [部署后验证](#部署后验证)
- [常见问题](#常见问题)
- [Redeploy 教程（日常更新部署）](#redeploy-教程日常更新部署)
- [Redeploy 注意事项](#redeploy-注意事项)

---

## 项目结构

```
curise_agent/
├── v2-backend/          # FastAPI 后端
│   ├── Dockerfile       # Cloud Run 容器构建
│   ├── main.py          # 入口文件
│   ├── config.py        # 配置（从环境变量读取）
│   ├── env_vars.yaml    # ⚠️ Cloud Run 部署用（不入 git）
│   ├── .env             # ⚠️ 本地开发用（不入 git）
│   ├── requirements.txt
│   └── ...
├── v2-frontend/         # Next.js 前端
│   ├── .env.local       # ⚠️ 本地开发用（不入 git）
│   ├── next.config.ts
│   ├── package.json
│   └── ...
└── DEPLOYMENT.md        # 本文件
```

---

## 环境要求

### 工具

| 工具 | 版本 | 安装 |
|------|------|------|
| Node.js | >= 18 | `brew install node` |
| pnpm | >= 8 | `npm install -g pnpm` |
| Python | >= 3.11 | `brew install python@3.11` |
| gcloud CLI | latest | https://cloud.google.com/sdk/docs/install |
| Vercel CLI | latest | `npm install -g vercel` |
| Git | latest | `brew install git` |

### 账号

- **Google Cloud**: 项目 `gxutokyo`，需要 Cloud Run 和 Cloud Build 权限
- **Vercel**: 项目 `v2-frontend`
- **GitHub**: `Terryzhang-jp/curise_agent`

---

## 安全注意事项

### 绝对不能推送到 Git 的文件

以下文件包含真实密钥，已通过 `.gitignore` 排除：

| 文件 | 内容 | 说明 |
|------|------|------|
| `v2-backend/.env` | DATABASE_URL, SECRET_KEY, GOOGLE_API_KEY | 本地开发环境变量 |
| `v2-backend/.env.supabase.bak` | Supabase 连接串备份 | 备份文件 |
| `v2-backend/env_vars.yaml` | 所有生产环境变量 | Cloud Run 部署专用 |
| `v2-frontend/.env.local` | NEXT_PUBLIC_API_URL | 前端 API 地址 |

### 推送前检查清单

每次 `git push` 之前，务必执行：

```bash
# 1. 确认 .gitignore 生效
git check-ignore -v v2-backend/.env v2-backend/env_vars.yaml v2-frontend/.env.local

# 预期输出：每个文件都显示被哪条规则排除
# v2-backend/.gitignore:9:.env     v2-backend/.env
# v2-backend/.gitignore:11:env_vars.yaml    v2-backend/env_vars.yaml
# v2-frontend/.gitignore:8:.env.*  v2-frontend/.env.local

# 2. 确认暂存区没有密钥文件
git diff --cached --name-only | grep -E "\.env|env_vars"

# 预期输出：空（无输出）

# 3. 搜索代码中是否硬编码了密钥
grep -rn "AIzaSy\|Qaz246567\|pdT0M5o4" --include="*.py" --include="*.ts" --include="*.tsx" .

# 预期输出：空（无输出）
```

### 如果不小心提交了密钥

1. **立即轮换密钥**（改 Supabase 密码、重新生成 Google API Key）
2. 从 git 历史中移除：
   ```bash
   git filter-branch --force --index-filter \
     'git rm --cached --ignore-unmatch v2-backend/.env v2-backend/env_vars.yaml' \
     HEAD
   git push --force
   ```
3. 在 GitHub Settings → Secrets 中检查是否有泄露告警

---

## 本地开发

### 后端

```bash
cd v2-backend

# 1. 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 创建 .env 文件（如果不存在）
cat > .env << 'EOF'
ENV=development
DATABASE_URL=postgresql://your_user@localhost/cruise_system_v2_dev
SECRET_KEY=your-dev-secret-key
GOOGLE_API_KEY=your-google-api-key
EOF

# 4. 启动开发服务器
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### 前端

```bash
cd v2-frontend

# 1. 安装依赖
pnpm install

# 2. 创建 .env.local 文件（如果不存在）
echo "NEXT_PUBLIC_API_URL=http://localhost:8001" > .env.local

# 3. 启动开发服务器
pnpm dev
```

访问 http://localhost:3001 即可看到前端页面。

---

## 部署教程

### 后端部署 (Google Cloud Run)

#### 前提

1. 已安装 `gcloud` CLI 并登录：
   ```bash
   gcloud auth login
   gcloud config set project gxutokyo
   ```

2. 已准备好 `env_vars.yaml`（从团队获取，不要自己创建）：
   ```yaml
   ENV: production
   DATABASE_URL: postgresql://...（Supabase 连接串）
   SECRET_KEY: ...
   GOOGLE_API_KEY: ...
   ALLOWED_ORIGINS: https://v2-frontend-delta.vercel.app,...
   # 其他环境变量...
   ```

#### 部署步骤

```bash
cd v2-backend

# 一条命令部署
gcloud run deploy v2-cruise-backend \
  --source . \
  --region asia-northeast1 \
  --env-vars-file env_vars.yaml \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --max-instances 3
```

#### 参数说明

| 参数 | 值 | 说明 |
|------|------|------|
| `--source .` | 当前目录 | 使用 Dockerfile 构建镜像 |
| `--region` | `asia-northeast1` | 东京区域，离日本用户最近 |
| `--env-vars-file` | `env_vars.yaml` | 注入所有环境变量 |
| `--allow-unauthenticated` | - | 公开访问（API 自带 JWT 认证） |
| `--memory` | `1Gi` | 内存限制，AI 推理需要较大内存 |
| `--timeout` | `300` | 请求超时 5 分钟（询价单生成耗时较长） |
| `--max-instances` | `3` | 最大实例数，控制成本 |

#### 部署输出

成功后会看到：
```
Service [v2-cruise-backend] revision [v2-cruise-backend-00005-xxx] has been deployed
and is serving 100 percent of traffic.
Service URL: https://v2-cruise-backend-1083982545507.asia-northeast1.run.app
```

---

### 前端部署 (Vercel)

#### 前提

1. 已安装 Vercel CLI 并登录：
   ```bash
   npm install -g vercel
   vercel login
   ```

2. 项目已关联（首次需要 `vercel link`）

3. 在 Vercel Dashboard 中已设置环境变量：
   - `NEXT_PUBLIC_API_URL` = `https://v2-cruise-backend-1083982545507.asia-northeast1.run.app`

#### 部署步骤

```bash
cd v2-frontend

# 一条命令部署到生产环境
vercel --prod
```

#### 首次部署（项目未关联时）

```bash
cd v2-frontend

# 1. 关联项目
vercel link
# 选择已有项目 v2-frontend 或创建新项目

# 2. 设置环境变量（也可在 Dashboard 中设置）
vercel env add NEXT_PUBLIC_API_URL production
# 输入: https://v2-cruise-backend-1083982545507.asia-northeast1.run.app

# 3. 部署
vercel --prod
```

#### 部署输出

成功后会看到：
```
Production: https://v2-frontend-delta.vercel.app
```

---

## 部署后验证

### 自动检查脚本

部署完成后执行以下检查：

```bash
# 后端健康检查
curl -s https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/health
# 预期: {"status":"ok","version":"2.0.0"}

# 前端可达性
curl -s -o /dev/null -w "%{http_code}" https://v2-frontend-delta.vercel.app/login
# 预期: 200

# 后端 CORS 检查
curl -s -I -X OPTIONS \
  -H "Origin: https://v2-frontend-delta.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/api/auth/login \
  | grep -i "access-control"
# 预期: access-control-allow-origin: https://v2-frontend-delta.vercel.app
```

### 手动验证

1. 打开 https://v2-frontend-delta.vercel.app/login
2. 使用管理员账号登录
3. 检查各页面功能：订单列表、设置中心、AI 助手

---

## 常见问题

### Q: 部署后前端报 CORS 错误

**原因**: 后端 `ALLOWED_ORIGINS` 环境变量中没有包含前端域名。

**解决**: 更新 `env_vars.yaml` 中的 `ALLOWED_ORIGINS`，添加新域名后重新部署后端：
```yaml
ALLOWED_ORIGINS: https://v2-frontend-delta.vercel.app,https://your-new-domain.vercel.app
```

### Q: Cloud Run 部署超时

**原因**: Docker 构建需要安装依赖，首次可能较慢。

**解决**: 耐心等待（通常 3-5 分钟），或检查 `requirements.txt` 是否有不必要的大包。

### Q: Vercel 构建失败

**原因**: 通常是 TypeScript 类型错误。

**解决**:
```bash
cd v2-frontend
npx tsc --noEmit  # 本地检查类型错误
pnpm build        # 本地测试构建
```

### Q: 需要更新单个环境变量

**Cloud Run**:
```bash
# 更新单个变量（无需 env_vars.yaml）
gcloud run services update v2-cruise-backend \
  --region asia-northeast1 \
  --update-env-vars "GOOGLE_API_KEY=new-key-here"
```

**Vercel**:
```bash
# 在 Dashboard 中修改，或：
vercel env rm NEXT_PUBLIC_API_URL production
vercel env add NEXT_PUBLIC_API_URL production
vercel --prod  # 需要重新部署才生效
```

### Q: 需要回滚到上一个版本

**Cloud Run**:
```bash
# 查看所有 revision
gcloud run revisions list --service v2-cruise-backend --region asia-northeast1

# 回滚到指定 revision
gcloud run services update-traffic v2-cruise-backend \
  --region asia-northeast1 \
  --to-revisions v2-cruise-backend-00004-xxx=100
```

**Vercel**:
在 Vercel Dashboard → Deployments 中找到上一个成功部署，点击 "Promote to Production"。

---

## 快速参考

### 日常部署（代码更新后）

```bash
# 1. 确认无密钥泄露
git diff --cached --name-only | grep -E "\.env|env_vars"

# 2. 推送代码
git add .
git commit -m "feat: your changes"
git push

# 3. 部署后端
cd v2-backend
gcloud run deploy v2-cruise-backend \
  --source . --region asia-northeast1 \
  --env-vars-file env_vars.yaml \
  --allow-unauthenticated --memory 1Gi --timeout 300 --max-instances 3

# 4. 部署前端
cd v2-frontend
vercel --prod

# 5. 验证
curl -s https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/health
```

### 线上地址

| 服务 | URL |
|------|-----|
| 后端 API | https://v2-cruise-backend-1083982545507.asia-northeast1.run.app |
| 前端 | https://v2-frontend-delta.vercel.app |
| GitHub | https://github.com/Terryzhang-jp/curise_agent |

---

## Redeploy 教程（日常更新部署）

> 日常开发中最常见的场景：改了代码，需要重新部署到线上。

### 完整流程

```
本地改代码 → 本地验证 → 安全检查 → git push → 部署后端/前端 → 线上验证
```

---

### Step 1: 本地验证

改完代码后，先在本地确认没有问题：

```bash
# 后端：确认能正常启动
cd v2-backend
source venv/bin/activate
uvicorn main:app --reload --port 8001
# 浏览器访问 http://localhost:8001/health 确认返回 {"status":"ok"}

# 前端：确认 TypeScript 编译通过
cd v2-frontend
npx tsc --noEmit        # 类型检查，0 error 才能继续
pnpm build              # 完整构建测试（可选但推荐）
```

### Step 2: 安全检查（推送前必做）

```bash
cd curise_agent   # 进入 git 仓库根目录

# 检查 1：确认密钥文件被 .gitignore 排除
git check-ignore -v v2-backend/.env v2-backend/env_vars.yaml v2-frontend/.env.local
# ✅ 每行都应该显示被哪条 .gitignore 规则排除

# 检查 2：暂存区中没有密钥文件
git add . && git diff --cached --name-only | grep -E "\.env|env_vars|\.bak"
# ✅ 应该无输出

# 检查 3：代码中没有硬编码的真实密钥
grep -rn "AIzaSy\|Qaz246567\|pdT0M5o4" --include="*.py" --include="*.ts" --include="*.tsx" .
# ✅ 应该无输出
```

### Step 3: 提交并推送

```bash
git add .
git commit -m "fix: 简要描述改了什么"
git push
```

### Step 4: 部署

根据改动范围，选择需要部署的服务：

| 改了什么 | 需要部署 |
|----------|----------|
| 只改了 `v2-frontend/` | 只部署前端 |
| 只改了 `v2-backend/` | 只部署后端 |
| 前后端都改了 | **先部署后端，再部署前端** |
| 只改了 `env_vars.yaml` | 只部署后端 |

#### 部署后端

```bash
cd v2-backend

gcloud run deploy v2-cruise-backend \
  --source . \
  --region asia-northeast1 \
  --env-vars-file env_vars.yaml \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --max-instances 3
```

耗时约 3-8 分钟（Docker 构建 + 部署）。看到以下输出表示成功：
```
Service [v2-cruise-backend] revision [v2-cruise-backend-00006-xxx]
has been deployed and is serving 100 percent of traffic.
```

#### 部署前端

```bash
cd v2-frontend

vercel --prod
```

耗时约 30-90 秒。看到 `Production: https://v2-frontend-...` 表示成功。

### Step 5: 线上验证

```bash
# 后端健康检查
curl -s https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/health
# ✅ {"status":"ok","version":"2.0.0"}

# 前端可达性
curl -s -o /dev/null -w "%{http_code}" https://v2-frontend-delta.vercel.app/login
# ✅ 200

# CORS 检查（所有 HTTP 方法）
for METHOD in GET POST PUT PATCH DELETE; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
    -H "Origin: https://v2-frontend-delta.vercel.app" \
    -H "Access-Control-Request-Method: $METHOD" \
    -H "Access-Control-Request-Headers: content-type,authorization" \
    https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/api/auth/login)
  echo "$METHOD → $STATUS"
done
# ✅ 全部应返回 200
```

最后打开浏览器访问 https://v2-frontend-delta.vercel.app ，手动操作验证改动生效。

---

## Redeploy 注意事项

### 1. 部署顺序：先后端，再前端

如果前后端都有改动（尤其是 API 接口变更），**必须先部署后端**。
- 原因：前端新代码可能调用新的 API 路径/参数，如果后端还没更新，会报 404 或 500
- 反过来通常没问题：后端新增接口不会影响还在用旧代码的前端

### 2. env_vars.yaml 不在 git 仓库中

`env_vars.yaml` 只存在于本地 `v2-backend/` 目录中（被 `.gitignore` 排除）。
- `git clone` 下来的代码不包含此文件
- 新环境部署时需要从团队获取或从密码管理器中恢复
- 修改环境变量后需要重新部署后端才能生效

### 3. Cloud Run 部署是从本地 source 构建

`gcloud run deploy --source .` 会把当前目录打包上传到 Cloud Build。
- 它用的是**本地文件**，不是 GitHub 上的代码
- 所以 `git push` 和 `gcloud run deploy` 是两个独立步骤
- 确保本地代码和 git 仓库一致，避免"推了但没部署"或"部署了但没推"

### 4. Vercel 同理：部署的是本地代码

`vercel --prod` 上传的是本地 `v2-frontend/` 目录。
- 如果本地有未提交的改动，Vercel 上会有但 GitHub 上没有
- 建议：**先 commit + push，再 deploy**，保持一致

### 5. 前端环境变量需要重新部署才生效

Vercel 的 `NEXT_PUBLIC_*` 环境变量是**构建时注入**的（不是运行时读取）。
- 在 Vercel Dashboard 改了环境变量后，必须重新 `vercel --prod` 才能生效
- 仅修改 Dashboard 而不重新部署 = 没有效果

### 6. 后端冷启动

Cloud Run 在无流量时会缩容到 0 实例（节省成本）。
- 第一次请求可能需要 5-15 秒冷启动
- 这是正常现象，不是 bug
- 如需减少冷启动延迟，可设置 `--min-instances 1`（但会持续产生费用）

### 7. 数据库迁移

后端使用 `Base.metadata.create_all()` 自动创建新表，但**不会修改已有表结构**。
- 新增表：自动处理，无需操作
- 修改已有表（加列、改类型）：需要手动执行 SQL
  ```bash
  # 连接 Supabase 执行迁移
  psql "postgresql://postgres.xxx:password@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"

  # 执行迁移文件
  \i migrations/manual/014_delivery_environment.sql
  ```
- 迁移文件在 `v2-backend/migrations/manual/` 目录中，按编号顺序执行

### 8. 踩过的坑

| 问题 | 原因 | 修复 |
|------|------|------|
| CORS 报错 PUT 请求 | `allow_methods` 列表遗漏了 `PUT` | 在 `main.py` 的 CORSMiddleware 中添加 `PUT` |
| CORS 报错新域名 | `ALLOWED_ORIGINS` 没有包含 Vercel 预览域名 | 在 `env_vars.yaml` 中添加域名并重新部署 |
| 登录 500 错误 | bcrypt 5.0 与 passlib 不兼容 | 锁定 `bcrypt==4.2.1` |
| 前端 API 调用 404 | `NEXT_PUBLIC_API_URL` 未设置或错误 | 在 Vercel Dashboard 设置正确的后端地址 |
| 部署后数据库报错 | 新代码依赖新增的表列 | 先执行数据库迁移 SQL，再部署后端 |

### 9. 快速诊断清单

部署后遇到问题时，按顺序检查：

```bash
# 1. 后端是否活着？
curl -s https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/health

# 2. CORS 是否通过？（替换 METHOD 为出问题的 HTTP 方法）
curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
  -H "Origin: https://v2-frontend-delta.vercel.app" \
  -H "Access-Control-Request-Method: PUT" \
  -H "Access-Control-Request-Headers: content-type,authorization" \
  https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/api/any-path

# 3. API 认证是否正常？
curl -s -X POST https://v2-cruise-backend-1083982545507.asia-northeast1.run.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"Admin123"}'

# 4. 查看 Cloud Run 日志
gcloud run services logs read v2-cruise-backend --region asia-northeast1 --limit 50
```
