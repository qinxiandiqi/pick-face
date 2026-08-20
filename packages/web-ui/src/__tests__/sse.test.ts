// SSE schema round-trip tests.
//
// Two streams are covered here:
//
//   1. Per-job stream  — `/api/scan/jobs/{id}/events` (M8-T-8):
//      ``new_photo`` / ``new_person`` / ``merged`` / ``progress``.
//
//   2. Global stream  — `/api/scan/events` (SSE-driven banner):
//      ``snapshot`` / ``job_update`` payloads shaped like ``ScanJob``.
//
// We exercise the zod schemas directly with sample payloads that match
// what the backend writes. If the backend shape changes, these tests
// should fail loudly so we update both sides in lockstep.

import { describe, expect, it } from "vitest";

import {
  ScanJobSchema,
  ScanMergedEventSchema,
  ScanNewPersonEventSchema,
  ScanNewPhotoEventSchema,
  ScanProgressEventSchema,
} from "@/lib/api/schemas";

describe("sse event schemas (M8-T-8)", () => {
  it("ScanNewPhotoEventSchema accepts a valid new_photo payload", () => {
    const ok = ScanNewPhotoEventSchema.safeParse({
      photo_id: 17,
      face_count: 2,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.photo_id).toBe(17);
      expect(ok.data.face_count).toBe(2);
    }
  });

  it("ScanNewPhotoEventSchema rejects face_count < 0", () => {
    const bad = ScanNewPhotoEventSchema.safeParse({
      photo_id: 1,
      face_count: -1,
    });
    expect(bad.success).toBe(false);
  });

  it("ScanNewPersonEventSchema accepts a valid new_person payload", () => {
    const ok = ScanNewPersonEventSchema.safeParse({
      cluster_id: 42,
      label: "person-0042",
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.cluster_id).toBe(42);
      expect(ok.data.label).toBe("person-0042");
    }
  });

  it("ScanMergedEventSchema accepts a valid merged payload", () => {
    const ok = ScanMergedEventSchema.safeParse({
      cluster_id: 10,
      into_cluster_id: 5,
      face_count: 3,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.cluster_id).toBe(10);
      expect(ok.data.into_cluster_id).toBe(5);
      expect(ok.data.face_count).toBe(3);
    }
  });

  it("ScanProgressEventSchema accepts a valid progress payload", () => {
    const ok = ScanProgressEventSchema.safeParse({
      job_id: "abc-123",
      state: "running",
      processed: 10,
      total: 20,
      faces: 7,
      errors: 0,
    });
    expect(ok.success).toBe(true);
  });
});

describe("global scan-event stream payload (ScanJobSchema)", () => {
  it("accepts a fully-populated snapshot with eta_sec", () => {
    const ok = ScanJobSchema.nullable().safeParse({
      id: "abc-123",
      kind: "full",
      state: "running",
      paths: ["/tmp/photos"],
      started_at: "2026-08-20T10:00:00+00:00",
      ended_at: null,
      progress: { processed: 5, total: 10, faces: 3, errors: 0, eta_sec: 42 },
      error: null,
    });
    expect(ok.success).toBe(true);
    if (ok.success && ok.data) {
      expect(ok.data.progress.eta_sec).toBe(42);
      expect(ok.data.kind).toBe("full");
    }
  });

  it("accepts a snapshot where eta_sec is null", () => {
    const ok = ScanJobSchema.nullable().safeParse({
      id: "abc-123",
      kind: "incremental",
      state: "running",
      paths: [],
      started_at: null,
      ended_at: null,
      progress: { processed: 0, total: 0, faces: 0, errors: 0, eta_sec: null },
      error: null,
    });
    expect(ok.success).toBe(true);
  });

  it("accepts a null snapshot (no active job)", () => {
    const ok = ScanJobSchema.nullable().safeParse(null);
    expect(ok.success).toBe(true);
    expect(ok.data).toBeNull();
  });

  it("accepts an FAILED terminal snapshot with error message", () => {
    const ok = ScanJobSchema.nullable().safeParse({
      id: "deadbeef",
      kind: "incremental",
      state: "failed",
      paths: ["/tmp/photos"],
      started_at: "2026-08-20T10:00:00+00:00",
      ended_at: "2026-08-20T10:00:05+00:00",
      progress: { processed: 2, total: 10, faces: 1, errors: 1, eta_sec: null },
      error: "decoder crashed",
    });
    expect(ok.success).toBe(true);
    if (ok.success && ok.data) {
      expect(ok.data.state).toBe("failed");
      expect(ok.data.error).toBe("decoder crashed");
    }
  });
});