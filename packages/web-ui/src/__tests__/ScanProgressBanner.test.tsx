// ScanProgressBanner — shows when there's an active scan job.
// We mock the hooks the banner consumes (`useActiveScanJobStream`
// and `usePersonsLiveInvalidator`) so we can drive the job state
// deterministically without standing up an SSE stream in jsdom.

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/hooks", () => ({
  useActiveScanJobStream: vi.fn(),
  usePersonsLiveInvalidator: vi.fn(),
  useStartScanMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/sse", () => ({
  // No per-job SSE in the banner anymore — global SSE is consumed via
  // useActiveScanJobStream, which is mocked. Per-job SSE for fine-grained
  // cluster events still exists for usePersonsLiveInvalidator (mocked too).
  openScanEventStream: () => ({
    close: () => undefined,
  }),
}));

import { useActiveScanJobStream } from "@/lib/api/hooks";

import { ScanProgressBanner } from "@/components/layout/ScanProgressBanner";

function makeJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    kind: "full",
    state: "running" as const,
    progress: { processed: 5, total: 10, faces: 3, errors: 0 },
    ...overrides,
  };
}

function renderBanner(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ScanProgressBanner />
    </QueryClientProvider>,
  );
}

describe("ScanProgressBanner", () => {
  it("renders nothing when there's no active job (SSE-driven)", () => {
    vi.mocked(useActiveScanJobStream).mockReturnValue({
      data: null,
      status: "open",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    const { container } = render(<QueryClientProvider client={new QueryClient()}><ScanProgressBanner /></QueryClientProvider>);
    expect(container.firstChild).toBeNull();
  });

  it("renders the banner with state, progress + percent", () => {
    vi.mocked(useActiveScanJobStream).mockReturnValue({
      data: makeJob(),
      status: "open",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    renderBanner();
    expect(screen.getByTestId("scan-progress-banner")).toBeInTheDocument();
    // "running · 5/10 · 3 faces"
    expect(screen.getByText(/running/)).toBeInTheDocument();
    expect(screen.getByText(/5\/10/)).toBeInTheDocument();
    expect(screen.getByText(/3 faces/)).toBeInTheDocument();
    // 5/10 = 50%
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("hides the 'New scan' button when the job is DONE", () => {
    vi.mocked(useActiveScanJobStream).mockReturnValue({
      data: makeJob({ state: "done", progress: { processed: 10, total: 10, faces: 7, errors: 0 } }),
      status: "open",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    renderBanner();
    expect(screen.getByTestId("scan-progress-banner")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new scan/i })).toBeNull();
  });
});