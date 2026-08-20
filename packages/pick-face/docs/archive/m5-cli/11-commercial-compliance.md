# 11 商业部署合规指南

> 文档版本：v0.2（路线 B 落地稿） · 2026-08-07
> 范围：把"默认 `yunet-mfn` Apache-2.0，opt-in `buffalo_l` NC-research"这一新结构在产品、代码、文档、发布四个层面**完整闭环**。
> **本文是单一权威解读**。任何与本文件冲突的章节（README / 01 / 02 / 10 / 03 §11 / 04 / 06 / 08 / 09），以本文件为准。
> 关联：[08 §6 最终方案](08-review-notes.md) · [10 §0 / §5 model pack 与许可](10-model-stack.md) · [01 R-COM-1](01-product-requirement.md) · [03 §11 包管理](03-architecture-design.md) · [06 §7.2 extras](06-engineering-plan.md) · [07 ADR-005/007](07-risk-and-decisions.md) · [13 §8 Pi 路径 AC-9 自然消失](13-raspberry-pi-support.md) · [14-model-pack-plugins.md](14-model-pack-plugins.md)

## 0. 摘要（60 秒版）

| 问题 | 答案（v2.0 路线 B） |
|---|---|
| pick-face 本体能商用吗？ | **✅ 是**，Apache-2.0。 |
| **默认**的 model pack 商用吗？ | **✅ 是**，`yunet-mfn` 是 Apache-2.0，**直接商用合法**。 |
| `buffalo_l` 权重商用吗？ | **❌ 否**，NC-research；opt-in 装 `pick-face-modelpack-insightface` 后才走它。 |
| 谁的责任？ | **用户**。项目方不为第三方权重背书。 |
| 商业用户怎么办？ | **4 选 1**：(a) 自训，(b) 买 InsightFace 商业 license，(c) 换 AdaFace/MagFace，(d) **用默认 `yunet-mfn`（Apache-2.0）**。 |
| 在 pick-face 里怎么"切"？ | 改 `pick-face.toml` 的 `[runtime] pack` + `[runtime] model_dir`。 |
| 项目方做了什么护栏？ | (1) **不**捆绑任何 `*.onnx`；(2) `init-models` 强制交互确认；(3) LicenseClass-driven 启动强校验；(4) `report.md` 标 model + license；(5) CI 守卫防模型泄露；(6) README/LICENSE 顶部明记用户自负。 |

---

## 1. 许可证边界

### 1.1 三层独立物（路线 B 后）

```
┌──────────────────────────────────────────────────────┐
│  你的公司 / 你的产品                                  │
│  (商业行为发生地)                                      │
└──────────────────┬───────────────────────────────────┘
                   │ 使用
                   ▼
┌──────────────────────────────────────────────────────┐
│  pick-face core (Apache-2.0)                          │
│  · 扫描、聚类、链接、报告的代码                         │
│  · 不含任何 *.onnx                                    │
│  · 不依赖 insightface / onnxruntime (pack 自带)        │
│  · 通过 entry-points `pick_face.model_packs` 加载 pack │
└──────────────────┬───────────────────────────────────┘
                   │ ModelPack Protocol (见 14 §2)
                   ▼
┌──────────────────────────────────────────────────────┐
│  model pack 插件 (Apache-2.0 或 MIT)                  │
│  · pick-face-modelpack-yunet (默认, Apache-2.0)        │
│  · pick-face-modelpack-insightface (opt-in, MIT 代码 + │
│    NC-research 权重)                                   │
│  · pick-face-modelpack-my-arcface (自训, 自定 license) │
└──────────────────┬───────────────────────────────────┘
                   │ 加载
                   ▼
┌──────────────────────────────────────────────────────┐
│  权重文件                                              │
│  位置: model_dir/<pack_id>/<file>.onnx                │
│  yunet-mfn      ~5 MB   Apache-2.0                    │
│  buffalo_l    ~325 MB   InsightFace NC-research        │
│  my-arcface    自定      自定                          │
└──────────────────────────────────────────────────────┘
```

