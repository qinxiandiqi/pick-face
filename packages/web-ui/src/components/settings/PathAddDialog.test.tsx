// PathAddDialog — directory picker behavior.
//
// The picker is a hidden `<input webkitdirectory>` triggered by the
// visible "Browse" button. Browsers expose varying amounts of path
// info to the page (Firefox gives `File.path`; Chromium / Safari
// only give the leaf name via `webkitRelativePath`). The dialog must
// pre-fill the form field either way and surface a hint so the user
// knows whether they still need to type the parent path.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/api/hooks", () => ({
  useAddPathMutation: () => ({ mutateAsync: vi.fn().mockResolvedValue({}) }),
}));

// jsdom doesn't model ``<input webkitdirectory>`` — for the test we
// stub the prototype so feature detection passes. (Vitest's jsdom env
// otherwise strips the property, hiding the Browse button.)
beforeEach(() => {
  const proto = HTMLInputElement.prototype as unknown as Record<
    string,
    unknown
  >;
  proto["webkitdirectory"] = false;
});

import { PathAddDialog } from "@/components/settings/PathAddDialog";

function openDialog() {
  return render(
    <PathAddDialog open onOpenChange={() => undefined} />,
  );
}

describe("PathAddDialog — directory picker", () => {
  it("renders a Browse button next to the path input", () => {
    openDialog();
    expect(screen.getByTestId("browse-directory-button")).toBeInTheDocument();
    expect(screen.getByTestId("add-path-input")).toBeInTheDocument();
  });

  it("pre-fills the input with the picked file's absolute path when available (Firefox-shaped)", async () => {
    const user = userEvent.setup();
    openDialog();

    const picker = screen.getByTestId("directory-picker-input") as HTMLInputElement;
    const file = new File(["x"], "img.jpg") as File & { path?: string };
    Object.defineProperty(file, "webkitRelativePath", { value: "vacation/img.jpg" });
    Object.defineProperty(file, "path", { value: "C:\\Users\\me\\Pictures\\vacation" });
    await user.upload(picker, [file]);

    const input = screen.getByTestId("add-path-input") as HTMLInputElement;
    expect(input.value).toBe("C:\\Users\\me\\Pictures\\vacation");
    // Complete pick → no "add parent path" hint, just a confirmation.
    expect(screen.getByTestId("picker-hint").textContent).toMatch(/picked from/i);
  });

  it("falls back to the leaf directory name on Chromium-shaped picks and surfaces a hint", async () => {
    const user = userEvent.setup();
    openDialog();

    const picker = screen.getByTestId("directory-picker-input") as HTMLInputElement;
    const file = new File(["x"], "img.jpg");
    // No `path` property (Chromium / Safari don't expose it).
    Object.defineProperty(file, "webkitRelativePath", { value: "vacation/img.jpg" });
    await user.upload(picker, [file]);

    const input = screen.getByTestId("add-path-input") as HTMLInputElement;
    expect(input.value).toBe("vacation");
    expect(screen.getByTestId("picker-hint").textContent).toMatch(/parent path/i);
  });

  it("clears the hint when the dialog is closed and reopened", async () => {
    // We model the close-then-reopen cycle by mounting once, picking,
    // then closing via the Cancel button (which calls onOpenChange
    // via our `handleOpenChange` wrapper). The hint should be cleared.
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <PathAddDialog open={true} onOpenChange={onOpenChange} />,
    );

    const picker = screen.getByTestId("directory-picker-input") as HTMLInputElement;
    const file = new File(["x"], "img.jpg") as File & { path?: string };
    Object.defineProperty(file, "webkitRelativePath", { value: "vacation/img.jpg" });
    Object.defineProperty(file, "path", { value: "/Users/me/Pictures/vacation" });
    await user.upload(picker, [file]);
    expect(screen.getByTestId("picker-hint")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);

    // Reopen — hint should be gone.
    rerender(<PathAddDialog open={true} onOpenChange={onOpenChange} />);
    expect(screen.queryByTestId("picker-hint")).toBeNull();
    expect((screen.getByTestId("add-path-input") as HTMLInputElement).value).toBe("");
  });
});