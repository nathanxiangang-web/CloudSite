import { PublicShell } from "@/components/PublicShell";

export default function Loading() {
  return (
    <PublicShell>
      <div className="page search-page">
        <h1 className="skeleton" style={{ height: 28, width: 120 }} />
        <p className="search-lead skeleton" style={{ height: 14, width: 280 }} />
        <form className="skeleton" style={{ height: 58, width: "100%", borderRadius: 14, display: "block" }} />
        <div className="search-toolbar">
          <div className="search-filters">
            {Array.from({ length: 5 }).map((_, i) => <span key={i} className="skeleton" style={{ height: 34, width: 60, display: "inline-block", borderRadius: 999 }} />)}
          </div>
        </div>
        <p className="result-summary skeleton" style={{ height: 14, width: 200 }} />
        <section className="search-results">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="search-result-card" style={{ minHeight: 76 }}>
              <span className="search-result-icon skeleton" />
              <div className="search-result-copy" style={{ flex: 1 }}>
                <strong className="skeleton" style={{ height: 14, width: "60%", display: "block" }} />
                <small className="skeleton" style={{ height: 12, width: "40%", display: "block", marginTop: 6 }} />
              </div>
            </div>
          ))}
        </section>
      </div>
    </PublicShell>
  );
}