**关键点**：**触发 InsightFace 权重 license 的是「使用了 NC-research 的 pack」**，不是 pick-face 包、不是安装行为、不是下载行为。**默认 `yunet-mfn` 是 Apache-2.0，商业用户开箱即用**。

### 1.2 各 pack license 速查

| Pack id | 许可证 | 商业可用 | AC-9 gate |
|---|---|---|---|
| **`yunet-mfn`**（默认） | **Apache-2.0** | **✅** | 不触发 |
| `buffalo_l` / `buffalo_sc` / `antelopev2` | InsightFace 自定义 | ❌ | 触发（要 ack） |
| `my-arcface-r50`（自训） | 自定（PERMISSIVE / NC 视训练数据） | 视训练数据 license | 视 `LicenseClass` |
| pick-face 代码 | Apache-2.0 | ✅ | — |
| pick-face 文档 | CC-BY-4.0 | ✅ | 注明出处的复用 |
| onnxruntime | MIT | ✅ | — |
| hnswlib | Apache-2.0 | ✅ | — |
| hdbscan | BSD | ✅ | — |
| Pillow / OpenCV / NumPy / xxhash | HPND / Apache-2.0 / BSD | ✅ | — |
| face.evoLVe.PyTorch（训练脚本） | MIT | ✅ | 训练出来的权重归你 |
| WebFace4M / Glint360K（数据） | 各自条款 | ⚠ 视具体 license | 训练前逐项查 |
| AdaFace / MagFace 训练代码 | MIT / Apache-2.0 | ✅ | 训出来的权重归你 |

---

## 2. 用户必读

### 2.1 个人 / 研究 / 非营利用户

✅ **直接用默认**。`yunet-mfn` 完全够用，**不需要 ack 任何 license**。

```bash
pip install pick-face
pick-face init        # 生成 toml (pack = "yunet-mfn", Apache-2.0)
pick-face init-models --pack yunet-mfn --allow-network
pick-face run --src ~/Photos --out ~/Photos/by_face
```

老用户想用 `buffalo_l`（精度更高但仅个人/学术）：

```bash
pip install pick-face-modelpack-insightface
# 编辑 pick-face.toml: pack = "buffalo_l", accept_noncommercial_model_license = true
pick-face init-models --pack buffalo_l --allow-network --yes
```

**前提**：`accept_noncommercial_model_license = true` 是你对 InsightFace 条款的**明示同意**，pick-face 仅作为凭证记录。

### 2.2 商业用户（公司内部 / SaaS / 出海 / 任何"产生或支持商业收入"的场景）

#### 选项 D：用默认 `yunet-mfn`（**路线 B 新增，最简单**）

✅ `yunet-mfn` 是 Apache-2.0，**直接商用合法**，无需任何额外配置。

```bash
pip install pick-face
pick-face init
# 保持默认: pack = "yunet-mfn", accept_noncommercial_model_license = false (no-op)
pick-face init-models --pack yunet-mfn --allow-network --yes
pick-face run --src /data/photos --out /data/by_face
```

**取舍**：LFW 精度 99.50%（比 buffalo_l 的 99.83% 略低 ~0.3 pp）；RAM 常驻 150 MB；跑得稍慢。对"整理自己照片"场景，**人眼几乎无感**。

#### 选项 A：自训（控制力最强，路线 B 同样适用）

```bash
# 1) 拉训练脚本（MIT）
git clone https://github.com/ZhaoJ9014/face.evoLVe.PyTorch
cd face.evoLVe.PyTorch

# 2) 准备训练数据（**避开** MS1M 原始，已下架）
#    推荐 WebFace4M（4M 图，许可相对清晰）
#    或 Glint360K（360k 人）

# 3) 训练 r50@WebFace4M
python -m torch.distributed.launch --nproc_per_node=4 \
    train.py --network r50 --dataset webface4m --loss arcface

# 4) PyTorch → ONNX
python export_onnx.py --ckpt r50_webface4m.pth --out /srv/models/commercial/arcface.onnx

# 5) 写自己的 model pack（参考 docs/14）
#    pick-face-modelpack-my-arcface/
#    ├─ pyproject.toml  (注册 entry-point "my-arcface-r50")
#    └─ src/pick_face_modelpack_my_arcface/pack.py
#    descriptor.license_class = LicenseClass.PERMISSIVE

# 6) 装 + 配
pip install /path/to/pick-face-modelpack-my-arcface
cat >> pick-face.toml <<'EOF'
[runtime]
pack = "my-arcface-r50"
model_dir = "/srv/models/commercial"
EOF

# 7) 跑（不再触发任何 InsightFace 下载）
pick-face run --src /data/photos --out /data/by_face
```

