"""Model management helpers: License Notice text + .license_ack emission.

Reference:
- docs/11 §3.2 (启动强校验: 默认 accept_noncommercial_model_license = false)
- docs/11 §3.3 (`init-models` 启动时打印的 License 提示全文)
- docs/11 §3.4 (报告顶部明记 Model+License)
- docs/11 §3.5 (镜像 model_index_url)

This module deliberately contains NO actual download logic — network
calls live behind `--allow-network` and are out of M1 scope (InsightFace
ships its own `insightface.model_zoo` downloader when invoked).
"""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pick_face.config import INSIGHTFACE_MODELS, PickFaceConfig

LICENSE_NOTICE = """\
═══════════════════════════════════════════════════════════════════════
  InsightFace buffalo_l — License Notice
═══════════════════════════════════════════════════════════════════════

You are about to download the InsightFace "{model}" model pack
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
    you are NOT permitted to use {model} under its license.

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
═══════════════════════════════════════════════════════════════════════\
"""


def license_notice_for(model_name: str) -> str:
    """Return the License Notice text for *model_name*. For non-InsightFace
    models we return a short 'no commercial restriction' notice — they
    are the user's responsibility to license."""
    if model_name in INSIGHTFACE_MODELS:
        return LICENSE_NOTICE.format(model=model_name)
    return (
        f"Model '{model_name}' is NOT shipped by pick-face. You are responsible\n"
        f"for ensuring you have the right to use it. pick-face will not attempt\n"
        f"to download it; point `[runtime].model_dir` at your weights and proceed.\n"
    )


def is_insightface_model(model_name: str) -> bool:
    return model_name in INSIGHTFACE_MODELS


def write_license_ack(model_dir: Path, model_name: str, *, acked_by: str | None = None) -> Path:
    """Write `.license_ack` next to the model weights so the audit trail
    is preserved on disk (docs/11 §3.4 / §3.5). Returns the file path."""
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    target = model_dir / ".license_ack"
    payload = {
        "model": model_name,
        "license": (
            "InsightFace non-commercial-research"
            if is_insightface_model(model_name)
            else "custom (user-supplied; see upstream license)"
        ),
        "ack_text": license_notice_for(model_name),
        "acked_at": datetime.now(tz=timezone.utc).isoformat(),
        "acked_by": acked_by or _best_user(),
        "host": os.uname().nodename
        if hasattr(os, "uname")
        else os.environ.get("COMPUTERNAME", "?"),
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def read_license_ack(model_dir: Path) -> dict | None:
    """Read back the .license_ack file (if any) for reporting."""
    p = Path(model_dir) / ".license_ack"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _best_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def license_ack_summary(cfg: PickFaceConfig) -> str | None:
    """One-line human-readable summary used by report.md and preflight logs.

    Returns None if there's no .license_ack on disk (yet)."""
    ack = read_license_ack(cfg.runtime.model_dir / cfg.runtime.model_name)
    if ack is None:
        return None
    return (
        f"user {ack['acked_by']!r} on {ack['acked_at'][:10]} "
        f"(see `.cache/{cfg.runtime.model_name}/.license_ack`)"
    )
