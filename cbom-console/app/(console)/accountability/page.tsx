import { redirect } from "next/navigation";

export default async function AccountabilityPage({ searchParams }: { searchParams: Promise<{ group?: string | string[] }> }) {
  const group = (await searchParams).group;
  redirect(typeof group === "string" && group ? `/service-catalog?group=${encodeURIComponent(group)}` : "/service-catalog");
}