**关键合规点**：
- **数据**才是大头：训练数据本身的 license / 肖像权 / 爬取合规要逐项审
- **checkpoint** 是你的，归你所有，license 你定
- **ONNX** 是你的
- **model pack** 是你自己的 PyPI 包，LicenseClass = PERMISSIVE

#### 选项 B：买 InsightFace Pro / 商业 SDK 许可

- InsightFace 商业 license（直接联系原厂）
- 第三方 SDK：AWS Rekognition、Face++、旷视、商汤、百度 AI 开放平台
- 在 pick-face 里实现 `pick_face.ingest.detector.FaceDetector` Protocol 即可，**业务代码 0 改**

#### 选项 C：换模型族（AdaFace / MagFace / MobileFaceNet）

- 训练脚本 MIT，训出来的权重**你**拥有，**与 InsightFace 完全脱钩**
- 性能对标 `buffalo_l`（LFW 99.78%+；CALFW/CPLFW 略强）
- 详见 [10 §2.5](10-model-stack.md)

### 2.3 "是不是商业"的判定（不要揣测）

| 场景 | 是否商业 | 备注 |
|------|---------|------|
| 我自己整理我自己的照片 | ❌ 非商业 | 用默认 `yunet-mfn`（Apache-2.0） |
| 我帮邻居免费整理他们的照片 | ⚠ 灰色 | 涉及"代他人处理个人数据"；仍建议 Apache-2.0 pack 以避风险 |
| 公司内部工具箱免费给员工用 | ⚠ 灰色 | 公司上下文通常视为"商业使用"；用 yunet-mfn 或自训 |
| 集成进收费 SaaS / 商业产品 | ✅ 商业 | ✅ yunet-mfn 可直接用；❌ buffalo_l 不行 |
| 集成进公司产品供客户使用 | ✅ 商业 | ✅ yunet-mfn 或自训；❌ buffalo_l |
| 给付费客户提供人脸库整理服务 | ✅ 商业 | 同上 |
| 学术论文 demo | ❌ 非商业研究 | 默认 yunet-mfn OK；想用 buffalo_l 引用 InsightFace 即可 |

**判不准就用 yunet-mfn**（路线 B 默认）—— license 干净，比自训省事，比 buffalo_l 安全。

---

## 3. 项目方的护栏（不依赖用户善意）

### 3.1 代码层：完全解耦

| 动作 | 文件 | 内容 |
|------|------|------|
| `.gitignore` 兜底 | 仓根 | `*.onnx`、`*.pt`、`*.pth`、`models/`、`bench/dataset_demo/.insightface/` 等全列黑名单 |
| `pyproject.toml` 不绑模型 | 项目 | `[project]` 与所有 extras 中**不出现** `insightface-models-*` 或任何 `*.onnx` 直接依赖；`insightface` 和 `onnxruntime` 移到 opt-in extras 或 pack 自己声明 |
| `Dockerfile` 不装模型 | 镜像 | build 完 `uv pip install -e ".[dev]"` 就停，**不**调 `init-models` |
| CI 不下模型 | `.github/workflows/*.yml` | `actions/cache` **不**缓存 `model_dir`；test.yml 不跑 `init-models` |
| PyPI wheel/sdist 不带模型 | release.yml | `uv build` 产物 `MANIFEST.in` 不 include 任何 `*.onnx` |

### 3.2 启动时强校验（路线 B：LicenseClass-driven）

`pick-face.toml`：

