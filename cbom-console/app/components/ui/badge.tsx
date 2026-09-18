import { type HTMLAttributes } from "react";
import { cn } from "@/app/lib/utils";

type Tone = "neutral" | "info" | "warning" | "danger" | "success";
export function Badge({ tone = "neutral", className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn("badge", `badge-${tone}`, className)} {...props} />;
}
