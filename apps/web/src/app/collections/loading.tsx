import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";

export default function Loading() {
  return (
    <PublicShell>
      <div className="page collection-page">
        <section className="library-hero">
          <span className="library-folder skeleton" />
          <div>
            <h1 className="skeleton" style={{ height: 28, width: 160 }} />
            <p className="skeleton skeleton-text" style={{ width: 240 }} />
            <div className="meta skeleton" style={{ height: 14, width: 100, display: "inline-block" }} />
          </div>
        </section>
        <h2 className="subheading skeleton" style={{ height: 20, width: 100 }} />
        <section className="collection-grid">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="collection-card" style={{ background: "transparent", border: "1px solid var(--line)" }}>
              <div className="cover skeleton" style={{ borderRadius: 0 }} />
              <strong className="skeleton" style={{ height: 14, width: "70%", display: "block", margin: "12px 12px 0" }} />
              <span className="skeleton" style={{ height: 12, width: "50%", display: "block", margin: "6px 12px 0" }} />
            </div>
          ))}
        </section>
        <SiteFooter />
      </div>
    </PublicShell>
  );
}
