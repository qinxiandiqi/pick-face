// InstallAppButton — captures `beforeinstallprompt` and exposes a manual
// install button. Tests verify: no button until the event fires; click
// calls `prompt()` and surfaces the right toast; standalone mode hides
// the button; `appinstalled` clears it.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

const toastSuccess = vi.fn();
const toastInfo = vi.fn();
vi.mock("@/lib/toast", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: vi.fn(),
    info: (...args: unknown[]) => toastInfo(...args),
    warning: vi.fn(),
    fromError: vi.fn(),
  },
}));

import { InstallAppButton } from "@/components/settings/InstallAppButton";

// Helper: matchMedia with a controllable `matches`.
function setMatchMedia(matches: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (q: string) => ({
      matches: q === "(display-mode: standalone)" ? matches : false,
      media: q,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    }),
  });
}

interface FakePromptEventOptions {
  outcome?: "accepted" | "dismissed";
}

function dispatchInstallPromptEvent(
  opts: FakePromptEventOptions = {},
): { prompt: ReturnType<typeof vi.fn> } {
  const prompt = vi.fn().mockResolvedValue(undefined);
  const event = new Event("beforeinstallprompt") as Event & {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
    platforms: string[];
  };
  event.prompt = prompt;
  event.userChoice = Promise.resolve({
    outcome: opts.outcome ?? "accepted",
    platform: "web",
  });
  event.platforms = ["web"];
  act(() => {
    window.dispatchEvent(event);
  });
  return { prompt };
}

beforeEach(() => {
  toastSuccess.mockClear();
  toastInfo.mockClear();
  setMatchMedia(false);
});

describe("InstallAppButton", () => {
  it("renders nothing before beforeinstallprompt fires", () => {
    render(<InstallAppButton />);
    expect(screen.queryByTestId("install-app-button")).not.toBeInTheDocument();
  });

  it("renders nothing when running standalone", () => {
    setMatchMedia(true);
    render(<InstallAppButton />);
    dispatchInstallPromptEvent();
    expect(screen.queryByTestId("install-app-button")).not.toBeInTheDocument();
  });

  it("renders the button after beforeinstallprompt fires", () => {
    render(<InstallAppButton />);
    dispatchInstallPromptEvent();
    expect(screen.getByTestId("install-app-button")).toBeInTheDocument();
  });

  it("click → prompt() → success toast when user accepts", async () => {
    render(<InstallAppButton />);
    const { prompt } = dispatchInstallPromptEvent({ outcome: "accepted" });
    await act(async () => {
      fireEvent.click(screen.getByTestId("install-app-button"));
    });
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(toastSuccess).toHaveBeenCalledWith("App installed");
    // The button hides after a single-use prompt.
    expect(screen.queryByTestId("install-app-button")).not.toBeInTheDocument();
  });

  it("click → info toast when user dismisses", async () => {
    render(<InstallAppButton />);
    dispatchInstallPromptEvent({ outcome: "dismissed" });
    await act(async () => {
      fireEvent.click(screen.getByTestId("install-app-button"));
    });
    expect(toastInfo).toHaveBeenCalledWith("Install cancelled");
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("hides the button when appinstalled fires after a successful install", () => {
    render(<InstallAppButton />);
    dispatchInstallPromptEvent();
    expect(screen.getByTestId("install-app-button")).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("appinstalled"));
    });
    expect(screen.queryByTestId("install-app-button")).not.toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalledWith("App installed");
  });
});
