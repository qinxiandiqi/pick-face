"""pick-face: local offline image face recognition & organization CLI.

The package is split into 5 domain sub-packages:

  pick_face.core      — config, errors, hashing, images, paths (lowest)
  pick_face.ingest    — scanner, detector, embedder, align, cluster
  pick_face.store     — index (SQLite), index_hnsw, checkpoint, review
  pick_face.output    — linker, mirrors, reporter, parallel
  pick_face.platform  — runtime (provider probe), models, bench

Refer to docs/AGENTS.md for the full documentation index and
docs/11-commercial-compliance.md for commercial deployment compliance.
"""

__version__ = "3.0.0.dev0"
__license__ = "Apache-2.0"

from pick_face.core.config import (  # noqa: E402, F401
    ClusteringConfig,
    DetectionConfig,
    LinkConfig,
    PickFaceConfig,
    RuntimeConfig,
    load_config,
    write_default_config,
)
from pick_face.core.errors import (  # noqa: E402, F401
    EXIT_CONFIG,
    EXIT_INTERRUPTED,
    EXIT_MODEL,
    EXIT_OK,
    EXIT_PIPELINE,
    CliArgError,
    CommercialLicenseError,
    ConfigError,
    FaceError,
    ImageDecodeError,
    InterruptedError,
    ModelLoadError,
    ModelNotFoundError,
    OutputNotWritableError,
    PickFaceError,
    PipelineFailureError,
    SourceNotFoundError,
)
from pick_face.core.hashing import (  # noqa: E402, F401
    HASH_ALGO,
    HASH_HEX_LEN,
    HASH_PREFIX_BYTES,
    content_hash,
    content_hash_bytes,
    file_id,
)
from pick_face.core.images import (  # noqa: E402, F401
    MAX_LONG_EDGE,
    DecodedImage,
    decode,
)
from pick_face.core.paths import (  # noqa: E402, F401
    APP_AUTHOR,
    APP_NAME,
    default_data_dir,
    default_model_dir,
    ensure_dir,
)
from pick_face.ingest.align import (  # noqa: E402, F401
    estimate_similarity_transform,
    warp_affine_batch,
    warp_to_112,
)
from pick_face.ingest.cluster import (  # noqa: E402, F401
    ClusterResult,
    Constraint,
    ReviewLink,
    cluster_embeddings,
    face_to_cluster_similarity,
    incremental_assign,
)
from pick_face.ingest.detector import (  # noqa: E402, F401
    Detection,
    detection_from_insightface,
)
from pick_face.ingest.embedder import (  # noqa: E402, F401
    Embedder,
    cosine_distance_matrix,
    l2_normalize,
)
from pick_face.ingest.scanner import (  # noqa: E402, F401
    DEFAULT_IMAGE_EXTS,
    DiffKind,
    ScanRow,
    ScanStats,
    iter_candidate_files,
    scan,
)
from pick_face.output.linker import (  # noqa: E402, F401
    LinkResult,
    link_or_copy,
    staging_rename_atomic,
    unlink_safely,
)
from pick_face.output.mirrors import (  # noqa: E402, F401
    INDEX_SCHEMA,
    META_SCHEMA,
    write_all_cluster_metas,
    write_cluster_meta,
    write_index_json,
)
from pick_face.output.parallel import run_pool  # noqa: E402, F401
from pick_face.output.reporter import (  # noqa: E402, F401
    ReportStats,
    collect_low_confidence_faces,
    collect_stats,
    render_html,
    render_json,
    render_markdown,
    write_low_confidence_json,
    write_report,
)
from pick_face.platform.bench import (  # noqa: E402, F401
    BenchResult,
    run_benchmark,
)
from pick_face.platform.models import (  # noqa: E402, F401
    LICENSE_NOTICE,
    is_insightface_model,
    license_ack_summary,
    license_notice_for,
    read_license_ack,
    write_license_ack,
)
from pick_face.platform.pack import (  # noqa: E402, F401
    LicenseClass,
    ModelPack,
    PackDescriptor,
    discover_packs,
    get_pack,
    require_compliance,
    valid_pack_id,
)
from pick_face.platform.runtime import (  # noqa: E402, F401
    PackRunner,
    check_commercial,
    describe_provider_chain,
    load_insightface_runner,
    load_pack_runner,
    resolve_providers,
)
from pick_face.store.checkpoint import (  # noqa: E402, F401
    CHECKPOINT_FILENAME,
    checkpoint_path,
    clear_checkpoint,
    load_checkpoint,
    resume_offset,
    save_checkpoint,
    update_checkpoint,
)
from pick_face.store.checkpoint import (  # noqa: E402, F401
    SCHEMA as CHECKPOINT_SCHEMA,
)
from pick_face.store.index import (  # noqa: E402, F401
    SCHEMA_VERSION,
    open_db,
)
from pick_face.store.index_hnsw import (  # noqa: E402, F401
    BACKEND_HNSWLIB,
    BACKEND_NUMPY,
    MAGIC,
    METRIC_COSINE,
    METRIC_L2,
    HnswIndex,
)
from pick_face.store.index_hnsw import (  # noqa: E402, F401
    rebuild as rebuild_hnsw,
)
from pick_face.store.review import (  # noqa: E402, F401
    ReviewDecision,
    apply_decisions,
    load_decisions,
)

