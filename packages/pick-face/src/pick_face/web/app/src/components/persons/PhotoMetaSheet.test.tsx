// PhotoMetaSheet — right-side drawer that reads extended photo metadata
// from /api/photos/{id}/meta. M7-T-8.
//
// We drive the React Query state by mocking usePhotoMetadataQuery via
// vi.mock — that keeps the test focused on the drawer's rendering logic
// (loading skeletons, error message, success sections) without standing
// up MSW or a fake fetch.

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { PhotoMetadata } from "@/lib/api/schemas";

// ---------------------------------------------------------------------------
// Mock usePhotoMetadataQuery — `usePhotoMetadataQuery` is the only export we
// exercise, so mocking the whole hooks module is safe for these tests.
// ---------------------------------------------------------------------------
const metaMock = vi.fn();
vi.mock("@/lib/api/hooks", () => ({
  usePhotoMetadataQuery: (id: number | null) => metaMock(id),
}));

import { PhotoMetaSheet } from "@/components/persons/PhotoMetaSheet";

const SAMPLE: PhotoMetadata = {
  id: 42,
  path: "/photos/2026/wedding/IMG_0042.jpg",
  mtime: 1_725_000_000,
  size: 4_500_000,
  content_hash: "sha256:abcd1234",
  natural_width: 4032,
  natural_height: 3024,
  faces: [
    {
      id: 7,
      bbox: [120, 80, 480, 600],
      cluster_id: 3,
      det_score: 0.92,
      quality: 0.71,
    },
    {
      id: 8,
      bbox: [2400, 200, 3000, 900],
      cluster_id: null,
      det_score: 0.81,
      quality: 0.55,
    },
  ],
  exif: {
    make: "Canon",
    model: "EOS R6",
    taken_at: 1_718_460_600, // 2024-06-15 14:30:00 UTC
    lens: "RF 50mm F1.2 L USM",
    exposure: 1 / 200,
    f_number: 2.8,
    iso: 400,
    focal_length: 50,
    gps_lat: 37.5,
    gps_lon: -122.0833,
  },
};

