// Entry point — mounts <Root /> on #root.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@/index.css";
import { Root } from "@/Root";

const container = document.getElementById("root");
if (!container) throw new Error("#root not found");

createRoot(container).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);