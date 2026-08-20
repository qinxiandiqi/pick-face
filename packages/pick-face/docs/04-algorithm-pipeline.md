# 04 算法流水线：检测 → 嵌入 → 聚类（v3.0）

> 文档版本：v3.0 · 2026-08-12
> 范围：人脸识别算法内核的端到端流程（与 v2.x 共享；本文重点说明 Web 服务场景的调整）
> 关联：[01 PRD](01-product-requirement.md) · [05 §数据](05-data-and-storage.md) · [11 §商业合规](11-commercial-compliance.md)

## 0. 摘要

v3 算法内核与 v2.x **100% 复用**：detector + aligner + embedder + HNSW + HDBSCAN。  
差异只在**调用时机**和**触发方式**：

| 维度 | v2.x CLI | v3 Web 服务 |
|---|---|---|
| 触发 | `pick-face run --src ...` 一次性 | watchdog 实时 + 周期轮询 |
| 模型 session | CLI 进程生命周期 | FastAPI app 生命周期（长驻） |
| 增量 | 无（每次全量） | HNSW 增量添加 + 周期重聚类 |
| 缩略图 | 不需要 | 必须 |
| 进度反馈 | CLI `--progress` | SSE 推送到浏览器 |
| GPU | `--provider cuda` | `runtime.provider = "cuda"` 在 toml |
| 线程策略 | 一次性 | 长驻；同会话多次复用 |

## 1. 端到端流水线

```
图片文件 ───▶ ingest/scanner ───▶ ingest/detector ───▶ ingest/align
                                                            │
                                                            ▼
                                                      ingest/embedder
                                                            │
                                                            ▼
                                                       store/index_hnsw
                                                       (HNSW 增量添加)
                                                            │
                                                            ▼
                                                       ingest/cluster
                                                       (HDBSCAN 周期触发)
                                                            │
                                                            ▼
                                                       store/review
                                                       (人工 review)
```

## 2. 五阶段细节

### 2.1 阶段 ① 扫描（`ingest/scanner.py`）

**输入**：路径白名单中的目录  
**输出**：可解码的图片（`Pillow` / `pillow-heif` / `rawpy`）

**v3 改动**：
- **增量友好**：记录 `(path, mtime, size)` 三元组；上次扫描存在 → 仅处理变化的文件
- **失败隔离**：坏文件 / 不支持的格式 / 解码异常 → 记录到 `jobs/scan-{uuid}.json::errors`，不中断
- **文件监听**：watchdog 监听 `IN_CLOSE_WRITE` / `IN_DELETE` / `IN_MOVED_FROM/TO`

```python
async def iter_images(root: Path) -> AsyncIterator[Path]:
    for p in root.rglob("*"):
        if p.suffix.lower() in SUPPORTED_EXTS:
            yield p
```

### 2.2 阶段 ② 检测（`ingest/detector.py`）

**输入**：图片字节流  
**输出**：`list[Detection]`（bbox + 5 landmarks + det_score）

**复用 v2.x**：YuNet (`yunet-sface` pack) 或 SCRFD (`yunet-arcface`)  
**v3 改动**：
- **session 长驻**：detector 在 `app.on_event("startup")` 构造一次，整个进程复用
- **warmup**：启动时跑一张空图，避免首张检测卡顿
- **过滤**：det_score < 0.3 直接丢弃（避免误检）

### 2.3 阶段 ③ 对齐（`ingest/align.py`）

**输入**：原图 + 5 landmarks  
**输出**：112×112 RGB uint8（标准 ArcFace 输入）

**v3 改动**：
- 同时生成**缩略图**（Pillow `thumbnail((256, 256))`）
- 缓存键：`xxh3_64(content)`；同一文件不重做

### 2.4 阶段 ④ 嵌入（`ingest/embedder.py`）

**输入**：112×112 chip  
**输出**：128-D (SFace) 或 512-D (ArcFace) L2-normalized float32

**复用 v2.x**：Model Pack 架构 + 多变体支持  
**v3 改动**：
- **preprocess 函数纯化**：`ArcFaceR100Embedder.preprocess(chip)` 已经是 static method，web 测试友好
- **session 长驻**：ONNX Runtime session 在 startup 时构造

### 2.5 阶段 ⑤ 索引（`store/index_hnsw.py`）