```toml
[runtime]
# 选定要用的 model pack id（通过 entry-points 解析）
# 默认: "yunet-mfn"（Apache-2.0，不触发 AC-9）
pack = "yunet-mfn"

# 模型根目录；默认 ~/.cache/pick-face/models/
model_dir = "~/.cache/pick-face/models"

# 显式声明当前使用的模型来源与是否接受非商业研究 license
# 默认 false（fail-safe）；仅在 pack 的 LicenseClass.NC_RESEARCH 时被读
# yunet-mfn 是 PERMISSIVE → 此字段无论真假都放行
# buffalo_l 是 NC_RESEARCH → 必须 true，否则启动 exit 2
accept_noncommercial_model_license = false
```

`pick-face run` 启动逻辑（伪码，路线 B 后）：

```python
def preflight_check(cfg):
    pack = discover_packs()[cfg.runtime.pack]   # entry-points 解析

    # LicenseClass-driven gate
    if pack.descriptor.license_class is LicenseClass.NC_RESEARCH:
        if not cfg.runtime.accept_noncommercial_model_license:
            raise UserFacingError(
                f"Pack {pack.descriptor.pack_id!r} is "
                f"{pack.descriptor.license_name} (non-commercial-research).\n"
                f"You have not set [runtime] accept_noncommercial_model_license = true.\n"
                f"Three legal paths to use pick-face commercially (see docs/11):\n"
                f"  (a) Self-train an MIT-licensed model (recommended)\n"
                f"  (b) Obtain a commercial license from InsightFace\n"
                f"  (c) Switch to a different MIT/Apache-2.0 model family\n"
                f"  (d) Use the default 'yunet-mfn' pack (Apache-2.0, no ack)\n",
                exit_code=2,
            )
        log.warn(
            "Using '%s' under %s license. Confirm your use case qualifies "
            "(personal / academic / non-profit).",
            pack.descriptor.pack_id,
            pack.descriptor.license_name,
        )

    # PERMISSIVE / USER_SUPPLIED: silent pass
    # (USER_SUPPLIED still warns in report header)
```

`init-models` 子命令（路线 B 后）：

```python
def cmd_init_models(*, pack: str, allow_network: bool, yes: bool = False):
    if not allow_network:
        sys.exit("Refusing to download models without --allow-network.")
    pack_obj = discover_packs()[pack]
    # LicenseClass-driven license notice
    if pack_obj.descriptor.license_class is LicenseClass.NC_RESEARCH:
        if not yes:
            print(pack_obj.descriptor.license_notice_text)
            if input("Type 'I AGREE' to continue: ") != "I AGREE":
                sys.exit("Aborted.")
    target = cfg.runtime.model_dir / pack
    pack_obj.download_to(target)
    # 落盘证据 (仅 NC_RESEARCH 路径)
    if pack_obj.descriptor.license_class is LicenseClass.NC_RESEARCH:
        write_license_ack(target, pack)
```

### 3.3 `init-models` 启动时打印的 License 提示全文（NC-research pack）

```
═══════════════════════════════════════════════════════════════════════
  InsightFace buffalo_l — License Notice
═══════════════════════════════════════════════════════════════════════

You are about to download the InsightFace "buffalo_l" model pack
(detector + embedder, ~325 MB).

  Source  : https://github.com/deepinsight/insightface
  License : InsightFace — "Non-Commercial Research Use Only"

  ⚠ If you are using this in any commercial context — including but
    not limited to:
      · a company-internal tool,
      · a paid SaaS / cloud product,
      · a product shipped to paying customers,
      · use by an employee in the course of work for a for-profit
        company, or
      · any use that supports, directly or indirectly, revenue —
    you are NOT permitted to use buffalo_l under its license.

    You must EITHER:
      (a) Self-train a model (see docs/11 §2.2 option A),
      (b) Obtain a commercial license from InsightFace,
      (c) Use a different MIT/Apache-2.0 model family
          (AdaFace, MagFace, MobileFaceNet, …),
      (d) Use the default 'yunet-mfn' pack (Apache-2.0, no ack).

═══════════════════════════════════════════════════════════════════════
Type 'I AGREE' to confirm your use case qualifies as non-commercial
research (per the InsightFace license terms), or 'NO' to abort:
═══════════════════════════════════════════════════════════════════════
```

