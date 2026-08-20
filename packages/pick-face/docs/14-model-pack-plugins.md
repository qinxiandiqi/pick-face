# 14 Model Pack 插件契约

> 文档版本：v3.0 · 2026-08-12
> 范围：定义 **第三方 / 内部** model pack 插件如何接入 pick-face（包括 v3 Web 服务 + v2.x CLI），插件作者**应该**遵守什么、**不应该**触碰什么。
> **本文是单一权威解读**。任何与本文件冲突的章节（README / 03 / 10 / 13），以本文件为准。

> **v3 note**：v3 Web 服务复用 v2.x 的 Model Pack 架构 100%。`build_detector` / `build_embedder` / `build_aligner` 在 FastAPI `app.on_event("startup")` 阶段被调用一次，session 复用。`providers=` 关键字在 v3 真正用于路由 CUDA / DirectML EP（v2.x CLI 也已支持）。
> 关联：[10-model-stack.md](10-model-stack.md) · [13-raspberry-pi-support.md](13-raspberry-pi-support.md)

## 0. 摘要（60 秒版）

| 问题 | 答案 |
|---|---|
| pick-face 怎么知道装了哪些 model pack？ | 通过 Python entry-points `pick_face.model_packs` 自动发现。 |
| 一个 pack 是什么？ | 一个独立的 PyPI 包，提供 `ModelPack` Protocol 实现。 |
| 谁来负责模型权重？ | pack 自己（自己下载、自己 SHA256 校验、自己落到 `[runtime] model_dir/<pack_id>/`）。 |
| pick-face core 还强制依赖哪些 ML 框架？ | **只**依赖 `onnxruntime` (CPU)。`insightface` / `torch` / `tensorflow` **全部是可选**，只 pack 自己需要。 |
| 我能写自己的 pack 吗？ | ✅ 可以。最小 ~50 行代码，发布到自己 PyPI 即可。 |

## 1. 什么是 Model Pack

A *Model Pack* 是一个独立的 PyPI 包，提供：

1. **一个** `Detector` 实现
2. **一个** `Embedder` 实现
3. **一个** `Aligner`（可选；默认复用 ArcFace 5-pt）
4. **一个** `PackDescriptor`（自描述：名字、license、URL、SHA256、大小、tags）
5. **一个** `download_to()` 方法（如何把权重拉到 `[runtime] model_dir/<pack_id>/`）

