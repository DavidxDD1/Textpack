"use strict";
const $ = id => document.getElementById(id);
let revision = 0;
let lastAnalyzed = -1;
let busy = false;
let filename = "notes";
let sourceText = "";
const bytes = n => `${n.toLocaleString("en-US")} B`;

function setText(value) {
  // Keep imported CRLF/BOM bytes until the user edits the textarea.
  sourceText = value;
  $("text").value = value;
}

function status(message, kind = "") {
  $("status").textContent = message;
  $("status").className = `status ${kind}`;
}
function edited() {
  revision++;
  $("char-count").textContent = `${Array.from(sourceText).length.toLocaleString()} 个字符`;
  $("download").disabled = true;
  $("verified").textContent = "需要重新分析";
  status("内容已更改，点击“分析与检索”更新结果。", "pending");
}
function setBusy(value) {
  busy = value;
  for (const id of ["analyze", "sample", "clear", "text-file", "archive-file", "text", "pattern"]) $(id).disabled = value;
  $("analyze").textContent = value ? "正在处理…" : "分析与检索 ↗";
  $("download").disabled = value || lastAnalyzed !== revision;
}
async function api(path, body, binary = false) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": binary ? "application/octet-stream" : "application/json"}, body: binary ? body : JSON.stringify(body)});
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || `请求失败：${response.status}`);
  }
  return response;
}
function renderRows(id, rows) {
  const container = $(id);
  container.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = String(cell);
      tr.append(td);
    }
    container.append(tr);
  }
}
function preview(text, pattern, positions) {
  // Python offsets count Unicode code points; JS string offsets count UTF-16 units.
  const characters = Array.from(text).slice(0, 4000);
  const width = Array.from(pattern).length;
  const intervals = [];
  for (const start of positions.slice(0, 80)) {
    if (start >= characters.length) break;
    const end = Math.min(characters.length, start + width);
    const last = intervals[intervals.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else intervals.push([start, end]);
  }
  const container = $("preview");
  container.replaceChildren();
  let cursor = 0;
  for (const [start, end] of intervals) {
    container.append(document.createTextNode(characters.slice(cursor, start).join("")));
    const mark = document.createElement("mark");
    mark.textContent = characters.slice(start, end).join("");
    container.append(mark);
    cursor = end;
  }
  container.append(document.createTextNode(characters.slice(cursor).join("")));
  if (!text) container.textContent = "空文本";
}
function render(result, text, pattern) {
  const c = result.compression;
  $("saving").textContent = c.saving_percent === null ? "不适用" : `${c.saving_percent.toFixed(2)}%`;
  $("saving-note").textContent = !c.original_bytes ? "空文本仍生成 18 B 的合法文件头。" : c.saving_percent < 0 ? "本次打包变大：元数据开销高于编码收益。" : "已计入元数据开销；此结果来自实际生成的文件。";
  $("original-size").textContent = bytes(c.original_bytes);
  $("archive-size").textContent = bytes(c.archive_bytes);
  $("payload-size").textContent = `${bytes(c.payload_bytes)} / ${c.payload_bits.toLocaleString()} bit`;
  $("metadata-size").textContent = bytes(c.metadata_bytes);
  $("average-bits").textContent = `${c.average_bits.toFixed(3)} bit/字节`;
  $("crc").textContent = c.crc32;
  $("verified").textContent = result.roundtrip_ok ? "还原校验通过" : "校验失败";
  $("match-count").textContent = `${result.match_count.toLocaleString()} 处`;
  $("result-note").textContent = !pattern ? "空模式串按约定不匹配任何位置。" : !result.match_count ? "没有找到匹配项。可修改模式串后重试。" : `共找到 ${result.match_count} 处${result.positions_truncated ? "，表格只展示前 200 处" : ""}；行、列从 1 开始。`;
  renderRows("matches", result.matches.map(m => [m.offset, `${m.line} : ${m.column}`, m.context]));
  $("prefix").textContent = `[${result.prefix.join(", ")}]${result.prefix_truncated ? "（只展示前 100 项）" : ""}`;
  $("symbol-count").textContent = `${c.unique_bytes} 种字节`;
  renderRows("codes", c.codebook.map(row => [row.label, row.frequency, row.code, row.length]));
  $("merges").textContent = c.merges.length ? c.merges.map((m, i) => `${i + 1}. ${m.left} + ${m.right} → ${m.sum}`).join("\n") : "少于两个符号，无需合并。";
  preview(text, pattern, result.positions);
}
async function analyze() {
  if (busy) return;
  const ownRevision = revision;
  const text = sourceText;
  const pattern = $("pattern").value;
  setBusy(true);
  status("正在检索、压缩，并执行还原比较…", "pending");
  try {
    const result = await (await api("/api/analyze", {text, pattern})).json();
    if (ownRevision !== revision) {
      status("处理期间内容已更改，请重新分析。", "pending");
      return;
    }
    render(result, text, pattern);
    lastAnalyzed = ownRevision;
    status(`分析完成 · 找到 ${result.match_count} 处匹配 · 压缩后还原与原始 UTF-8 字节完全一致。`);
  } catch (error) {
    status(error.message, "error");
    lastAnalyzed = -1;
  } finally { setBusy(false); }
}
async function loadSample() {
  if (busy) return;
  setBusy(true);
  try {
    const response = await fetch("/api/sample");
    if (!response.ok) throw new Error("示例文件载入失败。");
    const sample = await response.json();
    setText(sample.text);
    $("pattern").value = sample.pattern;
    filename = "study_notes";
    $("input-label").textContent = "示例：study_notes.txt（合成学习笔记）";
    edited();
    setBusy(false);
    await analyze();
  } catch (error) { status(error.message, "error"); }
  finally { setBusy(false); }
}
$("text").addEventListener("input", () => { sourceText = $("text").value; edited(); });
$("pattern").addEventListener("input", edited);
$("analyze").addEventListener("click", analyze);
$("sample").addEventListener("click", loadSample);
$("clear").addEventListener("click", () => { setText(""); $("input-label").textContent = "新建文本"; filename = "notes"; edited(); });
$("text-file").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file) return;
  setBusy(true);
  try {
    if (file.size > 1024 * 1024) throw new Error("文本文件超过 1 MiB 上限。");
    setText(new TextDecoder("utf-8", {fatal: true, ignoreBOM: true}).decode(await file.arrayBuffer()));
    filename = file.name.replace(/\.[^.]*$/, "") || "notes";
    $("input-label").textContent = `已导入：${file.name}`;
    edited();
    setBusy(false);
    await analyze();
  } catch (error) { status(`导入失败：${error.message}`, "error"); }
  finally { setBusy(false); }
  event.target.value = "";
});
$("download").addEventListener("click", async () => {
  if (busy || lastAnalyzed !== revision) return;
  setBusy(true);
  try {
    const response = await api("/api/compress", {text: sourceText});
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `${filename}.tpk`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status(`压缩文件已生成：${blob.size.toLocaleString()} B。可以用“还原 .tpk 文件”重新导入。`);
  } catch (error) { status(error.message, "error"); }
  finally { setBusy(false); }
});
$("archive-file").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file || busy) return;
  setBusy(true);
  try {
    if (file.size > 2 * 1024 * 1024 + 4096) throw new Error("压缩文件超过界面限制。");
    const result = await (await api("/api/decompress", await file.arrayBuffer(), true)).json();
    setText(result.text);
    filename = file.name.replace(/\.tpk$/i, "") || "restored";
    $("input-label").textContent = `已还原：${file.name} · CRC32 校验通过`;
    edited();
    setBusy(false);
    await analyze();
  } catch (error) { status(`还原失败：${error.message}`, "error"); }
  finally { setBusy(false); event.target.value = ""; }
});
loadSample();
