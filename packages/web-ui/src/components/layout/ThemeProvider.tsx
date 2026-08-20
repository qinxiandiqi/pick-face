"use client";

// Theme provider wrapping next-themes. Per shadcn/ui template —
// `attribute="class"` so Tailwind's `darkMode: 'class'` flips cleanly.

import * as React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";

export function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>): React.JSX.Element {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}