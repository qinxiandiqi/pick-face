// ScanProgressBanner — shows when there's an active scan job.
// We mock the two hooks the banner consumes (`useActiveScanJobQuery`
// and `usePersonsLiveInvalidator`) so we can drive the job state
// deterministically without standing up an SSE stream in jsdom.

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/hooks", () => ({
  useActiveScanJobQuery: vi.fn(),
  usePersonsLiveInvalidator: vi.fn(),
  useStartScanMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/sse", () => ({
  openScanEventStream: () => ({
    close: () => undefined,
  }),
}));

import { useActiveScanJobQuery } from "@/lib/api/hooks";

import { ScanProgressBanner } from "@/components/layout/ScanProgressBanner";

function makeJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    kind: "full",
    state: "RUNNING" as const,
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
  it("renders nothing when there's no active job (M8-T-8)", () => {
    vi.mocked(useActiveScanJobQuery).mockReturnValue({
      data: null,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    const { container } = render(<QueryClientProvider client={new QueryClient()}><ScanProgressBanner /></QueryClientProvider>);
    expect(container.firstChild).toBeNull();
  });

  it("renders the banner with state, progress + percent (M8-T-8)", () => {
    vi.mocked(useActiveScanJobQuery).mockReturnValue({
      data: makeJob(),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    renderBanner();
    expect(screen.getByTestId("scan-progress-banner")).toBeInTheDocument();
    // "RUNNING · 5/10 · 3 faces"
    expect(screen.getByText(/RUNNING/)).toBeInTheDocument();
    expect(screen.getByText(/5\/10/)).toBeInTheDocument();
    expect(screen.getByText(/3 faces/)).toBeInTheDocument();
    // 5/10 = 50%
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("hides the 'New scan' button when the job is DONE (M8-T-8)", () => {
    vi.mocked(useActiveScanJobQuery).mockReturnValue({
      data: makeJob({ state: "DONE", progress: { processed: 10, total: 10, faces: 7, errors: 0 } }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    renderBanner();
    expect(screen.getByTestId("scan-progress-banner")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new scan/i })).toBeNull();
  });
});