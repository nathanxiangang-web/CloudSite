const MAX_XLSX_BYTES = 25 * 1024 * 1024;
const MAX_XLSX_SHEETS = 10;
const MAX_XLSX_ROWS = 200;
const MAX_XLSX_COLS = 50;
const MAX_XML_CHARS = 5_000_000;

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] as string
  ));
}

function decodeXmlEntities(value: string): string {
  return value.replace(
    /&#x([0-9a-f]+);|&#([0-9]+);|&(amp|lt|gt|quot|apos);/gi,
    (_match, hex, dec, named) => {
      if (hex) return String.fromCodePoint(Number.parseInt(hex, 16));
      if (dec) return String.fromCodePoint(Number.parseInt(dec, 10));
      return ({ amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" } as Record<string, string>)[
        String(named).toLowerCase()
      ] ?? "";
    },
  );
}

function attribute(attrs: string, name: string): string {
  const match = new RegExp(name + "\\s*=\\s*[\"']([^\"']*)[\"']", "i").exec(attrs);
  return match ? decodeXmlEntities(match[1]) : "";
}

function textNodes(xml: string): string {
  return [...xml.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/gi)]
    .map((match) => decodeXmlEntities(match[1]))
    .join("");
}

function columnIndex(cellRef: string): number {
  const letters = /^([A-Z]+)/i.exec(cellRef)?.[1]?.toUpperCase() ?? "";
  let value = 0;
  for (const letter of letters) value = value * 26 + letter.charCodeAt(0) - 64;
  return Math.max(0, value - 1);
}

export function parseSharedStrings(xml: string): string[] {
  if (xml.length > MAX_XML_CHARS) throw new Error("XLSX shared strings too large to preview");
  return [...xml.matchAll(/<si(?:\s[^>]*)?>([\s\S]*?)<\/si>/gi)]
    .map((match) => textNodes(match[1]));
}

export function parseWorksheetXml(xml: string, sharedStrings: string[]): string[][] {
  if (xml.length > MAX_XML_CHARS) throw new Error("XLSX worksheet too large to preview");
  const rows: string[][] = [];
  for (const rowMatch of xml.matchAll(/<row(?:\s[^>]*)?>([\s\S]*?)<\/row>/gi)) {
    if (rows.length >= MAX_XLSX_ROWS) break;
    const values: string[] = [];
    for (const cellMatch of rowMatch[1].matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/gi)) {
      const attrs = cellMatch[1];
      const body = cellMatch[2];
      const ref = attribute(attrs, "r");
      const index = ref ? columnIndex(ref) : values.length;
      if (index >= MAX_XLSX_COLS) continue;

      const type = attribute(attrs, "t");
      const raw = /<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/i.exec(body)?.[1] ?? "";
      let value = decodeXmlEntities(raw);

      if (type === "s") {
        const sharedIndex = Number.parseInt(raw, 10);
        value = Number.isFinite(sharedIndex) ? (sharedStrings[sharedIndex] ?? "") : "";
      } else if (type === "inlineStr") {
        value = textNodes(body);
      } else if (type === "b") {
        value = raw === "1" ? "TRUE" : "FALSE";
      }
      values[index] = value;
    }
    rows.push(values);
  }
  return rows;
}

function worksheetHtml(name: string, rows: string[][]): string {
  const width = Math.min(
    MAX_XLSX_COLS,
    Math.max(1, ...rows.map((row) => row.reduce((max, value, index) => value !== undefined ? index + 1 : max, 0))),
  );
  const body = rows.length
    ? rows.map((row) =>
        `<tr>${Array.from({ length: width }, (_, index) => `<td>${escapeHtml(row[index] ?? "")}</td>`).join("")}</tr>`
      ).join("")
    : '<tr><td>（工作表为空）</td></tr>';
  return `<div class="xlsx-sheet"><h4>${escapeHtml(name)}</h4><table><tbody>${body}</tbody></table></div>`;
}

function normalizeWorksheetTarget(target: string): string {
  if (target.startsWith("/")) return target.slice(1);
  if (target.startsWith("xl/")) return target;
  return `xl/${target.replace(/^\.\//, "")}`;
}

export async function renderXlsxWorkbook(arrayBuffer: ArrayBuffer): Promise<string> {
  if (arrayBuffer.byteLength > MAX_XLSX_BYTES) {
    throw new Error("电子表格过大，浏览器内预览已停止，请下载后查看。");
  }

  const JSZip = (await import("jszip")).default;
  const zip = await JSZip.loadAsync(arrayBuffer);
  const workbookFile = zip.file("xl/workbook.xml");
  if (!workbookFile) throw new Error("无效的 XLSX 文件：缺少 workbook.xml");

  const workbookXml = await workbookFile.async("text");
  const relationshipsXml = await zip.file("xl/_rels/workbook.xml.rels")?.async("text") ?? "";
  const sharedStringsXml = await zip.file("xl/sharedStrings.xml")?.async("text") ?? "";
  const sharedStrings = sharedStringsXml ? parseSharedStrings(sharedStringsXml) : [];

  const relationshipTargets = new Map<string, string>();
  for (const match of relationshipsXml.matchAll(/<Relationship\b([^>]*)\/?\s*>/gi)) {
    const id = attribute(match[1], "Id");
    const target = attribute(match[1], "Target");
    if (id && target) relationshipTargets.set(id, normalizeWorksheetTarget(target));
  }

  const declaredSheets = [...workbookXml.matchAll(/<sheet\b([^>]*)\/?\s*>/gi)]
    .slice(0, MAX_XLSX_SHEETS)
    .map((match, index) => ({
      name: attribute(match[1], "name") || `Sheet ${index + 1}`,
      relationId: attribute(match[1], "r:id"),
    }));

  const fallbackFiles = Object.keys(zip.files)
    .filter((name) => /^xl\/worksheets\/sheet\d+\.xml$/i.test(name))
    .sort((a, b) => {
      const ai = Number(/sheet(\d+)\.xml$/i.exec(a)?.[1] ?? 0);
      const bi = Number(/sheet(\d+)\.xml$/i.exec(b)?.[1] ?? 0);
      return ai - bi;
    });

  const html: string[] = [];
  const sheetCount = Math.min(MAX_XLSX_SHEETS, Math.max(declaredSheets.length, fallbackFiles.length));
  for (let index = 0; index < sheetCount; index += 1) {
    const declared = declaredSheets[index];
    const path = declared?.relationId ? relationshipTargets.get(declared.relationId) : undefined;
    const file = zip.file(path || fallbackFiles[index] || "");
    if (!file) continue;
    const xml = await file.async("text");
    html.push(worksheetHtml(declared?.name || `Sheet ${index + 1}`, parseWorksheetXml(xml, sharedStrings)));
  }

  return html.length ? html.join("") : "<p>未能在该电子表格中提取到数据。</p>";
}
