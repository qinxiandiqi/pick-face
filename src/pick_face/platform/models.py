"""Model management helpers: License Notice text + .license_ack emission.

Reference:
- docs/11 §3.2 (启动强校验: 默认 accept_noncommercial_model_license = false)
- docs/11 §3.3 (`init-models` 启动时打印的 License 提示全文)
- docs/11 §3.4 (报告顶部明记 Model+License)
- docs/11 §3.5 (镜像 model_index_url)
- docs/14 §2 (ModelPack Protocol — license_class drives the notice text)

Route B: the notice text is driven by the ``PackDescriptor.license_class``
of the installed pack, not by a hardcoded model-name set. The
``is_insightface_model()`` shim is kept as a backward-compat alias so
v1.x call-sites that imported it keep working until v3.0.
"""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pick_face.core.config import PickFaceConfig
from pick_face.platform.pack import LicenseClass, discover_packs

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


# Pack ids the v1.x line classified as InsightFace NC-research. Kept
# here so we can still render the legacy notice when an installed pack
# reports LicenseClass.NC_RESEARCH but no custom notice_text.
_LEGACY_INSIGHTFACE_PACK_IDS: frozenset[str] = frozenset(
    {"buffalo_l", "buffalo_sc", "antelopev2", "buffalo_m"}
)


def license_notice_for(model_name: str) -> str:
    """Return the License Notice text for *model_name*.

    Resolution order (route B):
      1. If *model_name* matches an installed pack, defer to
         ``PackDescriptor.license_notice_text`` (NC packs) or emit a
         one-liner reminder (PERMISSIVE / USER_SUPPLIED).
      2. Fall back to the v1.x InsightFace notice when *model_name* is
         one of the legacy NC ids (so v1.x configs still print the
         correct text before any pack plugin is installed).
    """
    try:
        packs = discover_packs()
    except Exception:
        packs = {}
    if model_name in packs:
        pack = packs[model_name]
        cls = pack.descriptor.license_class
        if cls is LicenseClass.NC_RESEARCH:
            if pack.descriptor.license_notice_text:
                return pack.descriptor.license_notice_text
            if model_name in _LEGACY_INSIGHTFACE_PACK_IDS:
                return LICENSE_NOTICE.format(model=model_name)
            return (
                f"Model pack '{model_name}' is {pack.descriptor.license_name}.\n"
                f"Non-commercial-research only. See {pack.descriptor.license_spdx}."
            )
        if cls is LicenseClass.PERMISSIVE:
            return (
                f"Model pack '{model_name}' is {pack.descriptor.license_name} — "
                f"no commercial restriction. Downloads: ~{pack.descriptor.detector_size_bytes + pack.descriptor.embedder_size_bytes} bytes."
            )
        # USER_SUPPLIED
        return (
            f"Model pack '{model_name}' is user-supplied. You are responsible\n"
            f"for licensing the weights yourself; pick-face will not gate, but\n"
            f"the audit report will warn.\n"
        )
    if model_name in _LEGACY_INSIGHTFACE_PACK_IDS:
        return LICENSE_NOTICE.format(model=model_name)
    return (
        f"Model '{model_name}' is NOT shipped by pick-face. You are responsible\n"
        f"for ensuring you have the right to use it. pick-face will not attempt\n"
        f"to download it; point `[runtime].model_dir` at your weights and proceed.\n"
    )


def is_insightface_model(model_name: str) -> bool:
    """Backward-compat alias — prefer ``PackDescriptor.license_class``.

    True iff *model_name* is one of the legacy InsightFace NC-research
    pack ids. Replaced in route B by the LicenseClass check; kept here
    so v1.x importers keep working through v2.x.
    """
    return model_name in _LEGACY_INSIGHTFACE_PACK_IDS


def write_license_ack(model_dir: Path, model_name: str, *, acked_by: str | None = None) -> Path:
    """Write `.license_ack` next to the model weights so the audit trail
    is preserved on disk (docs/11 §3.4 / §3.5). Returns the file path.

    Route B: license label comes from the installed pack descriptor; if
    none is installed yet, we fall back to the legacy
    "InsightFace non-commercial-research" string.
    """
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    target = model_dir / ".license_ack"

    try:
        packs = discover_packs()
    except Exception:
        packs = {}
    if model_name in packs:
        pack = packs[model_name]
        license_label = pack.descriptor.license_name
    elif model_name in _LEGACY_INSIGHTFACE_PACK_IDS:
        license_label = "InsightFace non-commercial-research"
    else:
        license_label = "custom (user-supplied; see upstream license)"

    payload = {
        "model": model_name,
        "license": license_label,
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

    Returns None if there's no .license_ack on disk (yet). Pack-aware in
    route B: looks under ``model_dir/<pack_id>/`` rather than
    ``model_dir/<model_name>/``.
    """
    pack_id = cfg.runtime.effective_pack_id()
    ack = read_license_ack(cfg.runtime.model_dir / pack_id)
    if ack is None:
        return None
    return (
        f"user {ack['acked_by']!r} on {ack['acked_at'][:10]} "
        f"(see `{cfg.runtime.model_dir}/{pack_id}/.license_ack`)"
    )
