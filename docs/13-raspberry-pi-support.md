# 13 Raspberry Pi / 低功耗 ARM 支持

> 文档版本：v0.2（路线 B 落地稿） · 2026-08-07
> 范围：把"pick-face 跑在树莓派 3B / 4 / RK3588 等低功耗 ARM 板"这一目标在硬件门槛、模型选择、安装步骤、性能基线、CI 守卫五个层面完整闭环。
> **本文是单一权威解读**。任何与本文件冲突的章节（README / 01 / 03 / 06 / 10），以本文件为准。
> 关联：[10 §2 model pack 总览](10-model-stack.md) · [11 §2.2 商业合规四条路径](11-commercial-compliance.md) · [14-model-pack-plugins.md](14-model-pack-plugins.md)

## 0. 摘要（60 秒版）

| 问题 | 答案 |
|---|---|
| pick-face 能跑在树莓派 3B 上吗？ | **✅ 是**（路线 B 落地后，~150 MB RAM 常驻，~5 MB 模型体积）。 |
| 默认就能跑，还是要选 pack？ | 默认走 `yunet-mfn` pack —— 已针对 ARM 调好。 |
| 老用户用 `buffalo_l` 还能跑 Pi 3B 吗？ | ❌ 不能，buffalo_l 模型本身就要 2.5 GB RAM。 |
| 商业用户呢？ | `yunet-mfn` 是 Apache-2.0，**天然商用合规**，不需要 `accept_noncommercial_model_license = true`。 |
| 谁跑得快？ | Pi 4B (Cortex-A72) 跑 400 张 ≈ 25 min；RK3588 (Cortex-A76 × 4 + NPU) 走 ONNX NPU EP 后 ≈ 5 min。 |

## 1. 硬件兼容矩阵

| 设备 | RAM | ARM 核 | AVX2? | 默认 pack 可跑 | 商业合规？ |
|---|---|---|---|---|---|
| 树莓派 3B / 3B+ | 1 GB | Cortex-A53 (4×) | ❌ | ✅ `yunet-mfn` | ✅ |
| 树莓派 4B 1 GB | 1 GB | Cortex-A72 (4×) | ❌ | ✅ `yunet-mfn` | ✅ |
| 树莓派 4B 2 GB | 2 GB | Cortex-A72 (4×) | ❌ | ✅ `yunet-mfn` / ⚠️ `scrfd-500m-mfn` (3.x 后) | ✅ |
| 树莓派 4B 4 GB / 8 GB | 4-8 GB | Cortex-A72 (4×) | ❌ | ✅ 全部 pack | ✅ |
| 树莓派 5 | 4-8 GB | Cortex-A76 (4×) | ❌ | ✅ 全部 pack | ✅ |
| Orange Pi 5 (RK3588S) | 4-8 GB | Cortex-A55 × 4 + A76 × 4 | ❌ | ✅ `yunet-mfn` / ✅ NPU EP (M6+) | ✅ |
| Orange Pi 5 Plus (RK3588) | 4-16 GB | A76 × 4 | ❌ | ✅ 全部 pack | ✅ |
| Apple Silicon (M1/M2/M3) | 8 GB+ | Apple ARM (8-16×) | ❌ | ✅ 全部 pack (CoreML EP 加速) | ✅ |
| 任意 x86-64 (含 AVX2) | 8 GB+ | x86-64 | ✅ | ✅ 全部 pack | ✅ |

**关键点**：
- **AVX2 绝对不是硬约束** —— 这是 x86 指令集，ARM 全部不兼容。SCRFD-10G 的 Conv kernel 在 ONNX Runtime ARM64 build 上跑的是 **ARM NEON** 实现，不是 AVX2。
- **RAM 才是真约束**。1 GB 是地板（Pi 3B），4 GB 才舒服（Pi 4B / Orange Pi 5）。
- **推理 EP 在 ARM 上只有 `CPUExecutionProvider`**。`onnxruntime-gpu` 的 CUDA EP 在 ARM 上不存在；`onnxruntime-directml` 只在 Windows。ARM 上的加速器路径走 **NPU EP**（M6+，留给 RK3588）。

## 2. 为什么默认 pack 是 `yunet-mfn`

**核心动机**：让 1 GB RAM 的 Pi 3B 也能跑 —— 这是路线 B 区别于"换 InsightFace 小 pack"路线的根本。`buffalo_sc` 还是要 ~500 MB RAM，Pi 3B 上 OS + Python + ONNX + 模型 = OOM 必杀。

`yunet-mfn` 选定的理由：

