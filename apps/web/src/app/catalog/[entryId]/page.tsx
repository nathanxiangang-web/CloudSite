"use client";

import { useParams } from "next/navigation";

import { PublicShell } from "@/components/PublicShell";
import { CatalogDetailView } from "@/features/catalog";

export default function CatalogEntryPage() {
  const { entryId } = useParams<{ entryId: string }>();

  return (
    <PublicShell>
      <CatalogDetailView entryId={entryId} />
    </PublicShell>
  );
}
