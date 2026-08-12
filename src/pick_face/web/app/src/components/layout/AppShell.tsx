// Application shell — sidebar + content area. Hosts the routing outlet,
// the scan-progress banner, and the toaster. The layout uses CSS grid so
// the sidebar stays full-height and the content area scrolls independently.

import * as React from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Camera, FolderTree, Settings as SettingsIcon } from "lucide-react";

import { cn } from "@/lib/cn";
import { Toaster } from "@/components/ui/toaster";
import { ScanProgressBanner } from "@/components/layout/ScanProgressBanner";

interface navItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
}

const navItems: navItem[] = [
  { to: "/persons", label: "Persons", icon: Camera, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

export function AppShell(): React.JSX.Element {
  return (
    <div className="grid h-full grid-cols-[14rem_1fr] bg-background text-foreground">
      <aside className="flex flex-col border-r bg-muted/30">
        <div className="flex h-14 items-center gap-2 border-b px-4 font-semibold">
          <FolderTree className="h-5 w-5" aria-hidden />
          <Link to="/persons">pick-face</Link>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )
              }
            >
              <item.icon className="h-4 w-4" aria-hidden />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3 text-xs text-muted-foreground">
          v3.0.0.dev0
        </div>
      </aside>

      <main className="flex flex-col overflow-hidden">
        <ScanProgressBanner />
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
      </main>
      <Toaster />
    </div>
  );
}