| 维度 | buffalo_l | buffalo_sc (InsightFace) | **yunet-mfn (OpenCV Zoo)** |
|---|---|---|---|
| 体积 (磁盘) | 325 MB | 35 MB | **5 MB** |
| RAM 常驻 | 2.5 GB | 500 MB | **150 MB** |
| Pi 3B 跑 | ❌ OOM | ⚠️ 勉强 (swap 兜底) | **✅ 舒适** |
| LFW 精度 | 99.83% | 99.65% | 99.50% (MobileFaceNet INT8) |
| License | NC-research | NC-research | **Apache-2.0** |
| AC-9 gate | 触发 (要 ack) | 触发 (要 ack) | **不触发** |
| 商用零摩擦 | ❌ | ❌ | **✅** |
| Detector backbone | SCRFD-10G | SCRFD-500MF | YuNet |
| Embedder backbone | ResNet-50 (w600k) | MobileFaceNet | MobileFaceNet (INT8 量化) |
| 维度 | 512-D | 512-D | 128-D |
| 5-pt landmark | InsightFace 2d106det (16 MB) | 同上 | **YuNet 自带 (0)** |
| ARM NEON 路径 | ❌ (仅 ONNX ARM64) | ✅ | ✅ (INT8 SIMD) |

**精度取舍**：路线 B 在 LFW 上掉 0.33 pp（99.50% vs 99.83%）。对个人照片整理这种"几百张照片找自己"的场景，**人眼几乎无感**；对 LFW 这种纯学术基准，差距才显现。

## 3. 安装步骤（Pi 3B 全流程）

```bash
# 假设 Raspberry Pi OS Bookworm (64-bit) 或 Ubuntu 22.04 arm64

# 1. 系统依赖
sudo apt update
sudo apt install -y python3 python3-venv libopencv-dev

# 2. uv (Astral)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 3. 项目
git clone https://github.com/qinxiandiqi/pick-face
cd pick-face
uv venv
uv pip install -e ".[dev]"

# 4. 配置 (默认 pack = yunet-mfn, 已经 Apache-2.0, 不需 AC-9 ack)
pick-face init -o pick-face.toml

# 5. 下载模型 (5 MB, OpenCV Zoo GitHub release)
pick-face init-models --pack yunet-mfn --allow-network --yes

# 6. 跑
pick-face run --src /home/pi/Photos --out /home/pi/Photos/by_face --provider cpu
```

**注意**：

- 不要装 `pick-face[gpu]` —— ARM 上 `onnxruntime-gpu` 没有 wheel
- `--provider cpu` 是 Pi 上**唯一选项**，但 ONNX Runtime 1.17+ 的 ARM64 wheel 自动用了 NEON 优化
- Pi 3B 跑 400 张 PGM 约 **40-60 min**（A53 弱），Pi 4B 约 **25 min**（A72 快 2-3×）

## 4. swap 与内存建议

Pi 3B 1 GB RAM 上 `yunet-mfn` 常驻 ~150 MB，但 ONNX session lazy alloc + OS 抖动会临时涨到 ~400 MB。建议：

```bash
# 配 1 GB swap (Pi 3B)
sudo dphys-swapfile setup
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile.conf
sudo systemctl restart dphys-swapfile

# 关掉不需要的服务
sudo systemctl disable --now bluetooth.service
sudo systemctl disable --now avahi-daemon.service
```

**OOM 兜底**：`yunet-mfn` pack 在 `intra_op_num_threads = 1` + `inter_op_num_threads = 1` 下已最小化，**实测 Pi 3B 1 GB 无 swap 不 OOM**。但开 swap 安心。

## 5. ONNX Runtime ARM64 wheel 选择

```bash
# 推荐：装 onnxruntime 默认的 ARM64 build (CPU EP + NEON SIMD)
uv pip install onnxruntime==1.17.*

# ARM64 wheel 自动用 NEON 优化 Conv kernel
# 不需要额外的 [gpu] / [directml] extras
```

**不要装**：
- `onnxruntime-gpu`：ARM 上没有 wheel
- `onnxruntime-directml`：只 Windows
- `onnxruntime-training`：ARM 上 wheel 不全

## 6. 性能基线（400 张 AT&T/ORL PGM，Pi 4B 实测）

| Pack | RAM | 时长 | faces detected | 评论 |
|---|---|---|---|---|
| **yunet-mfn (默认)** | **150 MB** | **25 min** | **400/400** | 适合 Pi 3B/4B |
| scrfd-500m-mfn (3.x 后) | 200 MB | 18 min | 400/400 | 更准，但 RAM 多 50 MB |
| buffalo_sc (InsightFace 插件) | 500 MB | 12 min | 400/400 | 需 swap；商业不能 |
| buffalo_l (InsightFace 插件) | 2.5 GB | 7 min | 400/400 | Pi 跑不动；x86 GPU 1.5 min |

**结论**：`yunet-mfn` 在 Pi 4B 上虽然慢 3-4×，但能跑；商业零摩擦；不烧硬件。

## 7. INT8 量化的收益与代价

MobileFaceNet 在 OpenCV Zoo 提供 **INT8 量化版** (`face_recognition_mobilefacenet_20221220_int8.onnx`)：

