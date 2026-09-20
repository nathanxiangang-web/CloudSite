import { PublicShell } from "@/components/PublicShell";
import { HomeSkeleton } from "@/components/HomeContent";
import { SiteFooter } from "@/components/SiteFooter";

export default function Loading() {
  return (
    <PublicShell>
      <div className="page home-page">
        <HomeSkeleton />
        <SiteFooter />
      </div>
    </PublicShell>
  );
}
