import assert from "node:assert/strict";
import test from "node:test";

type SuggestionKind = "new_entry" | "new_release" | "asset" | "candidate_duplicate" | "conflict";
type SuggestionStatus = "pending" | "reviewed" | "applied" | "rejected";

const KINDS: SuggestionKind[] = ["new_entry", "new_release", "asset", "candidate_duplicate", "conflict"];
const STATUSES: SuggestionStatus[] = ["pending", "reviewed", "applied", "rejected"];

const kindTabs: { kind: SuggestionKind | "all"; label: string }[] = [
  { kind: "all", label: "全部" },
  { kind: "new_entry", label: "新建条目" },
  { kind: "new_release", label: "新建版本" },
  { kind: "asset", label: "补充资产" },
  { kind: "candidate_duplicate", label: "候选重复" },
  { kind: "conflict", label: "冲突" },
];

const kindLabel: Record<SuggestionKind, string> = {
  new_entry: "新建条目",
  new_release: "新建版本",
  asset: "补充资产",
  candidate_duplicate: "候选重复",
  conflict: "冲突",
};

const statusLabel: Record<SuggestionStatus, string> = {
  pending: "待审核",
  reviewed: "已审核",
  applied: "已应用",
  rejected: "已拒绝",
};

type BatchResultItem = {
  suggestion_id: string;
  success: boolean;
  error: string;
  entry_id: string | null;
  release_id: string | null;
  asset_id: string | null;
};

type BatchResult = { results: BatchResultItem[]; succeeded: number; failed: number };

function classifyBatchResult(result: BatchResult) {
  const successItems = result.results.filter((r) => r.success);
  const failureItems = result.results.filter((r) => !r.success);
  return {
    successItems,
    failureItems,
    totalShown: result.results.length,
    succeededMatchesCount: successItems.length === result.succeeded,
    failedMatchesCount: failureItems.length === result.failed,
  };
}

function confidenceLabel(value: number): string {
  if (value >= 0.7) return "高";
  if (value >= 0.5) return "中";
  return "低";
}

function shortId(value: string | null): string {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}


test("工作台五类分区 Tab 覆盖所有建议类型加全部", () => {
  assert.equal(kindTabs.length, 6);
  assert.equal(kindTabs[0].kind, "all");
  const tabKinds = kindTabs.slice(1).map((t) => t.kind);
  assert.deepEqual(tabKinds.sort(), [...KINDS].sort());
  for (const tab of kindTabs) {
    assert.ok(tab.label.length > 0, `Tab ${tab.kind} 缺少 label`);
  }
});


test("每个建议类型有唯一 Tab 且 label 与 kindLabel 一致", () => {
  const seen = new Set<string>();
  for (const tab of kindTabs) {
    assert.ok(!seen.has(tab.kind), `重复 Tab kind: ${tab.kind}`);
    seen.add(tab.kind);
  }
  for (const kind of KINDS) {
    const tab = kindTabs.find((t) => t.kind === kind);
    assert.ok(tab, `缺少 ${kind} Tab`);
    assert.equal(tab!.label, kindLabel[kind], `${kind} Tab label 与 kindLabel 不一致`);
  }
});


test("状态标签覆盖全部四种状态", () => {
  for (const status of STATUSES) {
    assert.ok(statusLabel[status].length > 0, `状态 ${status} 缺少 label`);
  }
  assert.equal(Object.keys(statusLabel).length, 4);
});


test("批量结果逐项展示：成功与失败分离且计数一致", () => {
  const result: BatchResult = {
    results: [
      { suggestion_id: "cs_a", success: true, error: "", entry_id: "ce_1", release_id: "cr_1", asset_id: "ca_1" },
      { suggestion_id: "cs_b", success: false, error: "建议不存在", entry_id: null, release_id: null, asset_id: null },
      { suggestion_id: "cs_c", success: true, error: "", entry_id: "ce_2", release_id: "cr_2", asset_id: "ca_2" },
    ],
    succeeded: 2,
    failed: 1,
  };
  const classified = classifyBatchResult(result);
  assert.equal(classified.successItems.length, 2);
  assert.equal(classified.failureItems.length, 1);
  assert.equal(classified.totalShown, 3);
  assert.equal(classified.succeededMatchesCount, true);
  assert.equal(classified.failedMatchesCount, true);
});


test("批量结果不伪装全批成功：失败项保留 error 且 entry_id 为 null", () => {
  const result: BatchResult = {
    results: [
      { suggestion_id: "cs_ok", success: true, error: "", entry_id: "ce_1", release_id: null, asset_id: null },
      { suggestion_id: "cs_fail", success: false, error: "状态无效", entry_id: null, release_id: null, asset_id: null },
    ],
    succeeded: 1,
    failed: 1,
  };
  const classified = classifyBatchResult(result);
  assert.equal(classified.failureItems[0].error, "状态无效");
  assert.equal(classified.failureItems[0].entry_id, null);
  assert.ok(result.succeeded < result.results.length, "不应伪装全批成功");
});


test("批量全成功时无失败项", () => {
  const result: BatchResult = {
    results: [
      { suggestion_id: "cs_a", success: true, error: "", entry_id: "ce_1", release_id: "cr_1", asset_id: "ca_1" },
      { suggestion_id: "cs_b", success: true, error: "", entry_id: "ce_2", release_id: "cr_2", asset_id: "ca_2" },
    ],
    succeeded: 2,
    failed: 0,
  };
  const classified = classifyBatchResult(result);
  assert.equal(classified.failureItems.length, 0);
  assert.equal(classified.successItems.length, 2);
});


test("批量单项失败不阻塞其他项：混合结果完整展示", () => {
  const result: BatchResult = {
    results: [
      { suggestion_id: "cs_1", success: true, error: "", entry_id: "ce_1", release_id: null, asset_id: null },
      { suggestion_id: "cs_2", success: false, error: "已拒绝", entry_id: null, release_id: null, asset_id: null },
      { suggestion_id: "cs_3", success: true, error: "", entry_id: "ce_3", release_id: null, asset_id: null },
      { suggestion_id: "cs_4", success: false, error: "不存在", entry_id: null, release_id: null, asset_id: null },
    ],
    succeeded: 2,
    failed: 2,
  };
  const classified = classifyBatchResult(result);
  assert.equal(classified.totalShown, 4);
  assert.equal(classified.successItems.length, 2);
  assert.equal(classified.failureItems.length, 2);
  assert.deepEqual(
    classified.failureItems.map((r) => r.error),
    ["已拒绝", "不存在"],
  );
});


test("置信度标签分级正确", () => {
  assert.equal(confidenceLabel(0.8), "高");
  assert.equal(confidenceLabel(0.7), "高");
  assert.equal(confidenceLabel(0.69), "中");
  assert.equal(confidenceLabel(0.5), "中");
  assert.equal(confidenceLabel(0.49), "低");
  assert.equal(confidenceLabel(0.3), "低");
});


test("短 ID 显示截断长 ID 保留短 ID 原样", () => {
  assert.equal(shortId(null), "—");
  assert.equal(shortId("short"), "short");
  const longId = "cs_aaaaaaaaaaaaaaaa111111112222345678";
  const short = shortId(longId);
  assert.ok(short.length < longId.length);
  assert.ok(short.startsWith("cs_aaaaa"));
  assert.ok(short.endsWith("345678"));
});
