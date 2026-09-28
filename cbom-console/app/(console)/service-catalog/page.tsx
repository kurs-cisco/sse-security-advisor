import { ConsoleShell } from "@/app/components/console-shell";
import { ServiceCatalog } from "@/components/accountability/service-catalog";

export default async function ServiceCatalogPage({ searchParams }: { searchParams: Promise<{ group?: string | string[] }> }) {
  const group = (await searchParams).group;
  return <ConsoleShell><div className="page-container"><ServiceCatalog initialGroup={typeof group === "string" ? group : ""} /></div></ConsoleShell>;
}