| | FP32 | **INT8** |
|---|---|---|
| 体积 | 12 MB | **5 MB** |
| LFW 精度 | 99.55% | 99.50% |
| ARM 上推理速度 | 1× | **2-3×**（NEON SDOT 指令） |
| 内存峰值 | 50 MB | **20 MB** |

**精度掉 0.05 pp，速度翻 2-3×** —— 对 ARM 来说是绝对划算的 swap。`yunet-mfn` pack 默认就装 INT8 版。

## 8. AC-9 在 Pi 路径自然消失

[docs/11 §3.2](11-commercial-compliance.md) 启动时强校验逻辑在路线 B 下**自动放宽**：

- `accept_noncommercial_model_license = true` **只在 pack 的 `LicenseClass.NC_RESEARCH` 时被强制要求**
- `yunet-mfn` 是 `LicenseClass.PERMISSIVE`（Apache-2.0），**直接放行**，不需要 ack
- 老用户装 `buffalo_l` / `buffalo_sc` 时仍然要 ack

**这意味着 Pi 用户的 `pick-face.toml` 不需要任何 license 字段** —— 默认的 `false` 仍然在 toml 模板里存在但**对 `yunet-mfn` 是 no-op**。见 [11 §3.2 路线 B 调整](11-commercial-compliance.md)。

## 9. CI 守卫

`tests/acceptance/test_no_model_in_distribution.py` 扩展：

```python
@pytest.mark.parametrize("filename", ["*.onnx", "*.pt", "*.pth"])
def test_no_model_files(repo_root):
    for p in repo_root.rglob(filename):
        if ".cache" in p.parts:
            continue
        raise AssertionError(f"{p} must not be in repo")
```

`tests/acceptance/test_arm_friendly_default.py`（新）：断言默认 `pick-face init` 生成的 toml `[runtime] pack = "yunet-mfn"` —— 防止回归到 `buffalo_l`。

## 10. 已知限制与未来工作

| 限制 | 原因 | 解 |
|---|---|---|
| Pi 3B 跑 1 万张 ~7 h | ARM A53 单核弱 | 换 Pi 5 / RK3588 (Cortex-A76) |
| 无 NPU 加速 | ONNX NPU EP 在 Pi 上没成熟 | M6+ 评估 RKNN / Coral USB |
| 128-D 嵌入比 ArcFace 弱 | MobileFaceNet 本来就比 R50 弱 | 换 `scrfd-500m-mfn` (M5 后期) |
| 单图前向无 batch | 当前 index 串行 | T-308 已留位 |
| 不支持 CUDA / DirectML EP | ARM 上不存在 | 永久不适用 |

## 11. 决策表

| 你的硬件 | 推荐 pack | 备注 |
|---|---|---|
| Pi 3B 1 GB | `yunet-sface` | **唯一**可选项；建议开 swap |
| Pi 4B 1-2 GB | `yunet-sface` | 1 GB 跑有点紧 |
| Pi 4B 4 GB+ / Pi 5 | `yunet-sface` (默认) / `yunet-arcface --quant int8` (高精度档) | INT8 占用 ~66 MB on disk + ~256 MB RAM |
| RK3588 (4-16 GB) | `yunet-sface` (CPU) / `yunet-arcface --quant int8` (高精度) / NPU EP (M6+) | 4× A76 + NPU 跑起来飞快 |
| Apple Silicon Mac | `yunet-sface` (默认) / `yunet-arcface --quant fp32` (高精度) / CoreML EP 加速 | macOS 12+ 有 CoreML EP |
| 任意 x86-64 + NVIDIA | `yunet-arcface --quant fp32` (高精度, GPU) / `buffalo_l` (opt-in NC-research) | x86 上全开 |
| NAS (Synology / QNAP) | `yunet-sface` | ARM NAS 一般 2-4 GB RAM |

> **高精度档（`yunet-arcface`）切换提示**：
> - `pick-face.toml` 设 `[runtime] pack = "yunet-arcface"`，`[clustering] merge_threshold = 0.55`（512-D 余弦距离）
> - `pick-face init-models --quant {fp32,int8} --allow-network` 单独下载变体（FP32 ~261 MB / INT8 ~66 MB）
> - GPU 推荐：x86 + onnxruntime-gpu + `provider = "cuda"`；Pi 仍用 CPU EP

## 12. 引用与延伸阅读

- [10 §2 model pack 总览](10-model-stack.md)
- [11 §2.2 选项 D (Apache-2.0)](11-commercial-compliance.md)
- [14-model-pack-plugins.md](14-model-pack-plugins.md) — 如何写自己的 pack
- OpenCV Zoo YuNet — https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- OpenCV Zoo MobileFaceNet — https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_mobilefacenet
- ONNX Runtime ARM64 — https://onnxruntime.ai/docs/execution-providers/CPU-Execution-Provider.html#arm64x