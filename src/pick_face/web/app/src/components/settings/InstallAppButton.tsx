// InstallAppButton — captures the `beforeinstallprompt` event and
// surfaces a single "Install app" button so the user can put pick-face
// on their home screen without an auto-prompt surprise.
//
// Visibility rules (per user decision, M7-T-9):
//   - Renders nothing if the app is already running standalone
//     (matchMedia('(display-mode: standalone)')).
//   - Renders nothing until the browser fires `beforeinstallprompt` —
//     which means the user has accepted the install criteria (HTTPS,
//     manifest valid, has a service worker). Until then, the button
//     would be lying.
//   - Hides again after `appinstalled` (the user accepted) or after
//     the prompt result is "dismissed" (the prompt is single-use).
//
// iOS Safari does not fire `beforeinstallprompt`; the button stays
// hidden there. Users reach install via the iOS share sheet → "Add
// to Home Screen" — that's a manifest-only path.

import * as React from "react";
import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";

// Mirror of the browser's BeforeInstallPromptEvent. We declare the
// shape locally so we don't need `@types/webapp-install` (sonner doesn't
// ship one either).
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{
    outcome: "accepted" | "dismissed";
    platform: string;
  }>;
  prompt(): Promise<void>;
}

function isStandalone(): boolean {
  // jsdom doesn't ship matchMedia; the `?.` guard keeps the unit test
  // safe even if the test-setup stub is missing. The actual runtime
  // path on Chrome/Edge/Firefox always has it.
  return Boolean(window.matchMedia?.("(display-mode: standalone)").matches);
}

export function InstallAppButton(): React.JSX.Element | null {
  const [evt, setEvt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    if (isStandalone()) return;

    function onPrompt(e: Event): void {
      // Always preventDefault so the browser doesn't show its own
      // mini-infobar — we want install to be user-initiated via this
      // explicit button only.
      e.preventDefault();
      setEvt(e as BeforeInstallPromptEvent);
    }
    function onInstalled(): void {
      setEvt(null);
      toast.success("App installed");
    }

    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (!evt) return null;

  async function handleClick(): Promise<void> {
    if (!evt) return;
    setInstalling(true);
    try {
      await evt.prompt();
      const choice = await evt.userChoice;
      if (choice.outcome === "accepted") {
        toast.success("App installed");
      } else {
        toast.info("Install cancelled");
      }
    } finally {
      // The prompt is single-use; clear the event so the button hides
      // regardless of the outcome (the browser won't fire
      // beforeinstallprompt again until the user re-meets the criteria).
      setEvt(null);
      setInstalling(false);
    }
  }

  return (
    <Button
      data-testid="install-app-button"
      onClick={handleClick}
      disabled={installing}
      className="gap-2"
    >
      <Download className="h-4 w-4" aria-hidden />
      Install app
    </Button>
  );
}