**注意**：使用 `yunet-mfn` 时**不打印**此提示（PERMISSIVE license 不要求 ack）。

### 3.4 报告顶部明记（审计友好）

`report.md` 顶部新增一节：

```markdown
# pick-face Report

- **Run ID**: 2026-08-07T14:23:11Z
- **Pack**: `yunet-mfn` (YuNet + MobileFaceNet, Apache-2.0)
- **License**: Apache-2.0 ✅ commercial-friendly
- **Provider**: CPUExecutionProvider
- **Total sources**: 1234
- ...

---

## ⚠ Warnings
(none)
```

NC-research pack 时：

```markdown
- **Pack**: `buffalo_l` (SCRFD-10G + ArcFace w600k_r50, NC-research)
- **License**: InsightFace non-commercial-research ❗
- **Accepted by**: user "alice" on 2026-08-07 (see `.cache/buffalo_l/.license_ack`)

---

## ⚠ Warnings
- Pack `buffalo_l` is under a non-commercial-research license.
  Confirm your use case qualifies, or replace the pack per
  docs/11-commercial-compliance.md.
```

### 3.5 CI 守卫

`tests/acceptance/test_no_model_in_distribution.py`：

```python
"""Acceptance test AC-9: 模型权重绝不能进仓库 / 制品。
CI: 任何 .yml workflow 必须调用此测试
"""

from pathlib import Path
import zipfile, tarfile

REPO_ROOT = Path(__file__).resolve().parents[2]

def test_no_onnx_in_repo():
    for p in REPO_ROOT.rglob("*.onnx"):
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

def test_no_onnx_in_docker_build_context():
    dockerignore = (REPO_ROOT / ".dockerignore").read_text() if (REPO_ROOT / ".dockerignore").exists() else ""
    for must in ("*.onnx", "**/models/", "**/.insightface/", "**/__pycache__/"):
        assert must in dockerignore, f".dockerignore 必须排除: {must}"

def test_github_workflows_do_not_download_models():
    for yml in (REPO_ROOT / ".github" / "workflows").rglob("*.yml"):
        text = yml.read_text()
        for forbidden in ("init-models", "wget ", "curl -O"):
            assert forbidden not in text, f"{yml} 含下载模型命令: {forbidden}"

def test_pick_face_toml_template_default_pack_permissive():
    """路线 B fail-safe: 默认 pack 必须是 PERMISSIVE license 的。"""
    from pick_face.platform.pack import LicenseClass
    from pick_face.platform.packs.yunet_mfn import DESCRIPTOR
    assert DESCRIPTOR.license_class is LicenseClass.PERMISSIVE
    # toml 模板默认 pack 字段也匹配
    import tomllib
    for f in REPO_ROOT.rglob("pick-face.toml"):
        cfg = tomllib.parse(f.read_text())
        assert cfg["runtime"]["pack"] == "yunet-mfn", f"{f} 默认 pack 必须是 yunet-mfn"
        assert cfg["runtime"]["accept_noncommercial_model_license"] is False, f"{f} 必须默认 false"

def test_no_insightface_in_default_deps():
    """路线 B: pick-face core 默认依赖里不能强制拉 insightface。"""
    import tomllib
    pyproject = tomllib.parse((REPO_ROOT / "pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    assert not any("insightface" in d for d in deps), \
        "insightface 不应在 pick-face 默认依赖里；改由 pack 自带"
```

### 3.6 退出码契约扩展（路线 B 与 03 §9 兼容）

| 码 | 含义 | 新增条件 |
|----|------|----------|
| 0 | 成功 | — |
| 2 | 严重配置 / 参数错误 | **新增**：NC-research pack 但 `accept_noncommercial_model_license = false` |
| 3 | 模型不可用 | 维持原意 |
| 4 | 关键阶段失败率 > 50% | 维持原意 |
| 5 | 中断 | 维持原意 |

### 3.7 文档显眼位置

每个用户必看的地方都明记一遍：

