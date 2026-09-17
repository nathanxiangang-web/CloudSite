import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_PARSER_EVALUATION_CASES,
  parseCandidateResult,
  parserCandidateListPath,
  parserCandidateRetryPath,
  parserCandidateStatusLabel,
} from "../src/lib/parser-candidates.ts";

test("candidate list path carries only explicit encoded filters and bounds", () => {
  assert.equal(parserCandidateListPath(), "/api/admin/parser-candidates");
  assert.equal(parserCandidateListPath({ status: "failed", resourceId: "r a/", limit: 20, offset: 5 }), "/api/admin/parser-candidates?status=failed&resource_id=r+a%2F&limit=20&offset=5");
});

test("candidate retry path encodes task IDs", () => {
  assert.equal(parserCandidateRetryPath("pt_a b/"), "/api/admin/parser-candidates/pt_a%20b%2F/retry");
});

test("candidate result parser fails closed for malformed or non-object JSON", () => {
  assert.deepEqual(parseCandidateResult('{"version":"1.0"}'), { version: "1.0" });
  assert.equal(parseCandidateResult("[]"), null);
  assert.equal(parseCandidateResult("broken"), null);
  assert.equal(parseCandidateResult(null), null);
});

test("candidate status labels stay distinct", () => {
  assert.equal(parserCandidateStatusLabel("pending"), "待处理");
  assert.equal(parserCandidateStatusLabel("completed"), "已完成");
  assert.equal(parserCandidateStatusLabel("failed"), "失败");
});

test("default evaluation fixtures cover hyphen, Chinese, mixed versions, and unknowns", () => {
  assert.ok(DEFAULT_PARSER_EVALUATION_CASES.some((item) => item.name.includes("x86-64")));
  assert.ok(DEFAULT_PARSER_EVALUATION_CASES.some((item) => /[\u4e00-\u9fff]/u.test(item.name)));
  assert.ok(DEFAULT_PARSER_EVALUATION_CASES.some((item) => "version" in item.expected && item.expected.version === "2026.09.10"));
  assert.ok(DEFAULT_PARSER_EVALUATION_CASES.some((item) => "platform" in item.expected && item.expected.platform === "unknown"));
});
