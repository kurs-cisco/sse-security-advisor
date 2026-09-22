import { ConsoleShell } from "@/app/components/console-shell";
import { AdminConsole } from "@/components/admin/admin-console";

export default function AdminPage() {
  return <ConsoleShell><div className="page-container"><AdminConsole /></div></ConsoleShell>;
}
