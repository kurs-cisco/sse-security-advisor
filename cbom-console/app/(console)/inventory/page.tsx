import { InventoryWorkbench } from "@/components/inventory/inventory-workbench";
import { ConsoleShell } from "@/app/components/console-shell";

export default function InventoryPage() {
  return <ConsoleShell><div className="page-container"><InventoryWorkbench /></div></ConsoleShell>;
}