| 位置 | 内容 |
|------|------|
| 项目 README 顶部 | "默认 `yunet-mfn` Apache-2.0 ✅ 商用合规"；opt-in NC-research 见 docs/11 |
| `LICENSE`（仓根） | Apache-2.0 文本 + 第三方权重声明段 |
| `pyproject.toml` 长描述 | 一行："默认 pack = yunet-mfn, Apache-2.0, 商用合规" |
| `pick-face init` 生成的 toml 模板 | 顶部注释块 + `[runtime] pack` 默认值 |
| `pick-face init-models` 输出 | LicenseClass.NC_RESEARCH 才打印 License Notice |
| `pick-face run` 启动日志 | 一行 INFO: `pack=yunet-mfn license=Apache-2.0` |
| `report.md` 顶部 | §3.4 的 Pack / License 字段 |
| 每次错误信息涉及模型 | 必带"见 docs/11-commercial-compliance.md"链接 |

---

## 4. 商业部署的标准流程

### 4.1 三条路径（路线 B 后）

```
路径 1 (选项 D, 最简单):
    pip install pick-face
    pick-face init
    pick-face init-models --pack yunet-mfn --allow-network --yes
    pick-face run ...
    ↓
    ✅ 上生产

路径 2 (选项 A, 自训):
    训练 ArcFace/AdaFace/MagFace → ONNX → 写自己 pack → PyPI
    pip install pick-face pick-face-modelpack-my-arcface
    pick-face.toml: pack = "my-arcface-r50"
    ↓
    ✅ 上生产

路径 3 (选项 B, 商业 license):
    与 InsightFace 签合同
    用 pick-face-modelpack-insightface (Apache-2.0 代码 + 商业授权权重)
    pick-face.toml: pack = "buffalo_l", accept = true
    ↓
    ✅ 上生产
```

### 4.2 商业部署 checklist（路线 B 版）

**路径 1（yunet-mfn 默认）**：
- [ ] `pip install pick-face`（核心包，~30 MB）
- [ ] `pick-face init` 生成 toml（`pack = "yunet-mfn"` 默认）
- [ ] `pick-face init-models --pack yunet-mfn --allow-network --yes`（下载 5 MB ONNX）
- [ ] smoke 跑通：AC-1 / AC-2 / AC-6
- [ ] CI `tests/acceptance/test_no_model_in_distribution.py` 全过
- [ ] 部署机器 `model_dir` 为空（或不存在），首次运行才下权重
- [ ] 客户文档 / 法务文档里写明"使用 Apache-2.0 模型，无商业授权义务"

**路径 2（自训）**：在路径 1 基础上加：
- [ ] 训练数据 license 审完（避开 MS1M 原始；用 WebFace4M / Glint360K / 自建）
- [ ] 训练脚本 license 确认（face.evoLVe.PyTorch = MIT ✅）
- [ ] 自训 checkpoint 已转 ONNX
- [ ] 写自己的 model pack（[14 §3](14-model-pack-plugins.md)），`LicenseClass.PERMISSIVE`
- [ ] 内部 PyPI 发布或 `pip install -e ./`

**路径 3（商业 license）**：在路径 1 基础上加：
- [ ] InsightFace 商业 license 签合同
- [ ] 装 `pick-face-modelpack-insightface`
- [ ] `pack = "buffalo_l"`, `accept = true`
- [ ] 保留合同 + license_ack 文件

---

## 5. 法务 / 审计视角

### 5.1 客户/法务问"你用了什么模型"时怎么答