核心包 `pick-face` 通过 [importlib.metadata.entry_points()](https://docs.python.org/3/library/importlib.metadata.html) 在 `pick_face.model_packs` 组里发现已安装的 pack，**不在核心代码里硬编码任何 pack id**。

## 2. Protocol 契约

```python
# src/pick_face/platform/pack.py（核心包，已存在）

@runtime_checkable
class ModelPack(Protocol):
    descriptor: PackDescriptor

    def expected_files(self) -> list[str]: ...
    def build_detector(
        self, model_dir: Path, ctx_id: int = 0,
        det_size: tuple[int, int] = (320, 320),
    ) -> Detector: ...
    def build_embedder(self, model_dir: Path) -> Embedder: ...
    def build_aligner(self) -> Aligner: ...
    def download_to(
        self, target_dir: Path, *, progress=None,
    ) -> list[Path]: ...
```

具体签名见 [src/pick_face/platform/pack.py](../src/pick_face/platform/pack.py) 与 [Detector](../src/pick_face/ingest/detector.py) / [Embedder](../src/pick_face/ingest/embedder.py) / [Aligner](../src/pick_face/ingest/align.py) Protocols。

## 3. 最小 Pack 示例（50 行 PyPI 包）

```
pick-face-modelpack-yunet/
├── pyproject.toml
└── src/pick_face_modelpack_yunet/
    ├── __init__.py
    └── pack.py
```

### 3.1 `pyproject.toml`

```toml
[project]
name = "pick-face-modelpack-yunet"
version = "0.1.0"
requires-python = ">=3.10,<3.14"
dependencies = [
    "pick-face>=2.0",
    "onnxruntime>=1.17,<2",
    "opencv-python>=4.9",
    "numpy>=1.24",
]

[project.entry-points."pick_face.model_packs"]
yunet-mfn = "pick_face_modelpack_yunet.pack:YuNetMFNPack"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pick_face_modelpack_yunet"]
```

### 3.2 `src/pick_face_modelpack_yunet/pack.py`

```python
"""YuNet detector + MobileFaceNet embedder pack (MIT).

注册为 `yunet-mfn`，是 pick-face 2.0 起保留的 deprecated alias（指向
`yunet-sface`），用于 v1.x 配置文件向后兼容。2.0 默认 pack id 是
`yunet-sface`（YuNet + SFace，OpendCV Zoo per-model MIT）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from pick_face.ingest.align import ARCFACE_REFERENCE_5P, warp_to_112, Aligner
from pick_face.ingest.detector import Detection, Detector
from pick_face.ingest.embedder import Embedder, l2_normalize
from pick_face.platform.pack import (
    LicenseClass, ModelPack, PackDescriptor,
)


YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
MFN_URL   = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_mobilefacenet_20221220/face_recognition_mobilefacenet_20221220_int8.onnx"
DESCRIPTOR = PackDescriptor(
    pack_id="yunet-mfn",
    display_name="YuNet + MobileFaceNet (OpenCV Zoo)",
    detector_name="YuNet (face_detection_yunet_2023mar.onnx)",
    embedder_name="MobileFaceNet INT8 (face_recognition_mobilefacenet_20221220_int8.onnx)",
    detector_sha256="<pin-on-first-build>",
    embedder_sha256="<pin-on-first-build>",
    detector_size_bytes=371_386,
    embedder_size_bytes=5_027_712,
    detector_url=YUNET_URL,
    embedder_url=MFN_URL,
    license_class=LicenseClass.PERMISSIVE,
    license_name="Apache-2.0 (OpenCV Zoo)",
    license_spdx="Apache-2.0",
    license_notice_text="",
    accuracy_lfw=0.9950,
    notes="Default ARM-friendly pack. ~5 MB on disk, ~150 MB RAM at runtime.",
    tags=["arm-friendly", "low-ram", "default"],
)


class YuNetDetector(Detector):
    name = "YuNet"
    model_version = "face_detection_yunet_2023mar.onnx"

    def __init__(self, onnx_path: Path, det_size=(320, 320)) -> None:
        import cv2
        self._d = cv2.FaceDetectorYN.create(
            str(onnx_path), "", (det_size[0], det_size[1]),
            score_threshold=0.6, nms_threshold=0.3, top_k=5000,
        )
        self._ds = det_size

    def warmup(self, det_size):
        try:
            self._d.detect(np.zeros((det_size[1], det_size[0], 3), np.uint8))
        except Exception:
            pass

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        if (w, h) != self._ds:
            self._d.setInputSize((w, h))
        _, raw = self._d.detect(bgr)
        if raw is None:
            return []
        out = []
        for r in raw:
            x, y, ww, hh = r[0:4]
            kps = np.asarray(r[4:14], dtype=np.float32).reshape(5, 2)
            chip = warp_to_112(bgr, kps)
            out.append(Detection(
                bbox=(float(x), float(y), float(x+ww), float(y+hh)),
                det_score=float(r[14]),
                landmarks=kps,
                chip=chip,
                quality=0.5,
            ))
        return out


class MobileFaceNetEmbedder(Embedder):
    dim = 128
    model_version = "face_recognition_mobilefacenet_20221220_int8.onnx"

    def __init__(self, onnx_path: Path) -> None:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(
            str(onnx_path), sess_options=so,
            providers=["CPUExecutionProvider"],
        )
        self._name = self._sess.get_inputs()[0].name

    def embed(self, chip_rgb):
        bgr = chip_rgb[..., ::-1].copy().astype(np.float32)
        x = ((bgr - 127.5) / 128.0).transpose(2, 0, 1)[None]
        out = self._sess.run(None, {self._name: x})[0]
        return l2_normalize(out[0].astype(np.float32))


class ArcFaceAligner(Aligner):
    ref_landmarks = ARCFACE_REFERENCE_5P
    def warp(self, bgr, landmarks):
        return warp_to_112(bgr, landmarks)


class YuNetMFNPack(ModelPack):
    descriptor = DESCRIPTOR

    def expected_files(self):
        return ["face_detection_yunet_2023mar.onnx",
                "face_recognition_mobilefacenet_20221220_int8.onnx"]

    def build_detector(self, model_dir, ctx_id=0, det_size=(320, 320)):
        p = model_dir / self.descriptor.pack_id / "face_detection_yunet_2023mar.onnx"
        return YuNetDetector(p, det_size)

    def build_embedder(self, model_dir):
        p = model_dir / self.descriptor.pack_id / "face_recognition_mobilefacenet_20221220_int8.onnx"
        return MobileFaceNetEmbedder(p)

    def build_aligner(self):
        return ArcFaceAligner()

    def download_to(self, target_dir, *, progress=None):
        import urllib.request
        target_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for url, fname in [(YUNET_URL, "face_detection_yunet_2023mar.onnx"),
                            (MFN_URL, "face_recognition_mobilefacenet_20221220_int8.onnx")]:
            dst = target_dir / fname
            with urllib.request.urlopen(url, timeout=60) as r:
                with dst.open("wb") as f:
                    f.write(r.read())
            out.append(dst)
        return out
```

完整可运行实现见 [src/pick_face/platform/packs/yunet_mfn.py](../src/pick_face/platform/packs/yunet_mfn.py)（内嵌在核心包用于 bootstrap）。

## 4. 发布到 PyPI

```bash
cd pick-face-modelpack-yunet
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uv build
uv publish   # 需 PyPI 凭据或 Trusted Publishing
```

安装（用户侧）：

```bash
uv pip install pick-face-modelpack-yunet

# 验证插件被发现
pick-face doctor
# 输出:
#   Installed model packs:
#     - yunet-sface    (MIT)              — arm-friendly, default
#     - yunet-arcface  (Apache-2.0)        — high-precision tier
#     - buffalo_l      (NC-research)      — opt-in only
```

## 5. LicenseClass 与 AC-9 联动

`PackDescriptor.license_class` 决定 pick-face 启动时是否 gate：

| LicenseClass | pick-face 启动行为 | toml 字段 |
|---|---|---|
| `PERMISSIVE` (Apache-2.0 / MIT / BSD-3) | 直接放行 | `accept_noncommercial_model_license` 不读 |
| `NC_RESEARCH` (InsightFace buffalo_*) | 必须 `accept_noncommercial_model_license = true`，否则 exit 2 | 该字段被读 |
| `USER_SUPPLIED` | 直接放行；report 顶部警告"verify your license" | 该字段不读 |

**插件作者必填**字段：`license_class` + `license_name` + `license_spdx` (SPDX id)。漏填 → `init-models` 报错。

## 6. SHA256 与完整性

`download_to()` 返回后，pick-face 自动跑 `verify_sha256()`：

```python
expected = descriptor.detector_sha256
if expected.startswith("<pin-on-first-build>"):
    # 首次构建占位符；CI 写入真 hash 后切掉
    warnings.warn(f"{label} SHA256 not pinned; skipping verification")
    return
# 否则计算并对比
```

**插件作者必须**：
1. 在第一次 CI build 后把真实 SHA256 填到 `descriptor`
2. **不**写"<TBD>"字面量（要写`<pin-on-first-build>`让脚本识别）

## 7. 兼容性矩阵

| pick-face 版本 | pack API 版本 |
|---|---|
| 1.x | 不支持 pack（必须装 `insightface` 直接跑） |
| **2.0+** | **pack API v1**（本文档定义） |
| 2.x | pack API v1（向后兼容） |
| 3.0+ | pack API v2（增加量化 / 增量 dist 字段） |

**插件作者**：把 `pick-face>=2.0,<3` 写进自己的 `[project] dependencies` 即可。

## 8. 已知 pack 列表

| Pack id | 厂商 | LicenseClass | 体积 | 推荐场景 |
|---|---|---|---|---|
| `yunet-sface` | OpenCV Zoo | PERMISSIVE (MIT) | ~10 MB | **默认**，ARM / Pi 3B / 树莓派 5 |
| `yunet-arcface` | ONNX Model Zoo | PERMISSIVE (Apache-2.0) | FP32 ~261 MB / INT8 ~66 MB | **高精度档**（同列 core，FP32 在 x86 + GPU；INT8 在 Pi 4/5） |
| `buffalo_l` | InsightFace | NC_RESEARCH | 325 MB | 个人/学术，x86 + GPU（opt-in 插件） |
| `buffalo_sc` | InsightFace | NC_RESEARCH | 35 MB | 个人/学术，ARM 上勉强（opt-in 插件） |
| `antelopev2` | InsightFace | NC_RESEARCH | 180 MB | 个人/学术 + GPU（opt-in 插件） |
| `scrfd-500m-mfn` | (M5 后) | PERMISSIVE | 35 MB | Pi 4B / x86 兼顾 |
| `my-arcface-r50` | 自训 | PERMISSIVE / NC (视训练数据) | 自定 | 商业首选 |

> **`yunet-arcface` 关键提示**：
> - 512-D embeddings，高精度场景；FP32 强烈推荐 x86 + GPU（CUDA / DirectML），INT8 在 ARM / 内存紧时降级。
> - 训练数据：refined MS-Celeb-1M；权重本身 Apache-2.0，训练数据 rights 由用户负责（见 [ONNX Model Zoo README](https://github.com/onnx/models/blob/main/validated/vision/body_analysis/arcface/README.md)）。
> - 在 `pick-face.toml` 中建议 `clustering.merge_threshold = 0.55`（512-D 余弦距离一档）。`yunet-sface` 仍用 0.0。
> - 切换：`pick-face init-models --pack yunet-arcface --quant {fp32,int8} --allow-network`。

## 9. 写自己 pack 的检查清单

发布前**必过**：

- [ ] `[project.entry-points."pick_face.model_packs"]` 至少 1 条，pack id 全小写、含 `-`
- [ ] `descriptor.license_class` / `license_name` / `license_spdx` 都填了
- [ ] `expected_files()` 列出所有权重文件名
- [ ] `build_detector` / `build_embedder` 在权重缺失时抛 `ModelNotFoundError`
- [ ] `download_to()` 后 SHA256 已 pin（不是 `<pin-on-first-build>` 占位符）
- [ ] 在 `tests/contract/test_pack_discovery.py` 注册了插件，能跑通 `discover_packs()`
- [ ] CI 跑通 `pick-face doctor`，确认插件被发现
- [ ] `pyproject.toml` 的 `requires-python` 与 pick-face 一致 (`>=3.10,<3.14`)
- [ ] `LICENSE` 文件在包根目录，SPDX id 与 `descriptor.license_spdx` 一致
- [ ] README 注明 pick-face 版本要求 + 安装命令 + 权重 license
- [ ] **不**在 wheel 里打包 `*.onnx`（CI 守卫 `tests/acceptance/test_no_model_in_distribution.py` 会拦）

## 10. CI / 兼容性测试

`tests/contract/test_pack_discovery.py`：

```python
def test_yunet_mfn_pack_registered():
    packs = discover_packs()
    assert "yunet-mfn" in packs
    p = packs["yunet-mfn"]
    assert p.descriptor.license_class is LicenseClass.PERMISSIVE
    assert "Apache-2.0" in p.descriptor.license_spdx
    # Smoke: detector + embedder instantiate against fake model_dir
    # (real weights tested in real_data marker)
```

## 11. 引用与延伸阅读

- [10 §2 model pack 总览](10-model-stack.md) — 各 pack 的精度 / 体积 / license
- [11 §3.2 启动强校验](11-commercial-compliance.md) — LicenseClass 与 AC-9 gate 的对应
- [13-raspberry-pi-support.md](13-raspberry-pi-support.md) — Pi 上跑 pack 的实操
- [src/pick_face/platform/pack.py](../src/pick_face/platform/pack.py) — Protocol 完整定义
- [src/pick_face/ingest/detector.py](../src/pick_face/ingest/detector.py) — Detector Protocol
- [src/pick_face/ingest/embedder.py](../src/pick_face/ingest/embedder.py) — Embedder Protocol
- Python entry-points — https://packaging.python.org/specifications/entry-points/
- OpenCV Zoo — https://github.com/opencv/opencv_zoo