function withQueryClient(children: React.ReactNode): React.JSX.Element {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("PhotoMetaSheet", () => {
  it("renders nothing meaningful while loading", () => {
    metaMock.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    // The Sheet is mounted (Radix dialog title); the loading state shows
    // skeleton lines and does NOT yet render the data sections.
    expect(screen.getByText(/photo details/i)).toBeInTheDocument();
    expect(screen.queryByText(/wedding/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("meta-faces-list")).not.toBeInTheDocument();
  });

  it("shows an error message when the query fails", async () => {
    metaMock.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    expect(
      await screen.findByText(/failed to load metadata/i),
    ).toBeInTheDocument();
  });

  it("renders identity, image, faces, and EXIF sections when data is loaded", () => {
    metaMock.mockReturnValue({ data: SAMPLE, isLoading: false, isError: false });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );

    // Identity
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("/photos/2026/wedding/IMG_0042.jpg")).toBeInTheDocument();
    expect(screen.getByText("sha256:abcd1234")).toBeInTheDocument();

    // Image
    expect(screen.getByText(/4032 × 3024 px/)).toBeInTheDocument();

    // Faces header counts
    expect(screen.getByText(/faces \(2\)/i)).toBeInTheDocument();

    // Faces list
    const list = screen.getByTestId("meta-faces-list");
    expect(list).toBeInTheDocument();
    expect(screen.getByText(/face #7/)).toBeInTheDocument();
    expect(screen.getByText(/face #8/)).toBeInTheDocument();
    // bbox values rendered with one decimal place
    expect(screen.getByText(/\[120\.0, 80\.0, 480\.0, 600\.0\]/)).toBeInTheDocument();

    // EXIF section renders camera / exposure / GPS data.
    expect(screen.getByText("Canon EOS R6")).toBeInTheDocument();
    expect(screen.getByText("RF 50mm F1.2 L USM")).toBeInTheDocument();
    // Exposure line collapses the four exposure fields into "1/200s • f/2.8 • ISO 400 • 50mm".
    expect(screen.getByText(/1\/200s • f\/2\.8 • ISO 400 • 50mm/)).toBeInTheDocument();
    // GPS formatted as DMS.
    expect(screen.getByText(/37°30'0\.0"N/)).toBeInTheDocument();
  });

  it("renders an empty-faces placeholder when there are no faces", () => {
    metaMock.mockReturnValue({
      data: { ...SAMPLE, faces: [] },
      isLoading: false,
      isError: false,
    });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    expect(screen.getByText(/no faces detected/i)).toBeInTheDocument();
    expect(screen.queryByTestId("meta-faces-list")).not.toBeInTheDocument();
    // Section header still shows the count.
    expect(screen.getByText(/faces \(0\)/i)).toBeInTheDocument();
  });

  it("does not call the query when closed (gated by open=false → id=null)", () => {
    metaMock.mockClear();
    metaMock.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={false} onOpenChange={vi.fn()} />,
      ),
    );
    // The drawer passes `null` to usePhotoMetadataQuery when closed —
    // that gating lives in the component itself. Verify the call was made
    // with null, regardless of the photoId prop.
    expect(metaMock).toHaveBeenCalledWith(null);
  });

  it("forwards the photoId when open", () => {
    metaMock.mockClear();
    metaMock.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    expect(metaMock).toHaveBeenCalledWith(42);
  });

  it("calls onOpenChange(false) when the Close button is clicked", async () => {
    metaMock.mockReturnValue({ data: SAMPLE, isLoading: false, isError: false });
    const onOpenChange = vi.fn();
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={onOpenChange} />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByText(/photo details/i)).toBeInTheDocument();
    });
    // There are two buttons named "Close" in the DOM (the sr-only X icon
    // inside SheetContent + our footer Button). Click the last one — the
    // footer button — by filtering out the icon-only SheetClose.
    const closeButtons = screen.getAllByRole("button", { name: /^close$/i });
    // The SheetClose's accessible name comes from <span class="sr-only">Close</span>
    // (text-only); the footer Button has visible text. Pick the visible-text one.
    const visibleCloseButton = closeButtons.find((b) =>
      b.textContent?.trim() === "Close",
    );
    expect(visibleCloseButton).toBeDefined();
    visibleCloseButton!.click();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("renders a no-EXIF placeholder when all exif fields are null", () => {
    metaMock.mockReturnValue({
      data: { ...SAMPLE, exif: {
        make: null, model: null, taken_at: null, lens: null,
        exposure: null, f_number: null, iso: null, focal_length: null,
        gps_lat: null, gps_lon: null,
      } },
      isLoading: false,
      isError: false,
    });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    expect(screen.getByText(/no exif tags on this photo/i)).toBeInTheDocument();
  });

  it("renders only the Taken row when the photo has no camera/exposure/GPS", () => {
    metaMock.mockReturnValue({
      data: { ...SAMPLE, exif: {
        make: null, model: null, taken_at: 1_718_460_600, lens: null,
        exposure: null, f_number: null, iso: null, focal_length: null,
        gps_lat: null, gps_lon: null,
      } },
      isLoading: false,
      isError: false,
    });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    // No Camera / Exposure / GPS rows.
    expect(screen.queryByText(/Canon|EOS R6/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1\/200s/)).not.toBeInTheDocument();
    expect(screen.queryByText(/°/)).not.toBeInTheDocument();
    // But the Taken row IS present.
    expect(screen.getByText(/taken/i)).toBeInTheDocument();
  });

  it("formats 1s+ exposures with one decimal instead of 1/x style", () => {
    metaMock.mockReturnValue({
      data: { ...SAMPLE, exif: { ...SAMPLE.exif, exposure: 2.5 } },
      isLoading: false,
      isError: false,
    });
    render(
      withQueryClient(
        <PhotoMetaSheet photoId={42} open={true} onOpenChange={vi.fn()} />,
      ),
    );
    expect(screen.getByText(/2\.5s • f\/2\.8 • ISO 400 • 50mm/)).toBeInTheDocument();
  });
});