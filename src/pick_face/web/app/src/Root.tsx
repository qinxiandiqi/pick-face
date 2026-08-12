// Application root — wraps the router in TanStack Query + Theme providers.

import * as React from "react";
import { RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { router } from "@/App";
import { ThemeProvider } from "@/components/layout/ThemeProvider";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

export function Root(): React.JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>
  );
}