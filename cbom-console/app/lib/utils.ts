import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number | null | undefined) {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
}

export function serviceGroupDisplayName(value: string) {
  const withoutEvidenceSuffix = value.replace(/(?:-|_)NO(?:-|_)CBOM$/i, "");
  // The tracker historically used both a key and several human-readable
  // variants for this group. Keep all renderers aligned with the approved
  // Service Catalog display name without changing the underlying key.
  if (/^(?:on-prem-clients|on[ -]?prem\s*\/\s*clients)$/i.test(withoutEvidenceSuffix)) return "Chromebook Client";
  return withoutEvidenceSuffix.toLocaleLowerCase() === "discovery" ? "Discovery" : withoutEvidenceSuffix;
}

export function serviceGroupFromReference(value: string | undefined) {
  if (!value) return "Unassigned";
  const collectionSeparator = value.indexOf("/");
  const group = collectionSeparator >= 0 ? value.slice(collectionSeparator + 1) : value;
  return serviceGroupDisplayName(group);
}
