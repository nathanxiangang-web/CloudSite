import { PublicShell } from "@/components/PublicShell";

export default function Loading() {
  return (
    <PublicShell>
      <div className="page library-page">
        <nav className="breadcrumb"><span className="skeleton" style={{ width: 120, height: 14, display: "inline-block" }} /></nav>
        <section className="library-hero">
          <span className="library-folder skeleton" />
          <div>
            <h1 className="skeleton" style={{ height: 28, width: 200 }} />
            <p className="skeleton skeleton-text" style={{ width: 280 }} />
            <div className="meta skeleton" style={{ height: 14, width: 160, display: "inline-block" }} />
          </div>
        </section>
        <h2 className="subheading skeleton" style={{ height: 20, width: 100 }} />
        <section className="folder-grid">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="folder-card skeleton" />)}
        </section>
        <h2 className="subheading skeleton" style={{ height: 20, width: 80 }} />
        <section className="resource-grid">
          {Array.from({ length: 9 }).map((_, i) => <div key={i} className="resource-card skeleton" style={{ minHeight: 88, borderRadius: 12 }} />)}
        </section>
      </div>
    </PublicShell>
  );
}
