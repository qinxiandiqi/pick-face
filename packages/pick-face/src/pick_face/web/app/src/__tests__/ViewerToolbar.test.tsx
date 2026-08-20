// ViewerToolbar — rendered while store.open is true. Asserts toolbar
// controls exist and disable correctly at edges.

import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { ViewerToolbar } from "@/components/viewer/ViewerToolbar";
import { useViewerStore } from "@/lib/viewerStore";

const roster = [
  { id: 1, url: "/api/photos/1", thumbUrl: "/api/photos/1/thumb", width: 800, height: 600 },
  { id: 2, url: "/api/photos/2", thumbUrl: "/api/photos/2/thumb", width: 800, height: 600 },
];

describe("ViewerToolbar", () => {
  beforeEach(() => {
    useViewerStore.setState({
      open: false,
      personId: null,
      photos: [],
      index: 0,
      scale: 1,
      pan: { x: 0, y: 0 },
      fullscreen: false,
    });
  });

  it("renders nothing when closed", () => {
    const { container } = render(<ViewerToolbar />);
    expect(container.firstChild).toBeNull();
  });

  it("renders controls when open with multi-photo roster", () => {
    useViewerStore.setState({ open: true, photos: roster, index: 0 });
    render(<ViewerToolbar />);
    expect(screen.getByLabelText(/previous photo/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/next photo/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/close viewer/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/reset view/i)).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });

  it("disables Previous at index 0", () => {
    useViewerStore.setState({ open: true, photos: roster, index: 0 });
    render(<ViewerToolbar />);
    expect(screen.getByLabelText(/previous photo/i)).toBeDisabled();
    expect(screen.getByLabelText(/next photo/i)).not.toBeDisabled();
  });

  it("disables Next at last index", () => {
    useViewerStore.setState({ open: true, photos: roster, index: 1 });
    render(<ViewerToolbar />);
    expect(screen.getByLabelText(/previous photo/i)).not.toBeDisabled();
    expect(screen.getByLabelText(/next photo/i)).toBeDisabled();
  });
});