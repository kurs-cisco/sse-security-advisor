"use client";

import { motion, useReducedMotion } from "motion/react";
import { formatNumber } from "@/app/lib/utils";

export function NumberTicker({ value }: { value: number }) {
  const reduced = useReducedMotion();
  return <motion.span initial={{ opacity: 0, y: reduced ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduced ? 0 : 0.28 }}>{formatNumber(value)}</motion.span>;
}