**输入**：embedding vector  
**输出**：HNSW 索引更新 + SQLite 写入

**v3 改动**：
- **增量友好**：HNSW 支持 `add_items()` 单条添加
- **持久化频率**：每 1000 张脸落盘一次（atomic 写）
- **崩溃恢复**：重启时 SQLite + HNSW 必须自洽（HNSW 用 `id_map` 对齐 SQLite 主键）

## 3. 聚类（`ingest/cluster.py`）

**复用 v2.x**：HDBSCAN on cosine distance  
**v3 改动**：

| 维度 | v2.x | v3 |
|---|---|---|
| 触发 | CLI 一次性 | **周期 + 阈值双触发** |
| 频率 | 一次跑完 | 新增 N 张脸 OR M 秒 |
| 合并人 | review CLI 命令 | `POST /api/persons/merge` |

**触发条件**：
```
APScheduler: 每天 02:00 重聚类（低峰期）
增量触发:   新增 ≥ cluster.auto_recluster_min_new 张脸（默认 500）
```

**为什么不每次都重聚类？** HDBSCAN 是 O(n log n)，100k 脸一次 ~30 秒；增量触发让白天体验流畅。

## 4. 维度选择与 merge_threshold

与 v2.x 一致：
- **yunet-sface** (SFace 128-D)：merge_threshold = 0.0（不合并）
- **yunet-arcface** (ArcFace 512-D)：merge_threshold = 0.55（512-D cosine 提示）

`pick-face.toml` 的 `[clustering] merge_threshold` 控制 review 阶段的合并阈值。

## 5. 性能预算（100k 张照片基线）

| 阶段 | 单张耗时 | 100k 总耗时 |
|---|---|---|
| 扫描 | < 1ms | 100s |
| 检测 | 30 ms (CPU) / 5 ms (GPU) | 50 min / 8 min |
| 对齐 + 缩略图 | 5 ms | 8 min |
| 嵌入 | 10 ms (CPU) / 2 ms (GPU) | 17 min / 3 min |
| HNSW 添加 | 0.1 ms | 10 s |
| HDBSCAN 重聚类 | — | 30 s（一次性）|
| **总计** | — | **~75 min (CPU) / ~12 min (GPU)** |

**Web 服务场景的优化**：
- 启动期 100k 张图：单次 scan worker 并发 4 路；UI 进度条 100% 后用户可浏览
- 增量期：单张图检测+嵌入 < 50ms，不阻塞 HTTP
- HNSW query (K=20)：< 5ms p99，瀑布流加载响应即时

## 6. 验收（沿用 v2.x AC-1）

| AC | 含义 | v3 目标 |
|---|---|---|
| AC-1 pairwise precision | 同人聚类精度 | ≥ 0.95 |
| AC-1 pairwise recall | 同人聚类召回 | ≥ 0.85 |
| AC-1 B³ F1 | 综合 | ≥ 0.90 |

**v3 验收在 AT&T fixture 上跑**（与 v2.x 共用），数据存 `tests/fixtures/real_faces/`。  
**v3 新增跨目录聚类验收**：把 fixture 拆到 2 个子目录，验证跨目录同人合并（见 06 §M6-T-3）。

## 7. 与 v2.x 的兼容性矩阵

| 能力 | v2.x | v3 |
|---|---|---|
| 检测器 session | 临时 | 长驻 ✅ |
| 嵌入器 session | 临时 | 长驻 ✅ |
| HNSW 持久化 | ✅ | ✅ |
| HDBSCAN 周期触发 | ❌ | ✅ |
| 增量扫描 | ❌ | ✅ |
| 缩略图 | ❌ | ✅ |
| 进度反馈 | CLI flag | SSE |
| 并发 | CLI 单进程 | FastAPI N worker |
| Watchdog | ❌ | ✅ |
| 路径白名单 | ❌ | ✅ |
| 原图流式 | N/A | ✅ (HTTP Range) |

## 8. 引用与延伸阅读

- [01 PRD US-2 / US-3 / US-4 / US-5](01-product-requirement.md)
- [02 §栈选型](02-technical-pre-research.md)
- [05 §数据与存储](05-data-and-storage.md)
- [11 §商业合规](11-commercial-compliance.md) — AC-9 仍生效
- 归档：[M5 CLI §流水线](archive/m5-cli/04-algorithm-pipeline.md) — 算法内核的历史细节