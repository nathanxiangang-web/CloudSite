export type SubmissionStatus = "pending" | "approved" | "rejected" | "published";

export type ReviewAction = "approve" | "reject" | "publish";

export type ReviewPayload = { action: ReviewAction; admin_note: string; resource_id?: string };

export function canPublishSubmission(status: SubmissionStatus): boolean {
  return status === "approved";
}

export function defaultReviewAction(status: SubmissionStatus): ReviewAction {
  if (status === "approved") return "publish";
  if (status === "rejected") return "reject";
  return "approve";
}

export function isPublishReady(action: ReviewAction, resourceId: string): boolean {
  if (action !== "publish") return true;
  return resourceId.trim().length > 0;
}

export function buildReviewPayload(action: ReviewAction, adminNote: string, resourceId: string): ReviewPayload {
  const payload: ReviewPayload = { action, admin_note: adminNote };
  if (action === "publish") {
    payload.resource_id = resourceId.trim();
  }
  return payload;
}

export function publishedResultHref(
  status: SubmissionStatus,
  publishedResourceId: string | null | undefined,
): string | null {
  if (status !== "published") return null;
  if (!publishedResourceId) return null;
  const trimmed = publishedResourceId.trim();
  if (!trimmed) return null;
  return `/resource/${encodeURIComponent(trimmed)}`;
}
