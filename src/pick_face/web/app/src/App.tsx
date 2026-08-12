// Routes — see docs/06 §1.1 (M6) for routing contract.
//
// /              → redirect to /persons
// /persons       → persons waterfall (M6-T-13)
// /persons/:id   → person detail + viewer (M6-T-14 + M7-T-1..T-5)
// /settings      → tabs for Paths / Scan / Model (M6-T-12)
// *              → 404

import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { PersonsPage } from "@/pages/PersonsPage";
import { PersonDetailPage } from "@/pages/PersonDetailPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/persons" replace /> },
      { path: "persons", element: <PersonsPage /> },
      { path: "persons/:id", element: <PersonDetailPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);