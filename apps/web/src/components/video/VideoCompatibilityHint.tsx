"use client";

import { Info } from "lucide-react";
import { compatibilityHint } from "./video-utils";

export function VideoCompatibilityHint({ extension }: { extension: string }) {
  return <p className="video-compatibility-hint"><Info />{compatibilityHint(extension)}</p>;
}
