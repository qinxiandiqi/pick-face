// Class-name helper used by every shadcn/ui primitive.
// Combines `clsx` (conditional joining) with `tailwind-merge` (resolves
// conflicting Tailwind classes so e.g. `px-2 px-4` becomes `px-4`).
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}