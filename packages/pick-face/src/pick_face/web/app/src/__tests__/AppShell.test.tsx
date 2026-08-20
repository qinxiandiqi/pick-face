// AppShell — sidebar navigation. Renders inside MemoryRouter with a fake
// outlet child so we can assert navigation links + active state.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "@/components/layout/AppShell";

function renderAt(path: string): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/persons" element={<div>persons outlet</div>} />
            <Route path="/settings" element={<div>settings outlet</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  it("renders the sidebar with Persons and Settings links", () => {
    renderAt("/persons");
    expect(screen.getByRole("link", { name: /persons/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /settings/i })).toBeInTheDocument();
  });

  it("renders the version string", () => {
    renderAt("/persons");
    expect(screen.getByText(/v3\.0\.0/)).toBeInTheDocument();
  });

  it("marks the active route link", () => {
    renderAt("/settings");
    const settingsLink = screen.getByRole("link", { name: /settings/i });
    expect(settingsLink.className).toMatch(/bg-primary/);
  });

  it("renders the outlet content", () => {
    renderAt("/persons");
    expect(screen.getByText("persons outlet")).toBeInTheDocument();
  });
});