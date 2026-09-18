import assert from "node:assert/strict";
import test from "node:test";

import { parseSharedStrings, parseWorksheetXml } from "../src/lib/xlsx-preview.ts";

test("parseSharedStrings decodes plain, rich, and escaped text", () => {
  const xml = `<sst>
    <si><t>Hello &amp; world</t></si>
    <si><r><t>Rich</t></r><r><t> Text</t></r></si>
  </sst>`;
  assert.deepEqual(parseSharedStrings(xml), ["Hello & world", "Rich Text"]);
});

test("parseWorksheetXml resolves shared, inline, boolean, and sparse cells", () => {
  const xml = `<worksheet><sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="C1" t="inlineStr"><is><t>Inline</t></is></c>
      <c r="D1" t="b"><v>1</v></c>
    </row>
    <row r="2"><c r="B2"><v>42</v></c></row>
  </sheetData></worksheet>`;
  assert.deepEqual(parseWorksheetXml(xml, ["Shared"]), [
    ["Shared", undefined, "Inline", "TRUE"],
    [undefined, "42"],
  ]);
});