__all__ = [
    "__version__",
    "__license__",
    # core/config
    "ClusteringConfig",
    "DetectionConfig",
    "LinkConfig",
    "PickFaceConfig",
    "RuntimeConfig",
    "load_config",
    "write_default_config",
    # core/errors
    "CliArgError",
    "CommercialLicenseError",
    "ConfigError",
    "EXIT_CONFIG",
    "EXIT_INTERRUPTED",
    "EXIT_MODEL",
    "EXIT_OK",
    "EXIT_PIPELINE",
    "FaceError",
    "ImageDecodeError",
    "InterruptedError",
    "ModelLoadError",
    "ModelNotFoundError",
    "OutputNotWritableError",
    "PickFaceError",
    "PipelineFailureError",
    "SourceNotFoundError",
    # core/hashing
    "HASH_ALGO",
    "HASH_HEX_LEN",
    "HASH_PREFIX_BYTES",
    "content_hash",
    "content_hash_bytes",
    "file_id",
    # core/images
    "MAX_LONG_EDGE",
    "DecodedImage",
    "decode",
    # core/paths
    "APP_AUTHOR",
    "APP_NAME",
    "default_data_dir",
    "default_model_dir",
    "ensure_dir",
    # ingest/align
    "estimate_similarity_transform",
    "warp_affine_batch",
    "warp_to_112",
    # ingest/cluster
    "ClusterResult",
    "Constraint",
    "ReviewLink",
    "cluster_embeddings",
    "face_to_cluster_similarity",
    "incremental_assign",
    # ingest/detector
    "Detection",
    "detection_from_insightface",
    # ingest/embedder
    "Embedder",
    "cosine_distance_matrix",
    "l2_normalize",
    # ingest/scanner
    "DEFAULT_IMAGE_EXTS",
    "DiffKind",
    "ScanRow",
    "ScanStats",
    "iter_candidate_files",
    "scan",
    # store/checkpoint
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_SCHEMA",
    "checkpoint_path",
    "clear_checkpoint",
    "load_checkpoint",
    "resume_offset",
    "save_checkpoint",
    "update_checkpoint",
    # store/index
    "SCHEMA_VERSION",
    "open_db",
    # store/index_hnsw
    "BACKEND_HNSWLIB",
    "BACKEND_NUMPY",
    "MAGIC",
    "METRIC_COSINE",
    "METRIC_L2",
    "HnswIndex",
    "rebuild_hnsw",
    # store/review
    "ReviewDecision",
    "apply_decisions",
    "load_decisions",
    # output/linker
    "LinkResult",
    "link_or_copy",
    "staging_rename_atomic",
    "unlink_safely",
    # output/mirrors
    "INDEX_SCHEMA",
    "META_SCHEMA",
    "write_all_cluster_metas",
    "write_cluster_meta",
    "write_index_json",
    # output/parallel
    "run_pool",
    # output/reporter
    "ReportStats",
    "collect_low_confidence_faces",
    "collect_stats",
    "render_html",
    "render_json",
    "render_markdown",
    "write_low_confidence_json",
    "write_report",
    # platform/bench
    "BenchResult",
    "run_benchmark",
    # platform/models
    "LICENSE_NOTICE",
    "is_insightface_model",
    "license_ack_summary",
    "license_notice_for",
    "read_license_ack",
    "write_license_ack",
    # platform/pack (route B)
    "LicenseClass",
    "ModelPack",
    "PackDescriptor",
    "discover_packs",
    "get_pack",
    "require_compliance",
    "valid_pack_id",
    # platform/runtime
    "PackRunner",
    "check_commercial",
    "describe_provider_chain",
    "load_insightface_runner",
    "load_pack_runner",
    "resolve_providers",
]
