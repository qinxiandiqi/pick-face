# 07 风险与决策（v3.0）

> 文档版本：v3.0 · 2026-08-12
> 范围：v3 Web 相册服务的关键风险、未决议题、ADR 索引

## 0. 当前决策日志

| ID | 决策 | 状态 | 推翻成本 |
|---|---|---|---|
| ADR-001 | HTTP 框架 = FastAPI | ✅ Accepted | 低 |
| ADR-002 | DB = SQLite WAL | ✅ Accepted | 低 |
| ADR-003 | 后台任务 = asyncio.Queue + APScheduler | ✅ Accepted | 低 |
| ADR-004 | 文件监听 = watchdog + 周期兜底 | ✅ Accepted | 低 |
| ADR-005 | 向量索引 = hnswlib（沿用 v2.x） | ✅ Accepted | 极低 |
| ADR-006 | 前端 = React + Vite + TypeScript | ✅ Accepted | 中 |
| ADR-014 | UI 组件 = shadcn/ui（Radix + Tailwind，复制源码） | ✅ Accepted | 低 |
| ADR-007 | 查看器 = 自研 React + @use-gesture + framer-motion | ✅ Accepted | 中 |
| ADR-008 | 实时通信 = SSE | ✅ Accepted | 低 |
| ADR-009 | 数据目录 = XDG_DATA_HOME 默认 | ✅ Accepted | 极低 |
| ADR-010 | 单进程异步（不 gunicorn） | ✅ Accepted | 低 |
| ADR-011 | 缩略图 = Pillow 优先 | ✅ Accepted | 低 |
| ADR-012 | 路径白名单 = 运维配置 + resolve 校验 | ✅ Accepted | 极低 |
| ADR-013 | v3 无用户体系（反代负责鉴权） | ✅ Accepted | 中（v4 加）|

## 1. 关键风险

### 1.1 R-1: 大目录 OOM

**风险**：扫描 100w+ 张照片时 `ingest/detector` 一次性加载所有图片 → 内存爆。

**缓解**：
- 流式处理（`async iterator`），**不缓存图片**
- 缩略图生成是**写文件流**，不读全图到内存
- SQLite 批量提交（每 1000 张脸一次 `COMMIT`）
- detector 输入 size 限制（如 `det_size=(320, 320)`）

**Owner**：M6 实施时验证。

### 1.2 R-2: watchdog 在 Docker bind mount 失效

**风险**：macOS / Windows / Docker 容器内 watchdog 事件不可靠。

**缓解**：
- 周期轮询兜底（默认 5 分钟）
- 文档明确：Docker bind mount 下推荐用卷（`/data` 内部）而非 bind

**Owner**：M8 实施时验证。

### 1.3 R-3: HNSW + SQLite 不一致（崩溃恢复）

**风险**：服务崩溃时，HNSW 已落盘但 SQLite 还没 COMMIT（或反过来）。

**缓解**：
- HNSW 写盘 = SQLite COMMIT **同一事务内**（应用层协调）
- 启动时**自检**：HNSW 的 `id_map` 必须 ⊆ SQLite 的 `faces.id`；不一致 → 重建 HNSW
- SQLite WAL 模式保证不撕裂

**Owner**：M6-T-7 实施时设计。

### 1.4 R-4: 路径穿越（US-1 AC-2）

**风险**：用户配置 `/mnt/photos` 后，攻击者用 `/api/photos?path=../../etc/passwd` 读敏感文件。

**缓解**：
- **永远不**用 `query_params["path"]`；用 `photo_id` 反查 `photos.path`
- `/api/config/paths` 接受路径前必须 `Path.resolve()` + 白名单校验
- 单元测试覆盖 `../etc/passwd`、`C:\Windows\System32` 等攻击向量

**Owner**：M6-T-2 实施时写测试。

### 1.5 R-5: 模型权重首次下载失败

**风险**：用户首次启动服务时需要下载 ~10 MB (yunet-sface) 或 ~261 MB (yunet-arcface)。网络中断 / 磁盘满 / 权限不足。

**缓解**：
- 启动期 `init-models` 步骤（CLI）→ 与 v2.x 相同机制
- 失败时 `/api/health` 返回 `model_status: missing`
- UI 显示"请运行 `pick-face-web init-models`"

**Owner**：M6 沿用 v2.x 机制。

### 1.6 R-6: Web 查看器性能（4K 屏 / 100+ 缩略图同时渲染）

**风险**：4K 屏瀑布流同时 100+ 缩略图，FPS 卡顿。

**缓解**：
- 缩略图 256×256 JPEG（< 30 KB/张）
- `react-photo-album` 已有虚拟化
- `loading="lazy"` + `IntersectionObserver`
- 必要时启用 `react-window` 虚拟列表

**Owner**：M7 实施时性能测试。

