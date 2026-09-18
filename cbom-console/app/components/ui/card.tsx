import { type HTMLAttributes } from "react";
import { cn } from "@/app/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <section className={cn("surface-card", className)} {...props} />;
}
