// FaceOverlay — SVG bbox rendering on top of the photo.
// M7-T-6: verifies empty/single/multi box rendering, natural-dim
// short-circuit, and the highlightClusterId filter (matching cluster
// gets full opacity, mismatching cluster gets dimmed stroke).

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { FaceOverlay, type Bbox } from "@/components/viewer/FaceOverlay";

/** Pull the rect children out of the <svg data-testid="face-overlay">. */
function rects(svg: HTMLElement): Element[] {
  return Array.from(svg.querySelectorAll("rect"));
}

const FACE: Bbox = {
  x: 100,
  y: 120,
  w: 200,
  h: 240,
  clusterId: 7,
};

describe("FaceOverlay", () => {
  it("renders nothing when boxes is empty", () => {
    const { container } = render(
      <FaceOverlay naturalW={800} naturalH={600} boxes={[]} />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("face-overlay")).not.toBeInTheDocument();
  });

  it("renders nothing when natural dimensions are zero / negative", () => {
    const { container: zeroW } = render(
      <FaceOverlay naturalW={0} naturalH={600} boxes={[FACE]} />,
    );
    expect(zeroW.firstChild).toBeNull();

    const { container: zeroH } = render(
      <FaceOverlay naturalW={800} naturalH={0} boxes={[FACE]} />,
    );
    expect(zeroH.firstChild).toBeNull();

    const { container: negW } = render(
      <FaceOverlay naturalW={-1} naturalH={600} boxes={[FACE]} />,
    );
    expect(negW.firstChild).toBeNull();
  });

  it("renders a single <svg> with one <rect> when given one box", () => {
    render(
      <FaceOverlay naturalW={800} naturalH={600} boxes={[FACE]} />,
    );
    const svg = screen.getByTestId("face-overlay");
    expect(svg.tagName.toLowerCase()).toBe("svg");
    expect(svg.getAttribute("viewBox")).toBe("0 0 800 600");
    const list = rects(svg);
    expect(list).toHaveLength(1);
    const rect = list[0];
    expect(rect.tagName.toLowerCase()).toBe("rect");
    expect(rect.getAttribute("x")).toBe("100");
    expect(rect.getAttribute("y")).toBe("120");
    expect(rect.getAttribute("width")).toBe("200");
    expect(rect.getAttribute("height")).toBe("240");
    // strokeWidth = max(2, min(800, 600) / 200) = max(2, 3) = 3
    expect(rect.getAttribute("stroke-width")).toBe("3");
    expect(rect.getAttribute("vector-effect")).toBe("non-scaling-stroke");
  });

  it("renders one rect per box when several are provided", () => {
    const boxes: Bbox[] = [
      { x: 10, y: 10, w: 50, h: 50, clusterId: 1 },
      { x: 100, y: 100, w: 80, h: 80, clusterId: 2 },
      { x: 250, y: 250, w: 200, h: 200, clusterId: null },
    ];
    render(<FaceOverlay naturalW={800} naturalH={600} boxes={boxes} />);
    expect(rects(screen.getByTestId("face-overlay"))).toHaveLength(3);
  });

  it("uses primary stroke at full opacity for the highlighted cluster", () => {
    render(
      <FaceOverlay
        naturalW={800}
        naturalH={600}
        boxes={[FACE]}
        highlightClusterId={7}
      />,
    );
    const rect = rects(screen.getByTestId("face-overlay"))[0];
    expect(rect.getAttribute("stroke")).toMatch(/var\(--primary\)/);
    expect(rect.getAttribute("stroke-opacity")).toBe("1");
  });

  it("dims strokes for non-matching clusters when highlightClusterId is set", () => {
    const boxes: Bbox[] = [
      { x: 0, y: 0, w: 100, h: 100, clusterId: 7 },
      { x: 200, y: 200, w: 100, h: 100, clusterId: 99 },
    ];
    render(
      <FaceOverlay
        naturalW={800}
        naturalH={600}
        boxes={boxes}
        highlightClusterId={7}
      />,
    );
    const list = rects(screen.getByTestId("face-overlay"));
    const [matching, other] = list;
    expect(matching.getAttribute("stroke-opacity")).toBe("1");
    expect(matching.getAttribute("stroke")).toMatch(/var\(--primary\)/);
    expect(other.getAttribute("stroke-opacity")).toBe("0.45");
    expect(other.getAttribute("stroke")).toMatch(/var\(--muted-foreground\)/);
  });

  it("leaves clusterId=null boxes undimmed even when highlight is set", () => {
    // Unknown-cluster faces (e.g. embeddings not yet clustered) should be
    // visible alongside the highlighted person — dim only mismatched IDs.
    const box: Bbox = { x: 0, y: 0, w: 50, h: 50, clusterId: null };
    render(
      <FaceOverlay
        naturalW={800}
        naturalH={600}
        boxes={[box]}
        highlightClusterId={7}
      />,
    );
    const rect = rects(screen.getByTestId("face-overlay"))[0];
    expect(rect.getAttribute("stroke-opacity")).toBe("1");
  });

  it("renders all boxes uniformly when highlightClusterId is null", () => {
    const boxes: Bbox[] = [
      { x: 0, y: 0, w: 50, h: 50, clusterId: 1 },
      { x: 100, y: 0, w: 50, h: 50, clusterId: 2 },
    ];
    render(
      <FaceOverlay
        naturalW={800}
        naturalH={600}
        boxes={boxes}
        highlightClusterId={null}
      />,
    );
    const list = rects(screen.getByTestId("face-overlay"));
    for (const r of list) {
      expect(r.getAttribute("stroke-opacity")).toBe("1");
      expect(r.getAttribute("stroke")).toMatch(/var\(--primary\)/);
    }
  });
});