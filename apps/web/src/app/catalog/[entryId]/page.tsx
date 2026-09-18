"use client";

import { useParams } from "next/navigation";

import { CatalogFollowButton } from "@/components/catalog/CatalogFollowButton";
import { CatalogDetailView } from "@/features/catalog";

export default function CatalogEntryPage() {
  const { entryId } = useParams<{ entryId: string }>();
  return (
    <CatalogDetailView
      entryId={entryId}
      followControl={<CatalogFollowButton entryId={entryId} />}
    />
  );
}
