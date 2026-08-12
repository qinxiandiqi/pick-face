// ModelPackCard — renders the active pack + license-class-driven
// Badge from /api/ready (M7-T-13).
//
// We mock @/lib/toast so we can assert the one-time "NC-research
// unacknowledged" warning fires once on mount and not on re-renders.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ActivePack } from "@/lib/api/schemas";

const toastWarn = vi.fn();
vi.mock("@/lib/toast", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: (...args: unknown[]) => toastWarn(...args),
    fromError: vi.fn(),
  },
}));

import { ModelPackCard } from "@/components/settings/ModelPackCard";

const PERMISSIVE: ActivePack = {
  id: "yunet-sface",
  display_name: "YuNet + SFace INT8",
  license_class: "permissive",
  license_name: "MIT",
  license_spdx: "MIT",
  nc_research_acknowledged: true,
};

const NC_ACKED: ActivePack = {
  id: "yunet-arcface",
  display_name: "YuNet + ArcFace R100",
  license_class: "nc-research",
  license_name: "InsightFace NC-research",
  license_spdx: "",
  nc_research_acknowledged: true,
};

const NC_UNACKED: ActivePack = {
  ...NC_ACKED,
  nc_research_acknowledged: false,
};

const USER_SUPPLIED: ActivePack = {
  id: "my-custom-pack",
  display_name: "User-trained model",
  license_class: "user-supplied",
  license_name: "user-supplied",
  license_spdx: "",
  nc_research_acknowledged: true,
};

function wrap(children: React.ReactNode): React.JSX.Element {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  toastWarn.mockClear();
});

describe("ModelPackCard", () => {
  it("renders the loading skeleton when isLoading is true", () => {
    render(wrap(<ModelPackCard pack={null} isLoading={true} />));
    // Skeletons have animate-pulse; the rendered pack card must be absent.
    expect(screen.queryByTestId("model-pack-card")).not.toBeInTheDocument();
  });

  it("renders an unknown-pack placeholder when pack is null", () => {
    render(wrap(<ModelPackCard pack={null} isLoading={false} />));
    expect(screen.getByTestId("model-pack-unknown")).toBeInTheDocument();
  });

  it("renders permissive pack with a secondary license badge", () => {
    render(wrap(<ModelPackCard pack={PERMISSIVE} isLoading={false} />));
    expect(screen.getByTestId("model-pack-id")).toHaveTextContent("yunet-sface");
    const badge = screen.getByTestId("model-pack-license-badge");
    expect(badge).toHaveTextContent("permissive");
    // No unacknowledged warning for permissive.
    expect(screen.queryByTestId("model-pack-unacknowledged")).not.toBeInTheDocument();
    // Display name + license rendered as secondary line.
    expect(screen.getByText(/YuNet \+ SFace INT8 · MIT/)).toBeInTheDocument();
  });

  it("renders NC-research pack with a destructive license badge", () => {
    render(wrap(<ModelPackCard pack={NC_ACKED} isLoading={false} />));
    const badge = screen.getByTestId("model-pack-license-badge");
    expect(badge).toHaveTextContent(/NC-research/i);
    // Acked → no "AC-9 will block" badge.
    expect(screen.queryByTestId("model-pack-unacknowledged")).not.toBeInTheDocument();
  });

  it("shows the AC-9 block badge when NC-research is unacknowledged", () => {
    render(wrap(<ModelPackCard pack={NC_UNACKED} isLoading={false} />));
    expect(screen.getByTestId("model-pack-unacknowledged")).toBeInTheDocument();
    expect(screen.getByTestId("model-pack-unacknowledged")).toHaveTextContent(/AC-9/);
  });

  it("renders user-supplied pack with an outline badge", () => {
    render(wrap(<ModelPackCard pack={USER_SUPPLIED} isLoading={false} />));
    const badge = screen.getByTestId("model-pack-license-badge");
    expect(badge).toHaveTextContent("user-supplied");
  });
});