### 1.7 R-7: 浏览器反代 / nginx 配置错误导致 Range 失效

**风险**：HTTP Range 流式原图在 nginx 默认配置下不工作（`gzip` 干扰）。

**缓解**：
- 部署文档示例显式关 `gzip` for `/api/photos/*`
- 加 `Accept-Ranges: bytes` 验证（curl 测试）

**Owner**：M10 文档 + 测试。

### 1.8 R-8: 商业合规（AC-9）泄漏

**风险**：用户安装 `pick-face-modelpack-insightface` 后，default pack 仍是 InsightFace，导致无意中商用。

**缓解**：
- AC-9 fail-safe：`accept_noncommercial_model_license = false` 默认
- NC 包必须显式 `I AGREE`
- 与 v2.x 复用

**Owner**：M6 沿用。

## 2. 待决议题

### 2.1 O-1: 是否引入 Celery？

**问题**：单机 asyncio 任务足够，但多机部署时 Celery 是事实标准。

**当前决策**：v3 不引入。需要分布式时（v4+）再评估。

### 2.2 O-2: 是否引入 Next.js？

**问题**：Next.js 自带 SSR / API routes，可省 SPA + FastAPI 两层。

**当前决策**：不引入。**理由**：
- 服务端逻辑（detector / embedder）不适合 Next.js（Python 生态）
- 前端要单页应用，与 SSR 关系不大

### 2.3 O-3: 多用户 / Auth 何时做？

**当前决策**：v3 不做。文档明确"反代（caddy / nginx）做 HTTPS + Basic Auth"。  
**v4 引入时机**：用户量增长 / 有 SaaS 需求时。

### 2.4 O-4: WebSocket 是否需要？

**当前决策**：仅 SSE。需要双向（v4 多用户实时协作）时再加。

## 3. ADR 详情

### 3.1 ADR-014 — UI 组件 = shadcn/ui

**日期**：2026-08-12
**状态**：✅ Accepted
**推翻成本**：低（每个组件都是源码，可单独替换）

**背景**：v3 前端需要一套无障碍 + 设计 token + 可定制的 UI 组件库，且要支持自托管相册的"克制风格"。

**候选**：
| 方案 | 优点 | 缺点 |
|---|---|---|
| **shadcn/ui（Radix + Tailwind）** | 行为/样式分离、源码复制可控、设计 token 一致 | 需手动组合（无开箱即用 Theme） |
| MUI | 组件最全 | Material Design 风格强；CSS-in-JS bundle 大 |
| Chakra | API 好；可定制主题 | 体积大；定制要走 token 系统 |
| Ant Design | 后台风 | 太"管理后台"，相册调性不符 |
| 纯 Radix + 自写 Tailwind | 完全可控 | 每个组件都要从零写 class，开发慢 |

**决策**：shadcn/ui。

**理由**：
1. **行为正确性** — Radix UI 提供 WAI-ARIA 合规的 Dialog / DropdownMenu / Toast / Tabs；这些"看似简单"的组件若手写，键盘导航 / focus trap / 屏幕阅读器兼容性极易出错
2. **样式可控** — shadcn/ui 把组件源码（TSX + Tailwind class）通过 CLI 复制到 `src/web/components/ui/`，**不是 npm 依赖**。要改样式直接改源码，不会被依赖锁死
3. **设计 token 化** — 颜色 / 间距 / 字体走 CSS 变量（`--background` / `--foreground` / `--primary` ...），换肤/白标只改 CSS 变量即可
4. **暗色模式内建** — `darkMode: 'class'` + token 变量；ThemeToggle 一键切换
5. **零运行时 CSS-in-JS** — Tailwind 编译期产出 class，不增加 bundle 体积
6. **与 FastAPI 契合** — 表单用 `react-hook-form` + `zod`，`zod` schema 与 Pydantic 类型互译（手动或半自动），前后端 schema 共源

**权衡**：
- 没有"开箱即用整套主题"——shadcn/ui 只给一组默认 token，相册风格要自己调
- 组件更新要主动跑 `pnpm dlx shadcn@latest add <new-component>` 拉新版（但因为是源码 merge，diff 可控）
- 团队需要熟悉 Tailwind utility class（学习成本低）

**后续**：
- M6 第一次提交时附 `pnpm dlx shadcn@latest init` 输出 + 选定的 16 个基础组件
- 主题 token 集中在 `src/web/styles/globals.css`
- 严禁"为了快"绕开 shadcn/ui 直接写 `<div className="bg-slate-900 ...">`（除非组件库真的没有）

## 4. 引用与延伸阅读

- [02 §栈选型](02-technical-pre-research.md) — 决策依据
- [03 §服务架构](03-architecture-design.md) — ADR-008 到 ADR-013 的实现
- [11 §商业合规](11-commercial-compliance.md) — AC-9 决策