import fs from "node:fs/promises";
import path from "node:path";
// The bundled artifact runtime stays under .codex_spreadsheet while all
// experiment runners live in this directory.
import { SpreadsheetFile, Workbook } from "../.codex_spreadsheet/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";


const [jsonPath, xlsxPath, previewPath] = process.argv.slice(2);
if (!jsonPath || !xlsxPath || !previewPath) {
  throw new Error("Usage: node build_stress_scale_xlsx.mjs rows.json output.xlsx preview.png");
}

const rows = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const columns = [
  ["|I| Disaster", "I"],
  ["|J| CCP", "J"],
  ["|H| Hosp", "H"],
  ["|S| Scen", "S"],
  ["|T| Per", "T"],
  ["obj_value", "obj_value"],
  ["First Stage Decision", "first_stage_decision"],
  ["Best LB", "best_lb"],
  ["Best UB", "best_ub"],
  ["CPU Time(s)", "cpu_s"],
  ["num_vars", "num_vars"],
  ["num_constrs", "num_constrs"],
  ["Nodes", "nodes"],
  ["Iteration", "iterations"],
  ["Final Gap(%)", "gap_pct"],
  ["VSS(%)", "vss_pct"],
  ["EVPI(%)", "evpi_pct"],
  ["Total Cuts", "total_cuts"],
  ["Seed Cuts", "seed_cuts"],
  ["Lazy Cuts", "lazy_cuts"],
  ["User Cuts", "user_cuts"],
  ["Root Seed Iters", "root_seed_iters_done"],
  ["Seeded LB", "root_seed_lb"],
  ["Root Seed Time(s)", "root_seed_time_s"],
  ["Root Cut Rounds", "root_cut_rounds_done"],
  ["Oracle Solves", "oracle_solves"],
  ["Callback Time(s)", "callback_time_s"],
];

const intKeys = new Set([
  "I", "J", "H", "S", "T", "num_vars", "num_constrs", "nodes", "iterations",
  "total_cuts", "seed_cuts", "lazy_cuts", "user_cuts", "root_seed_iters_done",
  "root_cut_rounds_done", "oracle_solves",
]);
const textKeys = new Set(["first_stage_decision"]);

function typed(value, key) {
  if (value === null || value === undefined || value === "NA" || value === "") return null;
  if (textKeys.has(key)) return String(value);
  const n = Number(value);
  if (Number.isFinite(n)) return intKeys.has(key) ? Math.trunc(n) : n;
  return String(value);
}

function colName(index) {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    n -= 1;
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26);
  }
  return out;
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Results");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);

const matrix = [
  columns.map(([title]) => title),
  ...rows.map((row) => columns.map(([, key]) => typed(row[key], key))),
];
const lastCol = colName(columns.length - 1);
const lastRow = Math.max(1, matrix.length);
sheet.getRange(`A1:${lastCol}${lastRow}`).values = matrix;

const header = sheet.getRange(`A1:${lastCol}1`);
header.format = {
  fill: "#2E75B6",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#1F4E78" },
};
sheet.getRange("O1:Q1").format.fill = "#E60000";
header.format.rowHeight = 34;

if (lastRow >= 2) {
  const body = sheet.getRange(`A2:${lastCol}${lastRow}`);
  body.format = {
    verticalAlignment: "top",
    borders: {
      insideHorizontal: { style: "thin", color: "#D9E2F3" },
      bottom: { style: "thin", color: "#9EADBA" },
    },
  };
  sheet.getRange(`A2:E${lastRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`F2:F${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`H2:J${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`K2:N${lastRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`O2:Q${lastRow}`).format.numberFormat = "0.0000";
  sheet.getRange(`R2:V${lastRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`W2:X${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`Y2:Y${lastRow}`).format.numberFormat = "#,##0";
  sheet.getRange(`Z2:AA${lastRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`G2:G${lastRow}`).format.wrapText = true;
  sheet.getRange(`G2:G${lastRow}`).format.autofitRows();
}

sheet.getRange(`A1:${lastCol}${lastRow}`).format.autofitColumns();
sheet.getRange(`A1:E${lastRow}`).format.columnWidth = 12;
sheet.getRange(`F1:F${lastRow}`).format.columnWidth = 16;
sheet.getRange(`G1:G${lastRow}`).format.columnWidth = 54;
sheet.getRange(`H1:J${lastRow}`).format.columnWidth = 16;
sheet.getRange(`K1:AA${lastRow}`).format.columnWidth = 13;

const inspected = await workbook.inspect({
  kind: "table",
  range: `Results!A1:${lastCol}${Math.min(lastRow, 5)}`,
  include: "values,formulas",
  tableMaxRows: 5,
  tableMaxCols: columns.length,
  maxChars: 5000,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

await fs.mkdir(path.dirname(xlsxPath), { recursive: true });
const preview = await workbook.render({
  sheetName: "Results",
  range: `A1:${lastCol}${Math.min(lastRow, 5)}`,
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);
console.log(`[xlsx] saved: ${xlsxPath}`);
console.log(`[xlsx] inspected ${columns.length} columns; error scan: ${errors.ndjson}`);
console.log(inspected.ndjson);
