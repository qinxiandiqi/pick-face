# 11 商业部署合规指南

> 文档版本：v0.1（评审稿） · 2026-07-30
> 范围：把"默认 `buffalo_l` 非商用"这一风险在产品、代码、文档、发布四个层面**完整闭环**。
> **本文是单一权威解读**。任何与本文件冲突的章节（README / 01 / 02 / 10 / 03 §11 / 04 / 06 / 08 / 09），以本文件为准。
> 关联：[08 §6 最终方案](08-review-notes.md) · [10 §4 / §7 模型许可与下载](10-model-stack.md) · [01 R-COM-1](01-product-requirement.md) · [03 §11 包管理](03-architecture-design.md) · [06 §7.2 extras](06-engineering-plan.md) · [07 ADR-005/007](07-risk-and-decisions.md)

## 0. 摘要（60 秒版）

| 问题 | 答案 |
|------|------|
| pick-face 本体能商用吗？ | **✅ 是**，Apache-2.0。 |
| 默认跑的 `buffalo_l` 权重能商用吗？ | **❌ 否**，InsightFace 仓库 license 是「非商业研究用途」。 |
| 谁的责任？ | **用户**。pick-face 项目方不为第三方权重背书。 |
| 商业用户怎么办？ | **3 选 1**：(a) 自训（MIT 训练脚本 + WebFace4M/Glint360K），(b) 购买 InsightFace / 第三方商业 SDK 许可，(c) 换 AdaFace/MagFace（自训路径，license 干净）。 |
| 在 pick-face 里怎么"切"？ | 改 `pick-face.toml` 的 `[runtime] model_dir` 指向自有权重 + `accept_noncommercial_model_license = false`。 |
| 项目方做了什么护栏？ | (1) **不**捆绑任何 `*.onnx`；(2) `init-models` 强制交互确认；(3) 启动强校验；(4) `report.md` 标模型来源；(5) CI 守卫防模型泄露；(6) README/LICENSE 顶部明记用户自负。 |

---

## 1. 许可证边界

### 1.1 三层独立物

```
┌──────────────────────────────────────────────────────┐
│  你的公司 / 你的产品                                  │
│  (商业行为发生地)                                      │
└──────────────────┬───────────────────────────────────┘
                   │ 使用
                   ▼
┌──────────────────────────────────────────────────────┐
│  pick-face (Apache-2.0)                              │  ← 项目方责任到此
│  · 扫描、聚类、链接、报告的代码                         │
│  · 不含任何 *.onnx                                    │
│  · 不内置任何模型下载器（由 init-models 显式触发）        │
└──────────────────┬───────────────────────────────────┘
                   │ 通过 FaceDetector / FaceEmbedder Protocol 调用
                   ▼
┌──────────────────────────────────────────────────────┐
│  InsightFace python-package (MIT)                    │  ← 仅仅是接口适配
└──────────────────┬───────────────────────────────────┘
                   │ 加载
                   ▼
┌──────────────────────────────────────────────────────┐
│  buffalo_l 权重 (InsightFace 自定义：非商业研究)        │  ← 真正触发 license 的物
│  位置: ~/.insightface/models/buffalo_l/                │
└──────────────────────────────────────────────────────┘
```

**关键点**：**触发 InsightFace 权重 license 的是「使用」本身**，不是 pick-face 包、不是安装行为、不是下载行为。

### 1.2 各组件 license 速查

