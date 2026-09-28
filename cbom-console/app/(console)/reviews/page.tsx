import { ConsoleShell } from "@/app/components/console-shell";
import { OperationalReviewWorkspace } from "@/components/reviews/operational-review";

export default function ReviewsPage() {
  return <ConsoleShell><div className="page-container"><OperationalReviewWorkspace /></div></ConsoleShell>;
}
