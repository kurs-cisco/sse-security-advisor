import { OverviewDashboard } from "@/app/components/dashboard/overview-dashboard";
import { ConsoleShell } from "@/app/components/console-shell";

export default function HomePage() {
  return <ConsoleShell><OverviewDashboard /></ConsoleShell>;
}
