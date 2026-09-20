import { PublicShell } from "@/components/PublicShell";

export default function Loading() {
  return (
    <PublicShell>
      <div className="page detail-page">
        <nav className="breadcrumb"><span className="skeleton" style={{ width: 120, height: 14, display: "inline-block" }} /></nav>
        <header className="resource-heading">
          <span className="skeleton" style={{ width: 80, height: 14, display: "inline-block", marginBottom: 8 }} />
          <h1 className="skeleton" style={{ height: 28, width: "70%" }} />
        </header>
        <section className="detail-grid">
          <article className="preview-panel skeleton" style={{ minHeight: 520 }} />
          <aside className="detail-meta">
            <span className="detail-icon skeleton" />
            <p className="skeleton skeleton-text" style={{ width: "80%" }} />
            <dl>
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i}><dt className="skeleton" style={{ width: 50, height: 14, display: "inline-block" }} /><dd className="skeleton" style={{ width: 90, height: 14, display: "inline-block" }} /></div>
              ))}
            </dl>
            <div className="detail-actions">
              <span className="skeleton" style={{ height: 40, width: 120, display: "inline-block" }} />
              <span className="skeleton" style={{ height: 40, width: 80, display: "inline-block" }} />
            </div>
          </aside>
        </section>
      </div>
    </PublicShell>
  );
}
