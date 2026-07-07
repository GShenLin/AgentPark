const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

function usage() {
  console.error("Usage: node Scripts/MarkdownToPdf.js <input.md> [output.pdf] [--keep-html]");
  process.exit(1);
}

const args = process.argv.slice(2);
if (args.length < 1) usage();

const inputPath = path.resolve(args[0]);
const keepHtml = args.includes("--keep-html");
const outputArg = args.find((arg, index) => index > 0 && !arg.startsWith("--"));
const outputPdf = path.resolve(outputArg || inputPath.replace(/\.md$/i, ".pdf"));
const outputHtml = outputPdf.replace(/\.pdf$/i, ".html");

if (!fs.existsSync(inputPath)) {
  console.error(`Input file does not exist: ${inputPath}`);
  process.exit(1);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inline(text) {
  let escaped = escapeHtml(text);
  escaped = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  escaped = escaped.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label, href) => {
    return `<a href="${escapeHtml(href)}">${escapeHtml(label)}</a>`;
  });
  return escaped;
}

function isTableSeparator(line) {
  return /^\s*\|?[\s:|-]+\|[\s:|-]+\|?\s*$/.test(line);
}

function splitTableRow(line) {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map((cell) => cell.trim());
}

function markdownToHtml(markdown, title) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const body = [];
  let paragraph = [];
  let list = [];

  function flushParagraph() {
    if (paragraph.length) {
      body.push(`<p>${inline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  }

  function flushList() {
    if (list.length) {
      body.push("<ul>");
      for (const item of list) body.push(`<li>${inline(item)}</li>`);
      body.push("</ul>");
      list = [];
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (/^```/.test(line.trim())) {
      flushParagraph();
      flushList();
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        code.push(lines[i]);
        i++;
      }
      body.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      body.push(`<h${level}>${inline(heading[2].trim())}</h${level}>`);
      continue;
    }

    if (i + 1 < lines.length && line.includes("|") && isTableSeparator(lines[i + 1])) {
      flushParagraph();
      flushList();
      const headers = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      i--;
      body.push("<table>");
      body.push("<thead><tr>" + headers.map((h) => `<th>${inline(h)}</th>`).join("") + "</tr></thead>");
      body.push("<tbody>");
      for (const row of rows) {
        body.push("<tr>" + row.map((cell) => `<td>${inline(cell)}</td>`).join("") + "</tr>");
      }
      body.push("</tbody></table>");
      continue;
    }

    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      list.push(bullet[1].trim());
      continue;
    }

    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<style>
@page { size: A4; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body {
  font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
  color: #172033;
  line-height: 1.55;
  font-size: 11px;
}
h1, h2, h3, h4 { color: #0f172a; page-break-after: avoid; }
h1 { font-size: 26px; border-bottom: 2px solid #1f2937; padding-bottom: 8px; margin: 0 0 18px; }
h2 { font-size: 18px; margin: 22px 0 10px; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; }
h3 { font-size: 14px; margin: 16px 0 8px; }
h4 { font-size: 12px; margin: 14px 0 6px; }
p { margin: 7px 0; }
ul { margin: 7px 0 7px 18px; padding: 0; }
li { margin: 3px 0; }
code {
  font-family: Consolas, "Cascadia Mono", monospace;
  background: #f1f5f9;
  color: #0f172a;
  padding: 1px 4px;
  border-radius: 3px;
}
pre {
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px;
  border-radius: 6px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
pre code { background: transparent; color: inherit; padding: 0; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0 14px;
  page-break-inside: auto;
  font-size: 9.2px;
}
tr { page-break-inside: avoid; page-break-after: auto; }
th, td {
  border: 1px solid #cbd5e1;
  padding: 4px 5px;
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { background: #e2e8f0; color: #0f172a; font-weight: 700; }
a { color: #075985; text-decoration: none; }
</style>
</head>
<body>
${body.join("\n")}
</body>
</html>`;
}

function findBrowser() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate));
}

const markdown = fs.readFileSync(inputPath, "utf8");
const html = markdownToHtml(markdown, path.basename(inputPath, path.extname(inputPath)));
fs.writeFileSync(outputHtml, html, "utf8");

const browser = findBrowser();
if (!browser) {
  console.error("Could not find Edge or Chrome. HTML was generated:");
  console.error(outputHtml);
  process.exit(1);
}

if (fs.existsSync(outputPdf)) fs.rmSync(outputPdf, { force: true });
const htmlUri = new URL(`file://${outputHtml.replace(/\\/g, "/")}`).href;
const result = spawnSync(
  browser,
  [
    "--headless",
    "--disable-gpu",
    `--print-to-pdf=${outputPdf}`,
    "--no-pdf-header-footer",
    htmlUri,
  ],
  { stdio: "inherit" }
);

if (result.status !== 0) {
  console.error(`PDF generation failed with exit code ${result.status}`);
  process.exit(result.status || 1);
}

for (let i = 0; i < 50 && !fs.existsSync(outputPdf); i++) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
}

if (!fs.existsSync(outputPdf)) {
  console.error(`PDF was not created: ${outputPdf}`);
  process.exit(1);
}

if (!keepHtml) fs.rmSync(outputHtml, { force: true });
console.log(`PDF: ${outputPdf}`);
if (keepHtml) console.log(`HTML: ${outputHtml}`);
