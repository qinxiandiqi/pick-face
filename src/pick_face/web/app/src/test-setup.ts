// Test setup: jsdom-friendly matchers + auto-cleanup for React Testing
// Library. Loaded by vitest.config.ts → setupFiles.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});