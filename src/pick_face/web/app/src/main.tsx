// Entry point — mounts <Root /> on #root.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@/index.css";
import { Root } from "@/Root";
import "@/lib/pwa"; // M7.9 — registers the service worker (no-op outside PROD).

const container = document.getElementById("root");
if (!container) throw new Error("#root not found");

createRoot(container).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);