| 物 | 许可证 | 商业可用 | 备注 |
|---|--------|---------|------|
| pick-face 代码 | **Apache-2.0** | ✅ | 本仓库 |
| pick-face 文档 | **CC-BY-4.0** | ✅ | 注明出处的复用 |
| insightface (python package) | MIT | ✅ | 仅代码 |
| onnxruntime | MIT | ✅ | — |
| hnswlib | Apache-2.0 | ✅ | — |
| hdbscan | BSD | ✅ | — |
| Pillow / OpenCV / NumPy / xxhash | HPND / Apache-2.0 / BSD | ✅ | — |
| **buffalo_l / buffalo_sc 权重** | **InsightFace 自定义** | **❌** | 见 [InsightFace LICENSE](https://github.com/deepinsight/insightface/blob/master/LICENSE) |
| face.evoLVe.PyTorch（训练脚本） | MIT | ✅ | 训练出来的权重归你 |
| WebFace4M / Glint360K（数据） | 各自条款 | ⚠ 视具体 license | 训练前逐项查 |
| AdaFace / MagFace 训练代码 | MIT / Apache-2.0 | ✅ | 训出来的权重归你 |

---

## 2. 用户必读

### 2.1 个人 / 研究 / 非营利用户

✅ **直接用**。`buffalo_l` 完全够用。

```bash
pick-face init        # 生成 toml
# 编辑 pick-face.toml: accept_noncommercial_model_license = true
pick-face init-models --allow-network
pick-face run --src ~/Photos --out ~/Photos/by_face
```

**前提**：`accept_noncommercial_model_license = true` 是你对 InsightFace 条款的**明示同意**，pick-face 仅作为凭证记录。

### 2.2 商业用户（公司内部 / SaaS / 出海 / 任何"产生或支持商业收入"的场景）

❌ **不要**用 `buffalo_l`。

走以下 3 条之一：

#### 选项 A：自训（推荐，控制力最强）

```bash
# 1) 拉训练脚本（MIT）
git clone https://github.com/ZhaoJ9014/face.evoLVe.PyTorch
cd face.evoLVe.PyTorch

# 2) 准备训练数据（**避开** MS1M 原始，已下架）
#    推荐 WebFace4M（4M 图，许可相对清晰）
#    或 Glint360K（360k 人）
# 详见 [10 §2.1 / §5](10-model-stack.md)

# 3) 训练 r50@WebFace4M
python -m torch.distributed.launch --nproc_per_node=4 \
    train.py --network r50 --dataset webface4m --loss arcface

# 4) PyTorch → ONNX
python export_onnx.py --ckpt r50_webface4m.pth --out /srv/models/commercial/arcface.onnx

# 5) 配 pick-face.toml
cat >> pick-face.toml <<'EOF'
[runtime]
model_dir = "/srv/models/commercial"
accept_noncommercial_model_license = false
EOF

# 6) 跑（不再触发任何 InsightFace 下载）
pick-face run --src /data/photos --out /data/by_face
```

**关键合规点**：
- **数据**才是大头：训练数据本身的 license / 肖像权 / 爬取合规要逐项审。
- **checkpoint** 是你的，归你所有，license 你定。
- **ONNX** 是你的。

#### 选项 B：买 InsightFace Pro / 商业 SDK 许可

- InsightFace 商业 license（直接联系原厂）。
- 第三方 SDK：AWS Rekognition、Face++、旷视、商汤、百度 AI 开放平台。
- 在 pick-face 里实现 `pick_face.ingest.detector.FaceDetector` Protocol 即可，**业务代码 0 改**（[03 §6](03-architecture-design.md)）。

#### 选项 C：换模型族（AdaFace / MagFace）

- 训练脚本 MIT，训出来的权重**你**拥有，**与 InsightFace 完全脱钩**。
- 性能对标 `buffalo_l`（LFW 99.78%+；CALFW/CPLFW 略强）。
- 详见 [10 §2.3 / §2.4](10-model-stack.md)。

### 2.3 "是不是商业"的判定（不要揣测）

| 场景 | 是否商业 | 备注 |
|------|---------|------|
| 我自己整理我自己的照片 | ❌ 非商业 | — |
| 我帮邻居免费整理他们的照片 | ⚠ 灰色 | 涉及"代他人处理个人数据"，但**不产生收入**；仍建议走自训以避风险 |
| 公司内部工具箱免费给员工用 | ⚠ 灰色 | 公司上下文通常视为"商业使用" |
| 集成进收费 SaaS / 商业产品 | ✅ 商业 | 禁止 `buffalo_l` |
| 集成进公司产品供客户使用 | ✅ 商业 | 禁止 `buffalo_l` |
| 给付费客户提供人脸库整理服务 | ✅ 商业 | 禁止 `buffalo_l` |
| 学术论文 demo | ❌ 非商业研究 | 引用 InsightFace 即可 |

**判不准就当商业**，走自训——成本可控（[10 §6 模型总成本与体积](10-model-stack.md)）。

---

## 3. 项目方的护栏（不依赖用户善意）

### 3.1 代码层：完全解耦

| 动作 | 文件 | 内容 |
|------|------|------|
| `.gitignore` 兜底 | 仓根 | `*.onnx`、`models/`、`bench/dataset_demo/.insightface/` 等全列黑名单 |
| `pyproject.toml` 不绑模型 | 项目 | `[project]` 与所有 extras 中**不出现** `insightface-models-*` 或任何 `*.onnx` 直接依赖 |
| `Dockerfile` 不装模型 | 镜像 | build 完 `uv pip install -e ".[dev]"` 就停，**不**调 `init-models` |
| CI 不下模型 | `.github/workflows/*.yml` | `actions/cache` **不**缓存 `~/.insightface`；test.yml 不跑 `init-models` |
| PyPI wheel/sdist 不带模型 | release.yml | `uv build` 产物 `MANIFEST.in` 不 include 任何 `*.onnx` |

### 3.2 启动时强校验

`pick-face.toml`：

```toml
[runtime]
# 显式声明当前使用的模型来源与是否接受非商业研究 license
# false  → 启动时校验 model_dir 里的权重**不是** buffalo_l/scrfd_10g/w600k_r50 等 InsightFace 家族
# true   → 用户明示接受 InsightFace 权重条款（仅个人/研究/非营利）
# 必填；缺字段视为 false（fail-safe 默认）
accept_noncommercial_model_license = false

# 模型根目录；默认 ~/.insightface/models/
model_dir = "~/.insightface/models"

# 选定要用的模型包（与 model_dir 下的子目录同名）
# 默认: "buffalo_l"
model_name = "buffalo_l"
```

`pick-face run` 启动逻辑（伪码）：

```python
def preflight_check():
    cfg = load_config()
    if cfg.runtime.model_name in {"buffalo_l", "buffalo_sc"} \
       and not cfg.runtime.accept_noncommercial_model_license:
        raise UserFacingError(
            f"Model '{cfg.runtime.model_name}' is licensed under InsightFace's "
            f"non-commercial-research terms.\n"
            f"See docs/11-commercial-compliance.md for the three legal paths "
            f"to use pick-face commercially:\n"
            f"  (a) Self-train an MIT-licensed model (recommended)\n"
            f"  (b) Obtain a commercial license from InsightFace\n"
            f"  (c) Switch to another MIT/Apache-2.0 model family\n",
            exit_code=2,        # 与 03 §9 退出码契约一致
        )
    if cfg.runtime.model_name.startswith("buffalo_") \
       and cfg.runtime.accept_noncommercial_model_license:
        log.warn(
            "You are using '%s' under InsightFace's non-commercial-research "
            "license. By proceeding you confirm that your use case qualifies "
            "(personal / academic / non-profit).",
            cfg.runtime.model_name,
        )
```

`init-models` 子命令：

```python
def cmd_init_models(*, allow_network: bool, yes: bool = False):
    if not allow_network:
        sys.exit("Refusing to download models without --allow-network.")
    if not yes:
        print(LICENSE_PROMPT)        # 见 §3.3
        if input("Type 'I AGREE' to continue: ") != "I AGREE":
            sys.exit("Aborted.")
    download_to(cfg.runtime.model_dir / "buffalo_l")
    # 落盘证据
    (cfg.runtime.model_dir / "buffalo_l" / ".license_ack").write_text(
        json.dumps({
            "model": "buffalo_l",
            "license": "InsightFace non-commercial-research",
            "ack_text": LICENSE_PROMPT,
            "acked_at": utcnow().isoformat(),
            "acked_by": getpass.getuser(),
        }, indent=2)
    )
```

### 3.3 `init-models` 启动时打印的 License 提示全文

```
═══════════════════════════════════════════════════════════════════════
  InsightFace buffalo_l — License Notice
═══════════════════════════════════════════════════════════════════════

You are about to download the InsightFace "buffalo_l" model pack
(detector + embedder, ~350 MB).

  Source  : https://github.com/deepinsight/insightface
  License : InsightFace — "Non-Commercial Research Use Only"
             (full text: see the LICENSE file in that repository)

  ⚠ If you are using this in any commercial context — including but
    not limited to:
      · a company-internal tool,
      · a paid SaaS / cloud product,
      · a product shipped to paying customers,
      · use by an employee in the course of their work for a for-profit
        company, or
      · any use that supports, directly or indirectly, revenue generation —
    you are NOT permitted to use buffalo_l under its license.

    You must EITHER:
      (a) Self-train a model you are licensed to use commercially
          (see docs/11-commercial-compliance.md §2.2 option A),
      (b) Obtain a separate commercial license from InsightFace,
      (c) Use a different MIT/Apache-2.0 model family
          (AdaFace, MagFace, MobileFaceNet, …; see docs/10 §2.3/§2.4).

  The pick-face project authors and contributors make NO
  representation about your right to use these model weights and
  accept NO liability arising from such use.

═══════════════════════════════════════════════════════════════════════
Type 'I AGREE' to confirm your use qualifies as non-commercial
research (per the InsightFace license terms), or 'NO' to abort:
═══════════════════════════════════════════════════════════════════════
```

### 3.4 报告顶部明记（审计友好）

`report.md` 顶部新增一节：

```markdown
# pick-face Report

- **Run ID**: 2026-07-30T14:23:11Z
- **Model**: `buffalo_l` (SCRFD-10G detector + ArcFace w600k_r50 embedder)
- **Model License**: InsightFace non-commercial-research
- **Accepted by**: user "alice" on 2026-07-30 (see `.cache/buffalo_l/.license_ack`)
- **Provider**: CPUExecutionProvider
- **Total sources**: 1234
- ...

---

## ⚠ Warnings
- Model `buffalo_l` is under a non-commercial-research license.
  Confirm your use case qualifies, or replace the model per
  docs/11-commercial-compliance.md.
```

### 3.5 CI 守卫

`tests/acceptance/test_no_model_in_distribution.py`：

```python
"""Acceptance test AC-9: 模型权重绝不能进仓库 / 制品。

跑法: pytest -q tests/acceptance/test_no_model_in_distribution.py
CI: 任何 .yml workflow 必须调用此测试
"""

from pathlib import Path
import zipfile
import tarfile

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_onnx_in_repo():
    for p in REPO_ROOT.rglob("*.onnx"):
        # .cache 是运行时目录, git 不会追踪
        if ".cache" in p.parts:
            continue
        raise AssertionError(f"模型文件不得入仓: {p}")


def test_no_onnx_in_tests_fixtures():
    for p in (REPO_ROOT / "tests" / "fixtures").rglob("*.onnx"):
        raise AssertionError(f"测试 fixture 不得含模型: {p}")


def test_no_onnx_in_dist_artifacts():
    for archive in REPO_ROOT.glob("dist/*.whl"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if name.endswith(".onnx"):
                    raise AssertionError(f"wheel 含模型: {archive} :: {name}")
    for archive in REPO_ROOT.glob("dist/*.tar.gz"):
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                if m.name.endswith(".onnx"):
                    raise AssertionError(f"sdist 含模型: {archive} :: {m.name}")


def test_no_onnx_in_docker_build_context():
    dockerignore = (REPO_ROOT / ".dockerignore").read_text() if (REPO_ROOT / ".dockerignore").exists() else ""
    for must in ("*.onnx", "**/models/", "**/.insightface/", "**/__pycache__/"):
        assert must in dockerignore, f".dockerignore 必须排除: {must}"


def test_github_workflows_do_not_download_models():
    for yml in (REPO_ROOT / ".github" / "workflows").rglob("*.yml"):
        text = yml.read_text()
        for forbidden in ("init-models", "wget ", "curl -O"):
            assert forbidden not in text, f"{yml} 含下载模型命令: {forbidden}"


def test_pick_face_toml_template_default_license_false():
    """fallback 安全: 默认 accept=false, 用户必须显式打开。"""
    # toml 模板在仓库根
    toml_files = list(REPO_ROOT.rglob("pick-face.toml"))
    assert toml_files, "至少要有一个 toml 模板"
    for f in toml_files:
        text = f.read_text()
        assert "accept_noncommercial_model_license = false" in text, (
            f"{f} 必须默认 false (fail-safe)"
        )
```

### 3.6 退出码契约扩展（与 [03 §9](03-architecture-design.md) 兼容）

| 码 | 含义 | 新增条件 |
|----|------|----------|
| 0 | 成功 | — |
| 2 | 严重配置 / 参数错误 | **新增**：商业 license 校验失败（`buffalo_l` + `accept=false`） |
| 3 | 模型不可用 | 维持原意 |
| 4 | 关键阶段失败率 > 50% | 维持原意 |
| 5 | 中断 | 维持原意 |

### 3.7 文档显眼位置

每个用户必看的地方都明记一遍：

| 位置 | 内容 |
|------|------|
| 项目 README 顶部 | 「默认模型非商用；商业用户必读 docs/11」 |
| `LICENSE`（仓根） | Apache-2.0 文本 + 第三方权重声明段 |
| `pyproject.toml` 长描述 | 一行警示 |
| `pick-face init` 生成的 toml 模板 | 顶部注释块 |
| `pick-face init-models` 输出 | §3.3 的 License Notice |
| `pick-face run` 启动日志 | 一行 INFO：`model=buffalo_l license=non-commercial-research` |
| `report.md` 顶部 | §3.4 的 Model / License 字段 |
| 每次错误信息涉及模型 | 必带「见 docs/11-commercial-compliance.md」链接 |

---

## 4. 商业部署的标准流程

### 4.1 自训方案端到端

```
                  ┌──────────────────┐
                  │ 准备训练数据       │
                  │ (WebFace4M 等)   │
                  │  法务评估许可      │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ 训练 ArcFace/    │
                  │ AdaFace/MagFace  │
                  │ (1-2 周 GPU 集群) │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ torch.onnx.export│
                  │ → *.onnx         │
                  │ (5 分钟)         │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ pick-face.toml:  │
                  │   model_dir = …  │
                  │   accept = false │
                  │   model_name = … │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ 跑 smoke test:   │
                  │ AC-1 准率不降    │
                  │ AC-2 幂等 OK     │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ 跑 tests/         │
                  │ acceptance/       │
                  │ test_no_model_   │
                  │ in_distribut*.py │
                  └────────┬─────────┘
                           │
                           ▼
                       ✅ 上生产
```

### 4.2 商业部署 checklist

- [ ] 训练数据 license 审完（避开 MS1M 原始；用 WebFace4M / Glint360K / 自建）
- [ ] 训练脚本 license 确认（face.evoLVe.PyTorch = MIT ✅）
- [ ] 自训 checkpoint 已转 ONNX，体积 < 500 MB
- [ ] `pick-face.toml` 配 `model_dir` 指向自有权重
- [ ] `accept_noncommercial_model_license = false`
- [ ] smoke 跑通：AC-1 / AC-2 / AC-6
- [ ] CI `tests/acceptance/test_no_model_in_distribution.py` 全过
- [ ] 部署机器 `~/.insightface/` 为空（或不存在）
- [ ] 客户文档 / 法务文档里写明"模型为自训，Apache-2.0 / 商业自有"
- [ ] 如需第三方 SDK，签合同后再走 `FaceDetector` / `FaceEmbedder` Protocol

### 4.3 双轨过渡期（自训到投产前）

如果**自训还在跑**、但**生产已上线**：

```toml
# 主生产 toml — 商用
[runtime]
model_dir = "/srv/models/commercial"
model_name = "arcface_r50_webface4m"
accept_noncommercial_model_license = false

# 离线分析 toml — 仍可用 buffalo_l 做对照
# (与生产 toml 用不同路径, 互不干扰)
[runtime]
model_dir = "/srv/models/research"
model_name = "buffalo_l"
accept_noncommercial_model_license = true     # 研究语境, OK
```

**生产主路径**永远走自训权重；研究/对照环境允许 `buffalo_l`（仍在非商业研究范围内）。

---

## 5. 法务 / 审计视角

### 5.1 客户/法务问"你用了什么模型"时怎么答

- **个人客户 / 内部使用**：「用 InsightFace `buffalo_l` 模型包，license 为非商业研究。」附 [InsightFace LICENSE](https://github.com/deepinsight/insightface/blob/master/LICENSE) 链接。
- **商业客户 / SaaS / 集成产品**：「用我们**自训的 ArcFace/AdaFace 模型**（Apache-2.0/MIT 训练脚本 + 合法授权训练数据），checkpoint 与 ONNX 均为本团队所有。」附训练数据 license 清单 + ONNX 哈希。

### 5.2 收到「你用了 InsightFace 权重侵权」投诉的处置

- 项目方**不直接承担**——用户与 InsightFace 之间的合同关系。
- 处置：
  1. 把投诉转给**用户**（pick-face 部署方）。
  2. 用户在 `pick-face.toml` 把 `accept_noncommercial_model_license = false` 并切到自训权重。
  3. 协助做迁移（已铺好 [10 §5 升级路径](10-model-stack.md)）。
- 项目方**保留**在 README/LICENSE 明记"用户自负"的声明即可。

### 5.3 保留的合规证据

- 部署方应保留：
  1. `pick-face init-models` 时生成的 `.license_ack` 文件（带用户、时间戳）。
  2. `report.md` 的 Model / License 字段。
  3. 自训权重的训练日志、训练数据 license、数据来源证明。
  4. 第三方 SDK 的采购合同 / 商业 license 文件。
- 项目方**不**替用户保管这些；项目方在文档里**列清单**。

---

## 6. 决策表（速查）

| 你打算怎么用 | 你需要的配置 | 一句话 |
|---|---|---|
| 个人 / 研究 | `accept = true` + `model_name = buffalo_l` | 跑就行 |
| 公司内部工具 | 必走自训；`accept = false` + `model_dir` 指自训 | 不要心存侥幸 |
| 集成进付费 SaaS | 必走自训或商业 SDK | — |
| 学术 demo | `accept = true` + `model_name = buffalo_l` | 引用 InsightFace 即可 |
| 出海（GDPR / 数据出境） | 自训 + 数据审计 + DPIA | pick-face 帮你处理技术部分，**法务另走** |
| v0.1 demo 跑通 | `accept = true` + `model_name = buffalo_l` | 用 50 人 / 1000 张 demo 集验 |
| v0.1 上生产 | 自训 | 没有捷径 |

---

## 7. 引用与延伸阅读

- [10 §4 模型许可与合规表](10-model-stack.md)
- [10 §5 模型版本与升级策略](10-model-stack.md)
- [10 §7 模型下载与离线部署](10-model-stack.md)
- [01 §6 R-COM-1 商业合规风险](01-product-requirement.md)
- [01 §4 NF 许可证行 + AC-9 商业合规护栏](01-product-requirement.md)
- [03 §9 错误处理 / 退出码契约](03-architecture-design.md)
- [06 §7 依赖与 CI（含 extras 矩阵）](06-engineering-plan.md)
- [07 ADR-005 离线默认 + ADR-007 不遥测](07-risk-and-decisions.md)
- [08 §6 最终方案](08-review-notes.md)
- InsightFace LICENSE — https://github.com/deepinsight/insightface/blob/master/LICENSE
- face.evoLVe.PyTorch（MIT 训练脚本）— https://github.com/ZhaoJ9014/face.evoLVe.PyTorch
- WebFace4M — https://github.com/lyyyyyy/Compact-IFQA
- Glint360K — https://github.com/deepinsight/insightface/tree/master/dataset/Glint360K
- AdaFace (MIT) — https://github.com/mk-minchul/AdaFace
- MagFace (Apache-2.0) — https://github.com/IrvingMeng/MagFace
