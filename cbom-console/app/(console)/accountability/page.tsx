import { ConsoleShell } from "@/app/components/console-shell";
import { ServiceAccountability } from "@/components/accountability/service-accountability";

export default function AccountabilityPage() {
  return <ConsoleShell><div className="page-container"><ServiceAccountability /></div></ConsoleShell>;
}
