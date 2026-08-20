// PwaSettingsCard — Settings → App tab. Renders the install button slot
// and a "Check for update" trigger that calls `lib/pwa.refreshPwa()`.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

const refreshPwa = vi.fn().mockResolvedValue(undefined);
vi.mock("@/lib/pwa", () => ({
  refreshPwa: (...args: unknown[]) => refreshPwa(...args),
  initPwa: vi.fn(),
}));

vi.mock("@/components/settings/InstallAppButton", () => ({
  InstallAppButton: () => (
    <button data-testid="install-app-button-stub">Install</button>
  ),
}));

import { PwaSettingsCard } from "@/components/settings/PwaSettingsCard";

beforeEach(() => {
  refreshPwa.mockClear();
});

describe("PwaSettingsCard", () => {
  it("renders the PWA badge and the Check-for-update button", () => {
    render(<PwaSettingsCard />);
    expect(screen.getByTestId("pwa-settings-card")).toBeInTheDocument();
    expect(screen.getByTestId("pwa-install-state")).toHaveTextContent("PWA");
    expect(screen.getByTestId("check-update-button")).toBeInTheDocument();
    expect(screen.getByTestId("install-app-button-stub")).toBeInTheDocument();
  });

  it("calls refreshPwa when Check for update is clicked", async () => {
    render(<PwaSettingsCard />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("check-update-button"));
    });
    expect(refreshPwa).toHaveBeenCalledTimes(1);
  });
});