- **默认 `yunet-mfn` 部署**：「用 OpenCV Zoo YuNet + MobileFaceNet INT8，**Apache-2.0**，商业零授权义务。」附 [OpenCV Zoo repo](https://github.com/opencv/opencv_zoo) 链接 + 各 ONNX 的 SHA256。
- **自训部署**：「用我们自训的 ArcFace/AdaFace/MagFace 模型（Apache-2.0/MIT 训练脚本 + 合法授权训练数据），checkpoint 与 ONNX 均为本团队所有。」附训练数据 license 清单 + ONNX 哈希。
- **商业 license 部署**：「用 InsightFace 商业授权模型包，license 文件附后。」附合同副本 + .license_ack 文件。
- **老 buffalo_l NC-research 部署（仅个人/研究）**：「用 InsightFace `buffalo_l` 模型包，license 为非商业研究。」附 [InsightFace LICENSE](https://github.com/deepinsight/insightface/blob/master/LICENSE) 链接 + .license_ack。

### 5.2 收到"你用了 InsightFace 权重侵权"投诉的处置

1. 确认部署方是否走 `yunet-mfn` 路径（`report.md` 顶部 Pack 字段）
2. 如果是 → 项目方无责（Apache-2.0）
3. 如果是 `buffalo_l` 且 `accept = true` → 用户与 InsightFace 之间的合同关系，项目方不直接承担
5. 协助做迁移（[10 §6](10-model-stack.md) 已铺好升级路径）

### 5.3 保留的合规证据

- 部署方应保留：
  1. `pick-face init-models` 时生成的 `.license_ack` 文件（仅 NC_RESEARCH 路径带）
  2. `report.md` 的 Pack / License 字段
  3. 自训权重的训练日志、训练数据 license、数据来源证明
  4. 第三方 SDK 的采购合同 / 商业 license 文件
- 项目方**不**替用户保管这些；项目方在文档里**列清单**

---

## 6. 决策表（路线 B 速查）

| 你打算怎么用 | 你需要的配置 | 一句话 |
|---|---|---|
| 个人 / 研究 / 整理自己照片 | `pack = "yunet-mfn"`（默认）| 跑就行，Apache-2.0 |
| 公司内部工具（避风险）| `pack = "yunet-mfn"`（默认）| Apache-2.0，无需 ack |
| 集成进付费 SaaS（简单） | `pack = "yunet-mfn"`（默认）| Apache-2.0，商用零摩擦 |
| 集成进付费 SaaS（高精度）| 自训 + `pack = "my-arcface-r50"` | 控制力最强 |
| 学术论文 demo | `pack = "yunet-mfn"` 或 `pack = "buffalo_l"` (要 ack) | 引用即可 |
| 已有 InsightFace 商业 license | 装 pack 插件 + `pack = "buffalo_l"`, `accept = true` | 走合同 |
| 出海（GDPR / 数据出境）| 自训 + 数据审计 + DPIA | pick-face 帮你处理技术部分，**法务另走** |
| v0.1 demo 跑通 | `pack = "yunet-mfn"`（默认） | 用 50 人 / 1000 张 demo 集验 |
| v0.1 上生产 | `pack = "yunet-mfn"` 或自训 | **buffalo_l 默认路径已废**，路线 B 后默认就商用合规 |

---

## 7. 引用与延伸阅读

- [10 §0 / §5 model pack 总览](10-model-stack.md)
- [13 §8 Pi / ARM 路径 AC-9 自然消失](13-raspberry-pi-support.md)
- [14-model-pack-plugins.md](14-model-pack-plugins.md) — ModelPack Protocol
- [01 §6 R-COM-1 商业合规风险](01-product-requirement.md)
- [01 §4 NF 许可证行 + AC-9 商业合规护栏](01-product-requirement.md)
- [03 §9 错误处理 / 退出码契约](03-architecture-design.md)
- [06 §7 依赖与 CI（含 extras 矩阵）](06-engineering-plan.md)
- [07 ADR-005 离线默认 + ADR-007 不遥测](07-risk-and-decisions.md)
- [08 §6 最终方案](08-review-notes.md)
- InsightFace LICENSE — https://github.com/deepinsight/insightface/blob/master/LICENSE
- OpenCV Zoo — https://github.com/opencv/opencv_zoo
- face.evoLVe.PyTorch（MIT 训练脚本）— https://github.com/ZhaoJ9014/face.evoLVe.PyTorch
- WebFace4M — https://github.com/lyyyyyy/Compact-IFQA
- Glint360K — https://github.com/deepinsight/insightface/tree/master/dataset/Glint360K
- AdaFace (MIT) — https://github.com/mk-minchul/AdaFace
- MagFace (Apache-2.0) — https://github.com/IrvingMeng/MagFace
- SPDX License List — https://spdx.org/licenses/