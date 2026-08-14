// SSE schema round-trip tests (M8-T-8).
//
// The frontend subscribes to `/api/scan/jobs/{id}/events` via
// `openScanEventStream` (lib/sse.ts). The backend appends JSONL
// records to `scan-{id}.events.jsonl` and the SSE generator emits
// them as `event: <type>` + `data: <json>`.
//
// We exercise the zod schema directly with sample payloads that match
// what the backend writes. If the backend shape changes, these tests
// should fail loudly so we update both sides in lockstep.

import { describe, expect, it } from "vitest";

import {
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
      state: "RUNNING",
      processed: 10,
      total: 20,
      faces: 7,
      errors: 0,
    });
    expect(ok.success).toBe(true);
  });
});