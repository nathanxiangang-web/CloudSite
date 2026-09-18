"use client";

import { useParams } from "next/navigation";

import { PublicShell } from "@/components/PublicShell";
import { CatalogFollowButton } from "@/components/catalog/CatalogFollowButton";
import { CatalogDetailView } from "@/features/catalog";

export default function CatalogEntryPage() {
  const { entryId } = useParams<{ entryId: string }>();

  return (
    <PublicShell>
      <CatalogDetailView
        entryId={entryId}
        followSlot={<CatalogFollowButton entryId={entryId} />}
      />
    </PublicShell>
  );
}
