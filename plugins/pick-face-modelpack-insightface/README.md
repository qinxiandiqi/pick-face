# pick-face-modelpack-insightface

InsightFace `buffalo_l` / `buffalo_sc` / `antelopev2` ModelPack plugin
for [pick-face](https://github.com/qinxiandiqi/pick-face).

> ⚠ **License**: the *code* in this package is MIT, but the **weights**
> downloaded by `pick-face init-models --pack buffalo_l` are under
> [InsightFace's non-commercial-research terms](https://github.com/deepinsight/insightface/blob/master/LICENSE).
> Installing this plugin does not grant you any commercial rights to
> those weights. See
> [docs/11-commercial-compliance.md](https://github.com/qinxiandiqi/pick-face/blob/main/docs/11-commercial-compliance.md)
> for the four legal paths to commercial deployment.

## Install

```bash
uv pip install pick-face-modelpack-insightface
```

This installs alongside `pick-face>=2.0` (no need to uninstall the
default `yunet-mfn` pack — you can pick either one via
`[runtime].pack` in `pick-face.toml`).

## Use

```bash
# 1. Acknowledge the license in your config.
cat >> pick-face.toml <<'EOF'
[runtime]
pack = "buffalo_l"
accept_noncommercial_model_license = true
EOF

# 2. Download the weights (one-shot).
pick-face init-models --pack buffalo_l --allow-network --yes

# 3. Run normally.
pick-face run --src ~/Photos --out ~/Photos/by_face
```

## Switching back to the Apache-2.0 default

```toml
[runtime]
pack = "yunet-mfn"   # no ack required
```