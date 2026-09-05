import { Suspense } from "react";
import { PublicShell } from "@/components/PublicShell";
import { HomeContent, HomeSkeleton } from "@/components/HomeContent";
import { SiteFooter } from "@/components/SiteFooter";

export const revalidate = 60;

export default function HomePage() {
  return (
    <PublicShell>
      <div className="page home-page">
        <Suspense fallback={<HomeSkeleton />}>
          <HomeContent />
        </Suspense>
        <SiteFooter />
      </div>
    </PublicShell>
  );
}
