"""InsightFace ModelPack plugin for pick-face (route B, opt-in NC-research).

This package is **separate** from `pick-face` core. It exists so that
core stays Apache-2.0 + dependency-light, and so users who don't want
the InsightFace NC-research license terms can ship without this plugin
installed.

Install:
    uv pip install pick-face-modelpack-insightface

Use:
    # pick-face.toml
    [runtime]
    pack = "buffalo_l"
    accept_noncommercial_model_license = true

    pick-face init-models --pack buffalo_l --allow-network --yes
    pick-face run --src ~/Photos --out ~/Photos/by_face

The weights themselves are NC-research (InsightFace's license). The
*code* in this package is MIT. See docs/11-commercial-compliance.md.
"""

from pick_face_modelpack_insightface.pack import (
    AntelopeV2Pack,
    BuffaloLPack,
    BuffaloScPack,
)

__version__ = "0.1.0"
__all__ = ["AntelopeV2Pack", "BuffaloLPack", "BuffaloScPack"]
