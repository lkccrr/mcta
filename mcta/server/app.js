/* ---------- 语言：简体中文 / English ---------- */
const LANG = (function () {
  const q = new URLSearchParams(location.search).get("lang");
  if (q) {
    const v = q.toLowerCase();
    if (v.indexOf("en") === 0) return "en";
    if (v.indexOf("zh") === 0) return "zh";
  }
  try {
    const saved = localStorage.getItem("mcta-lang");
    if (saved === "en" || saved === "zh") return saved;
  } catch (e) { /* 隐私模式忽略 */ }
  const tag = String(navigator.language || "").toLowerCase();
  const simp = tag === "zh" || tag === "zh-cn" || tag === "zh-hans" ||
    tag.indexOf("zh-cn-") === 0 || tag.indexOf("zh-hans-") === 0 ||
    tag === "zh-sg" || tag.indexOf("zh-sg-") === 0;
  return simp ? "zh" : "en";
})();
const IS_EN = LANG === "en";
try {
  if (new URLSearchParams(location.search).get("lang")) localStorage.setItem("mcta-lang", LANG);
} catch (e) { /* 隐私模式忽略 */ }

const I18N = {
  "McTa 文件服务": "McTa File Server",
  "格塔 · Meta Crystal Toolkit & Analysis": "Meta Crystal Toolkit & Analysis",
  "运行目录": "Run directory",
  "输入路径后回车切换目录": "Enter a path, then press Enter to switch directory",
  "进入": "Enter",
  "输入路径": "Enter path",
  "回车切换目录": "Press Enter to switch directory",
  "读取中…": "Loading…",
  "正在渲染…": "Rendering…",
  "排队中，稍后重试…": "Queued, retrying…",
  "取消加载": "Cancel loading",
  "已取消加载": "Load cancelled",
  "完整轨迹已加载": "Full trajectory loaded",
  "运行账户": "Run as",
  "终端": "Terminal",
  "终端窗口": "Terminal window",
  "最小化终端": "Minimize terminal",
  "最小化": "Minimize",
  "最大化终端": "Maximize terminal",
  "还原到侧栏": "Dock to sidebar",
  "还原大小": "Restore size",
  "点击终端顶端栏可浮动为小窗口": "Click the terminal header to open a floating window",
  "已复制选中文字": "Selection copied",
  "已粘贴剪切板内容": "Pasted from clipboard",
  "剪切板为空": "Clipboard is empty",
  "无法读取剪切板": "Clipboard access denied",
  "连接中…": "Connecting…",
  "正在连接终端…": "Connecting to terminal…",
  "新建目录": "New folder",
  "新建文本": "New text file",
  "下载选中": "Download selected",
  "下载选中文件": "Download selected files",
  "浮窗": "Float",
  "浮动为小窗口": "Float as a small window",
  "还原到页面": "Dock back to page",
  "目录窗口": "Directory window",
  "点击顶栏可浮动为小窗口": "Click the header to float the directory panel",
  "点击顶栏可浮动为小窗口，再次点击还原": "Click the header to float as a small window; click again to dock",
  "点击顶栏还原到页面": "Click the header to dock back to the page",
  "目录面板已浮动": "Directory panel is now floating",
  "正在上传 ": "Uploading ",
  " 项…": " items…",
  "已上传 ": "Uploaded ",
  " 项": " items",
  "上传失败：": "Upload failed: ",
  "拖入文件或目录以上传": "Drop files or folders here to upload",
  "其他文件": "Other files",
  "名称": "Name",
  "类型": "Type",
  "大小": "Size",
  "修改时间": "Modified",
  "此目录为空": "This directory is empty",
  "许可": "License",
  "查看许可": "View license",
  "MIT License · 源码与问题反馈：": "MIT License · Source and issues:",
  "· 源码与问题反馈：": " · Source and issues:",
  "旋转": "Rotate",
  "Z轴 ▲": "Z axis ▲",
  "X 轴": "X axis",
  "Y 轴": "Y axis",
  "Z 轴": "Z axis",
  "缩放": "Zoom",
  "等值面": "Isosurface",
  "透明度": "Opacity",
  "视角：正交": "View: orthographic",
  "视角：透视": "View: perspective",
  "自适应": "Fit to view",
  "正对X": "Face X",
  "正对Y": "Face Y",
  "正对Z": "Face Z",
  "重置": "Reset",
  "左键拖动旋转 · 滚轮缩放 · 中键拖动平移": "Left-drag to rotate · scroll to zoom · middle-drag to pan",
  "保存图片": "Save image",
  "保存图片到电脑": "Save image to computer",
  "存档": "Save state",
  "选中原子": "Select atoms",
  "取消选中原子": "Exit atom selection",
  "原子坐标": "Atom coordinates",
  "分数坐标": "Fractional",
  "笛卡尔坐标 (Å)": "Cartesian (Å)",
  "应用": "Apply",
  "删除原子": "Delete atom",
  "增加原子": "Add atom",
  "元素名或符号": "Element name or symbol",
  "周期表": "Periodic table",
  "撤销": "Undo",
  "恢复": "Redo",
  "请先选择原子": "Select an atom first",
  "修改所有选中原子的元素": "Change element of all selected atoms",
  "修改此原子的元素": "Change element of this atom",
  "删除所有选中原子": "Delete all selected atoms",
  "确定删除选中的 ": "Delete ",
  " 个原子吗？此操作不可恢复。": " selected atoms? This cannot be undone.",
  "分数坐标（晶格）": "Fractional coordinates (lattice)",
  "选中原子（Shift+框选 / Ctrl+点击；按钮模式弹坐标，未进入时只高亮；Shift+方向键旋转原子，Shift+Alt+方向键移动原子）": "Select atoms (Shift+drag a box / Ctrl+click; coordinates open in selection-button mode, highlight only otherwise; Shift+Arrow rotates atoms, Shift+Alt+Arrow moves atoms)",
  "添加原子": "Add atom",
  "需要晶格信息才能按分数坐标新增原子": "A lattice is required to add atoms by fractional coordinates",
  "元素名或符号无效": "Invalid element name or symbol",
  "新增原子失败": "Failed to add atom",
  "已新增原子": "Added atom ",
  "密度显示中不可编辑原子": "Atoms cannot be edited while a density is displayed",
  "轨迹显示中不可编辑原子": "Atoms cannot be edited in trajectories",
  "密度显示中不可新增原子": "Atoms cannot be added while a density is displayed",
  "轨迹显示中不可新增原子": "Atoms cannot be added in trajectories",
  "多帧轨迹不可移动或旋转原子，仅可删除": "Atoms cannot be moved or rotated in trajectories; delete only",
  "关闭": "Close",
  "已存档": "State saved",
  "已存档 ": "Saved state ",
  "下载到电脑": "Download to computer",
  "大文本": "Large text",
  "大文本 · 只读分段加载": "Large text · read-only paged loading",
  "只读分段加载": "read-only paged loading",
  "跳转到行": "Go to line",
  "已加载": "Loaded",
  "行": "lines",
  "加载失败：": "Load failed: ",
  "尚未打开结构": "No structure is open",
  "不保存": "Don't save",
  "文件已修改": "File modified",
  "视图已调整": "3D view adjusted",
  "是否保存修改？": "Save changes?",
  "是否保存当前视图为图片？": "Save the current view as an image?",
  "是否存档修改？": "Save changes to state?",
  "是否存档当前视图？": "Save current view to state?",
  "图片格式": "Image format",
  "分辨率倍数": "Resolution scale",
  "文件名": "File name",
  "取消": "Cancel",
  "保存": "Save",
  "确认": "Confirm",
  "确定": "OK",
  "目录": "Folder",
  "文件": "File",
  "文本": "Text",
  "图片": "Image",
  "已连接": "Connected",
  "结构文件": "Structure",
  "文本 / 二进制": "Text / binary",
  "滚轮缩放 · 拖动平移": "Scroll to zoom · drag to pan",
  "下载": "Download",
  "已保存 ": "Saved ",
  "重命名 · ": "Rename · ",
  "名称不能为空": "Name cannot be empty",
  "已重命名为 ": "Renamed to ",
  "新建文本文件 · ": "New text file · ",
  "新建文本.txt": "untitled.txt",
  "输入文件名": "Enter a file name",
  "新建目录 · ": "New folder · ",
  "新建文件夹": "New folder",
  "输入目录名": "Enter a folder name",
  "请输入文件名": "Please enter a file name",
  "已创建 ": "Created ",
  "请输入目录名": "Please enter a folder name",
  "已创建目录 ": "Created folder ",
  "删除目录": "Delete folder",
  "删除文件": "Delete file",
  "确定删除 <b>": "Delete <b>",
  "</b> 吗？<br>此操作不可恢复。": "</b>?<br>This cannot be undone.",
  "删除": "Delete",
  "已删除 ": "Deleted ",
  "进入目录": "Open folder",
  "查看立体构型": "View 3D structure",
  "打开文本": "Open text",
  "查看图片": "View image",
  "打开": "Open",
  "重命名": "Rename",
  "该文件无法预览，长按可选择下载": "This file cannot be previewed; long-press to download",
  "该文件为二进制，无法在窗口中打开": "This binary file cannot be opened in the window",
  "暂停": "Pause",
  "播放": "Play",
  "静音": "Mute",
  "取消静音": "Unmute",
  "PDF": "PDF",
  "音频": "Audio",
  "视频": "Video",
  "表格": "Table",
  "Markdown": "Markdown",
  "空表格": "Empty table",
  "仅显示前 2000 行": "Only the first 2000 rows are shown",
  "当前浏览器不支持导出 ": "This browser cannot export ",
  "，请改用 PNG": "; use PNG instead",
  "已导出 ": "Exported ",
  "导出图片失败": "Failed to export image",
  "3Dmol 资源未加载，无法显示结构": "3Dmol failed to load; cannot show the structure",
  "当前浏览器不支持 WebGL，无法显示 3D 结构": "This browser does not support WebGL; cannot show the 3D structure",
  "连接中断，正在重试…": "Connection lost, retrying…",
  "已连接 · ": "Connected · ",
  "还原": "Restore",
  "放大": "Maximize",
  "缩回原始大小": "Restore original size",
  "放大到整个页面": "Maximize to full page",
  "还原弹窗": "Reset dialog",
  "关闭": "Close",
  "旋转轴": "Rotation axis",
  "旋转角度": "Rotation angle",
  "逆时针旋转": "Rotate counterclockwise",
  "顺时针旋转": "Rotate clockwise",
  "缩放比例": "Zoom step",
  "结构缩放": "Structure zoom",
  "左键平移": "Pan with left button",
  "左键平移（已开启）": "Left-button pan (on)",
  "缩小": "Zoom out",
  "恢复初始视图": "Reset view",
  "图片缩放": "Image zoom",
  "密度类型": "Density type",
  "等值面数值": "Isosurface value",
  "调节等值面": "Adjust isosurface",
  "透明度数值": "Opacity value",
  "调节透明度": "Adjust opacity",
  "上一帧": "Previous frame",
  "下一帧": "Next frame",
  "播放速度": "Playback speed",
  "清除选中": "Clear selection",
  "测量模式": "Measure mode",
  "测量模式（已开启）": "Measure mode (on)",
  "原子样式": "Atom style",
  "样式设置": "Style settings",
  "坐标轴设置": "Axis settings",
  "等值面设置": "Isosurface settings",
  "等值面": "Isosurface",
  "正值": "Positive",
  "负值": "Negative",
  "选择颜色": "Choose color",
  "色相": "Hue",
  "色相环": "Color wheel",
  "屏幕取色": "Screen color picker",
  "当前浏览器不支持屏幕取色": "Screen color picker is not supported in this browser",
  "更多设置": "More options",
  "颜色模式": "Color mode",
  "正值颜色": "Positive color",
  "负值颜色": "Negative color",
  "键与雾": "Bond & fog",
  "外观": "Appearance",
  "显示原子": "Show atoms",
  "键": "Bonds",
  "显示键": "Show bonds",
  "晶格": "Lattice",
  "晶格线宽": "Lattice line width",
  "晶格样式": "Lattice style",
  "晶格颜色": "Lattice color",
  "范围": "Range",
  "间隙": "Gap",
  "晶胞": "Cell",
  "坐标轴": "Axes",
  "轴颜色": "Axis colors",
  "深度雾": "Depth cue",
  "晶胞半径": "Cell radius",
  "晶胞虚线": "Cell dashed",
  "晶胞样式": "Cell style",
  "显示样式": "Display mode",
  "原样": "As-is",
  "内部": "Inside cell",
  "超晶胞A": "Supercell A",
  "超晶胞B": "Supercell B",
  "超晶胞C": "Supercell C",
  "超晶胞": "Supercell",
  "无": "None",
  "虚线段长": "Dash length",
  "虚线间隙": "Gap length",
  "晶胞颜色": "Cell color",
  "晶胞标记": "Cell labels (O/A/B/C)",
  "晶格标记": "Lattice labels (O/A/B/C)",
  "原子大小": "Atom size",
  "原子颜色": "Atom color",
  "显示坐标轴": "Show axes",
  "轴长度": "Axis length",
  "轴半径": "Axis radius",
  "箭头比例": "Arrow ratio",
  "轴透明度": "Axis opacity",
  "X轴颜色": "X axis color",
  "Y轴颜色": "Y axis color",
  "Z轴颜色": "Z axis color",
  "调节键粗": "Adjust bond radius",
  "调节": "Adjust ",
  "滑杆": " slider",
  "调节大小": "Adjust size",
  "键粗滑杆": "Bond radius slider",
  "大小滑杆": "Size slider",
  "颜色": "Color",
  "大小": "Size",
  "键粗": "Bond radius",
  "键颜色模式": "Bond color mode",
  "键颜色": "Bond color",
  "按元素": "By element",
  "自定义": "Custom",
  "自定义旋转角度（1-360 度）": "Custom rotation angle (1-360 degrees)",
  "旋转角度须为 1-360 度": "Rotation angle must be between 1 and 360 degrees",
  "键样式": "Bond style",
  "实线": "Solid",
  "虚线": "Dashed",
  "测量": "Measurement",
  "标注字号": "Label size",
  "标注颜色": "Label color",
  "轴标签字体": "Axis label font",
  "标注字体": "Label font",
  "虚线连线": "Dashed line",
  "连线粗细": "Line width",
  "连线颜色": "Line color",
  "恢复默认": "Reset to default"
};

/* HTML 转义：文件名等不可信文本进入 innerHTML 前必须过一遍 */
function escHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

/* ---- 浮窗预览：Markdown / 表格 / JSON / 媒体工具 ---- */
const QUICK_MD_EXTS = ["md", "markdown"];
const QUICK_TABLE_EXTS = ["csv", "tsv"];
const QUICK_TABLE_LIMIT = 2000;
let quickMedia = null;

function quickExt(name) {
  const s = String(name || "");
  const i = s.lastIndexOf(".");
  return i < 0 ? "" : s.slice(i + 1).toLowerCase();
}

function codeTextLabel(name) {
  const ext = quickExt(name);
  if (ext === "json") return "JSON";
  if (ext === "xml") return "XML";
  if (ext === "xsd") return "XSD";
  return tx("大文本");
}

function quickDockTag(data) {
  if (data.kind === "pdf") return tx("PDF");
  if (data.kind === "media") return tx(data.mediaType === "audio" ? "音频" : "视频");
  if (data.kind === "image") return tx("图片");
  if (data.kind === "largeText") return codeTextLabel(data.name);
  const ext = quickExt(data.name);
  if (QUICK_MD_EXTS.indexOf(ext) >= 0) return tx("Markdown");
  if (QUICK_TABLE_EXTS.indexOf(ext) >= 0) return tx("表格");
  if (ext === "json") return "JSON";
  if (ext === "xml") return "XML";
  if (ext === "xsd") return "XSD";
  return tx("文本");
}

function mdInline(s) {
  let t = escHtml(s);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  t = t.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  t = t.replace(/_([^_]+)_/g, "<em>$1</em>");
  t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, label, href) {
    if (!/^(https?:\/\/|mailto:|\/|#|\.\/)/i.test(href)) return m;
    return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
  });
  return t;
}

function splitMdRow(line) {
  let s = String(line || "").trim();
  if (s.charAt(0) === "|") s = s.slice(1);
  if (s.charAt(s.length - 1) === "|" && !/\\\|$/.test(s)) s = s.slice(0, -1);
  const cells = [];
  let cur = "", escaped = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (escaped) {
      if (c === "|") cur += "|";
      else cur += "\\" + c;
      escaped = false;
      continue;
    }
    if (c === "\\") { escaped = true; continue; }
    if (c === "|") { cells.push(cur.trim()); cur = ""; continue; }
    cur += c;
  }
  if (escaped) cur += "\\";
  cells.push(cur.trim());
  return cells;
}

function isMdTableSep(line) {
  if (String(line || "").indexOf("|") < 0) return false;
  const cells = splitMdRow(line);
  return cells.length > 0 && cells.every(function (c) { return /^:?-{3,}:?$/.test(c); });
}

function renderMarkdown(text) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let list = "";
  let code = false;
  function closeList() {
    if (list) { out.push("</" + list + ">"); list = ""; }
  }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      closeList();
      if (code) { out.push("</code></pre>"); code = false; }
      else { out.push("<pre><code>"); code = true; }
      continue;
    }
    if (code) { out.push(escHtml(line) + "\n"); continue; }
    if (!line.trim()) { closeList(); continue; }
    // Markdown 表格：表头行 + | --- | 分隔行 + 若干数据行。
    if (line.indexOf("|") >= 0 && i + 1 < lines.length && isMdTableSep(lines[i + 1])) {
      closeList();
      const heads = splitMdRow(line);
      out.push("<table><thead><tr>");
      heads.forEach(function (h) { out.push("<th>" + mdInline(h) + "</th>"); });
      out.push("</tr></thead><tbody>");
      i++;  // 跳过分隔行
      while (i + 1 < lines.length && lines[i + 1].indexOf("|") >= 0 && lines[i + 1].trim()) {
        i++;
        const cells = splitMdRow(lines[i]);
        out.push("<tr>");
        heads.forEach(function (_, j) { out.push("<td>" + mdInline(cells[j] || "") + "</td>"); });
        out.push("</tr>");
      }
      out.push("</tbody></table>");
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      closeList();
      const n = h[1].length;
      out.push("<h" + n + ">" + mdInline(h[2]) + "</h" + n + ">");
      continue;
    }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ul) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push("<li>" + mdInline(ul[1]) + "</li>");
      continue;
    }
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) {
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push("<li>" + mdInline(ol[1]) + "</li>");
      continue;
    }
    const q = line.match(/^\s*>\s?(.*)$/);
    if (q) { closeList(); out.push("<blockquote>" + mdInline(q[1]) + "</blockquote>"); continue; }
    closeList();
    out.push("<p>" + mdInline(line) + "</p>");
  }
  closeList();
  if (code) out.push("</code></pre>");
  return out.join("");
}

function parseDelimited(text, delim) {
  const s = String(text || "").replace(/\r\n?/g, "\n");
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quoted) {
      if (c === '"') {
        if (s[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else cell += c;
      continue;
    }
    if (c === '"') { quoted = true; continue; }
    if (c === delim) { row.push(cell); cell = ""; continue; }
    if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; continue; }
    cell += c;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function renderDataTable(text, delim) {
  const rows = parseDelimited(text, delim);
  if (!rows.length) return '<p class="data-note">' + escHtml(tx("空表格")) + "</p>";
  const limit = Math.min(rows.length, QUICK_TABLE_LIMIT);
  const parts = ['<table class="data-table"><thead><tr>'];
  rows[0].forEach(function (cell) { parts.push("<th>" + escHtml(cell) + "</th>"); });
  parts.push("</tr></thead><tbody>");
  for (let i = 1; i < limit; i++) {
    parts.push("<tr>");
    rows[i].forEach(function (cell) { parts.push("<td>" + escHtml(cell) + "</td>"); });
    parts.push("</tr>");
  }
  parts.push("</tbody></table>");
  if (rows.length > limit) {
    parts.push('<div class="data-note">' + escHtml(tx("仅显示前 2000 行")) + "</div>");
  }
  return parts.join("");
}

function renderJsonValue(value) {
  if (value === null) return '<span class="json-null">null</span>';
  if (typeof value === "string") return '<span class="json-str">"' + escHtml(value) + '"</span>';
  if (typeof value === "number") return '<span class="json-num">' + escHtml(String(value)) + "</span>";
  if (typeof value === "boolean") return '<span class="json-bool">' + value + "</span>";
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    let out = '<details open><summary>[' + value.length + "]</summary>";
    value.forEach(function (v, i) {
      out += "<div>" + renderJsonValue(v) + (i < value.length - 1 ? "," : "") + "</div>";
    });
    return out + "</details>";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (!keys.length) return "{}";
    let out = '<details open><summary>{' + keys.length + "}</summary>";
    keys.forEach(function (k, i) {
      out += '<div><span class="json-key">"' + escHtml(k) + '":</span> ' +
        renderJsonValue(value[k]) + (i < keys.length - 1 ? "," : "") + "</div>";
    });
    return out + "</details>";
  }
  return escHtml(String(value));
}

function renderJsonTree(text) {
  try {
    return '<div class="json-view">' + renderJsonValue(JSON.parse(text)) + "</div>";
  } catch (err) {
    return '<pre class="json-view">' + escHtml(text) + "</pre>";
  }
}

/* XML 只读文本：逐段转义后着色，不执行任何标记，也不提供编辑入口。 */
function xmlHighlight(src) {
  const text = String(src || "");
  const re = /(<!--[\s\S]*?-->)|(<\?[\s\S]*?\?>)|(<!\[CDATA\[[\s\S]*?\]\]>)|(<\/?)([A-Za-z_][\w:.\-]*)([^<>]*?)(\/?>)/g;
  let out = "", last = 0, m;
  while ((m = re.exec(text)) !== null) {
    out += escHtml(text.slice(last, m.index));
    if (m[1]) out += '<span class="xml-comment">' + escHtml(m[1]) + "</span>";
    else if (m[2]) out += '<span class="xml-decl">' + escHtml(m[2]) + "</span>";
    else if (m[3]) out += '<span class="xml-cdata">' + escHtml(m[3]) + "</span>";
    else {
      const attrs = escHtml(m[6] || "").replace(/([A-Za-z_][\w:.\-]*)(?==)/g,
        '<span class="xml-attr">$1</span>');
      out += '<span class="xml-punc">' + escHtml(m[4]) + '</span>' +
             '<span class="xml-tag">' + escHtml(m[5]) + "</span>" + attrs +
             '<span class="xml-punc">' + escHtml(m[7]) + "</span>";
    }
    last = re.lastIndex;
  }
  out += escHtml(text.slice(last));
  return out;
}

function renderXmlText(text) {
  return '<pre class="json-view xml-view">' + xmlHighlight(text) + "</pre>";
}

function mediaTime(sec) {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m + ":" + String(s).padStart(2, "0");
}

function setMediaPlayIcon(playing) {
  const icon = $("mediaPlayIcon");
  if (icon) icon.innerHTML = playing
    ? '<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>'
    : '<path d="M7 5l12 7-12 7z"/>';
  const btn = $("mediaPlay");
  if (btn) {
    btn.title = tx(playing ? "暂停" : "播放");
    btn.setAttribute("aria-label", btn.title);
  }
}

function setMediaMuteIcon(muted) {
  const icon = $("mediaMuteIcon");
  if (icon) icon.innerHTML = muted
    ? '<path d="M4 9v6h4l5 4V5L8 9H4M17 9l4 6M21 9l-4 6"/>'
    : '<path d="M4 9v6h4l5 4V5L8 9H4M17 8a5 5 0 0 1 0 8M19.5 5.5a8.5 8.5 0 0 1 0 13"/>';
  const btn = $("mediaMute");
  if (btn) {
    btn.title = tx(muted ? "取消静音" : "静音");
    btn.setAttribute("aria-label", btn.title);
    btn.setAttribute("aria-pressed", muted ? "true" : "false");
  }
}

function resetQuickMedia() {
  $("quickPlayer").classList.add("hidden");
  if (quickMedia) {
    try { quickMedia.pause(); quickMedia.removeAttribute("src"); quickMedia.load(); } catch (err) { /* 忽略 */ }
    quickMedia = null;
  }
  if ($("mediaSpeedBtn")) {
    $("mediaSpeedBtn").textContent = "1× ▲";
    setDDItem("mediaSpeedMenu", "1");
  }
  setMediaMuteIcon(false);
}

function bindQuickMedia(media) {
  const range = $("mediaRange");
  const count = $("mediaCount");
  range.value = "0";
  range.max = "0";
  count.textContent = "0:00 / 0:00";
  setMediaPlayIcon(false);
  media.addEventListener("loadedmetadata", function () {
    range.max = String(isFinite(media.duration) ? media.duration : 0);
    range.value = String(media.currentTime || 0);
    count.textContent = mediaTime(media.currentTime) + " / " + mediaTime(media.duration);
  });
  media.addEventListener("timeupdate", function () {
    range.value = String(media.currentTime || 0);
    count.textContent = mediaTime(media.currentTime) + " / " + mediaTime(media.duration);
  });
  media.addEventListener("play", function () { setMediaPlayIcon(true); });
  media.addEventListener("pause", function () { setMediaPlayIcon(false); });
  media.addEventListener("ended", function () { setMediaPlayIcon(false); });
  media.addEventListener("volumechange", function () { setMediaMuteIcon(media.muted); });
}

/* 动态文案：先精确匹配，再按最长前缀匹配（用于“已保存 ”+文件名这类拼接） */
function tx(s) {
  if (!IS_EN || !s) return s;
  if (Object.prototype.hasOwnProperty.call(I18N, s)) return I18N[s];
  let best = "";
  for (const key in I18N) {
    if (s.indexOf(key) === 0 && key.length > best.length) best = key;
  }
  return best ? I18N[best] + s.slice(best.length) : s;
}

// 语言按钮宽度跟随侧栏 McTa 动画字符，略宽 10px；下拉项继承同一宽度。
(function syncLangWidth() {
  function apply() {
    const logo = document.querySelector(".brand .logo");
    const wrap = document.getElementById("langWrap");
    if (!logo || !wrap || !logo.offsetWidth) return;
    wrap.style.setProperty("--lang-btn-w", (Math.ceil(logo.offsetWidth) + 10) + "px");
  }
  window.__mctaSyncLangWidth = apply;
  apply();
  window.addEventListener("resize", apply);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(apply);
})();

(function initLangSwitch() {
  const btn = document.getElementById("langToggle");
  if (!btn) return;
  const label = btn.querySelector(".lang-name");
  const menu = document.getElementById("langMenu");
  const item = document.getElementById("langMenuItem");
  const next = LANG === "en" ? "zh" : "en";
  // 按钮显示当前语言，菜单只列出可切换到的另一种语言。
  if (label) label.textContent = LANG === "en" ? "English" : "中文";
  if (item) item.textContent = next === "en" ? "English" : "中文";
  btn.setAttribute("lang", LANG === "en" ? "en" : "zh-CN");
  btn.title = next === "en" ? "Switch to English" : "切换到中文";
  btn.setAttribute("aria-label", btn.title);
  function go() {
    try { localStorage.setItem("mcta-lang", next); } catch (e) { /* 隐私模式忽略 */ }
    const url = new URL(location.href);
    url.searchParams.set("lang", next);
    location.href = url.toString();
  }
  btn.onclick = function () {
    if (menu) menu.classList.toggle("open");
    btn.setAttribute("aria-expanded", menu && menu.classList.contains("open") ? "true" : "false");
  };
  if (item) item.onclick = function (ev) { ev.stopPropagation(); go(); };
  document.addEventListener("click", function (ev) {
    if (!menu || !btn) return;
    if (menu.contains(ev.target) || btn.contains(ev.target)) return;
    menu.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
  });
})();

(function applyLang() {
  if (!IS_EN) return;
  document.documentElement.lang = "en";
  document.title = tx(document.title);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  let node;
  while ((node = walker.nextNode())) {
    const parent = node.parentNode;
    if (!parent || parent.nodeName === "SCRIPT" || parent.nodeName === "STYLE") continue;
    if (parent.closest && parent.closest(".lang-wrap")) continue;
    const raw = node.nodeValue;
    const key = raw ? raw.trim() : "";
    if (!key || !Object.prototype.hasOwnProperty.call(I18N, key)) continue;
    node.nodeValue = I18N[key];
  }
  ["title", "aria-label", "placeholder", "alt"].forEach(function (attr) {
    document.querySelectorAll("[" + attr + "]").forEach(function (el) {
      // 语言按钮的提示由 initLangSwitch 精确控制，不参与自动翻译，
      // 避免英文态下把“切换到中文”误替换为 “Switch to English”。
      if (el.id === "langToggle") return;
      const v = el.getAttribute(attr);
      if (v && Object.prototype.hasOwnProperty.call(I18N, v)) el.setAttribute(attr, I18N[v]);
    });
  });
})();

// 每个浏览器窗口持有独立的会话 ID，后端按它分配独立的终端进程与 cwd。
// window.name 在同一次页面加载（含刷新）中保持，新窗口/新标签则为空 → 新会话。
function mctaSessionId() {
  let sid = "";
  try {
    const named = String(window.name || "");
    if (named.indexOf("mcta-") === 0) sid = named.slice(5);
    if (!sid) sid = sessionStorage.getItem("mcta-sid") || "";
  } catch (err) { /* 隐私模式忽略 */ }
  const valid = function (v) { return /^[A-Za-z0-9_-]{1,64}$/.test(v || ""); };
  if (!valid(sid)) {
    try { sid = crypto.randomUUID(); } catch (err) { sid = ""; }
    if (!valid(sid)) {
      sid = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2);
    }
  }
  try {
    window.name = "mcta-" + sid;
    sessionStorage.setItem("mcta-sid", sid);
  } catch (err) { /* 隐私模式忽略 */ }
  return sid;
}
const SESSION_ID = mctaSessionId();

const state = { root: "", cwd: "", viewing: null, user: null, term: null, es: null, cwdTimer: null, lastCwd: null, signature: "", watchTimer: null, selected: new Set() };
// 每个结构/轨迹/密度窗口独立持有自己的 viewer 与状态。
function freshMolCtx() {
  return { viewer: null, frames: 0, index: 0, timer: null, home: null,
           baseName: "", volume: null, isoShape: null, isoNegShape: null, volumeGroups: null,
           ortho: true, saveJob: null, cell: null, cellOrigin: { x: 0, y: 0, z: 0 },
           cellShapes: [], cellLabels: [], cellCopies: [], structureModel: null,
           pickAtoms: [], pickBonds: [], measureShapes: [], measureLabels: [], styleAtom: null,
           atomStyles: {}, bondStyles: {}, bondBaseOrders: {}, bondPickShapes: [], archive: null, sourcePath: "",
           sourceFrames: null, pickedCellRepeat: [1, 1, 1],
           pickMode: "atom", styleAtom: null, styleBond: null, viewDirtyArmed: false,
           measureMode: false, leftPan: false, longPressHandled: false, longPressClickGuard: false,
           selectMode: false, selectedAtoms: [], selectShapes: [], selectStyles: {},
           atomEdits: {}, atomDeleted: {}, atomAdditions: [], atomElementChanges: {},
           atomHistory: { undo: [], redo: [] }, historySuspend: false,
           atomPanel: null, atomPanelSel: null, atomPanelZ: 30 };
}
let MC = freshMolCtx();
// 结构加载：新请求先取消旧请求；序号用于丢弃过期响应，避免切换文件后被旧响应覆盖。
let molLoadSeq = 0;
let molLoadAbort = null;
function cancelMolLoad() {
  molLoadSeq += 1;
  if (molLoadAbort) {
    try { molLoadAbort.abort(); } catch (e) { /* 忽略 */ }
    molLoadAbort = null;
  }
}
const MOL_BASE_MS = 220;  // 1× 速度下每帧间隔
const MOL_BOND_RADIUS = 0.06;  // 默认键半径（Å），空白处右键“样式设置”可调整
let molBondRadius = MOL_BOND_RADIUS;
// 全局键颜色：空字符串表示按元素着色；非空则覆盖所有未单独设置的键。
let molBondColor = "";
// 全局键样式：none 不显示键；solid/dashed 由 molBondDashed 区分；单键设置会被全局设置覆盖。
let molBondDashed = false;
let molBondHidden = false;
// 全局原子样式：0 / 空串表示按元素默认；非 0 / 非空表示覆盖所有原子。
// 与全局键设置一致，改动全局原子样式会清掉逐原子覆盖。
let molAtomRadius = 0;
let molAtomColor = "";
// 页面初始化阶段就要给样式滑杆取默认值，此时元素色/半径表尚未声明，先用常量。
const MOL_DEFAULT_ATOM_RADIUS = 0.36;
const MOL_DEFAULT_ATOM_COLOR = "#9aa4b2";
// 原子/键整体显示开关（“样式设置 → 外观 / 键”），关闭时对应几何整体隐藏。
let molAtomsVisible = true, molBondsVisible = true;
const MOL_BOND_DASH_LENGTH = 0.12;
const MOL_BOND_GAP_LENGTH = 0.18;
let activeMask = null;
let maskSeq = 0;
const $ = function (id) {
  if (activeMask) {
    if (activeMask.id === id || activeMask.dataset.baseId === id) return activeMask;
    const scoped = activeMask.querySelector("#" + id);
    if (scoped) return scoped;
  }
  return document.getElementById(id);
};

// 浮窗层级：后显示或被选中的窗口置顶，不改变其它窗口的位置和大小。
// 最小化停靠图标使用独立的高位层级段：高于普通浮窗/菜单/提示，低于确认对话框遮罩(10000)。
let floatZ = 30;
const MIN_DOCK_Z = 9000;
let minDockZCount = MIN_DOCK_Z;
function bringFloatToFront(el) {
  if (!el) return;
  const isMin = el.classList.contains("win-min")
    || !!(el.querySelector && el.querySelector(".win-min"));
  if (isMin) { el.style.zIndex = String(++minDockZCount); return; }
  if (floatZ >= MIN_DOCK_Z - 2) floatZ = 30; // 普通层级接近停靠层时回卷，避免盖住最小化图标
  el.style.zIndex = String(++floatZ);
}

/* ---- 浮窗最小化停靠：主体隐藏、只留顶栏，停靠页面下方从左到右排列 ---- */
// 记录最小化顺序，终端浮窗与文件浮窗共用一条停靠栏。
const minDock = [];
// 标题变化会改变图标宽度，尺寸变化后重排，避免相邻图标重叠。
const minResizeObserver = (typeof ResizeObserver !== "undefined")
  ? new ResizeObserver(function () { requestAnimationFrame(layoutMinDock); }) : null;
// 兜底巡检：标题/尺寸被外部逻辑改写后也能在下一拍收敛，避免图标残留重叠或完整标题。
let minDockTick = null;
function startDockTick() {
  if (minDockTick !== null) return;
  minDockTick = setInterval(function () {
    if (!minDock.length) { clearInterval(minDockTick); minDockTick = null; return; }
    ensureDockTitles();
    layoutMinDock();
  }, 400);
}
function minDockAdd(el) {
  if (el && minDock.indexOf(el) < 0) {
    minDock.push(el);
    if (minResizeObserver) minResizeObserver.observe(el);
    startDockTick();
  }
}
function minDockRemove(el) {
  const i = minDock.indexOf(el);
  if (i >= 0) {
    minDock.splice(i, 1);
    if (minResizeObserver && minResizeObserver.unobserve) minResizeObserver.unobserve(el);
    // 清除停靠时的 !important 几何，后续 applyFree/resetFree/floatAt 才能重新定位。
    if (el && el.style) { el.style.removeProperty("left"); el.style.removeProperty("top"); }
    if (!minDock.length && minDockTick !== null) { clearInterval(minDockTick); minDockTick = null; }
  }
}
// 从打开记录或标题中提取纯文件名，避免停靠态残留大小/修改日期等信息。
function dockFileName(mask, h2) {
  const text = String(h2 ? h2.textContent : "");
  const key = String((mask && mask.dataset.openKey) || "");
  const m = /^(?:view|rename):(.+)$/.exec(key);
  if (m) {
    const name = m[1].replace(/\\/g, "/").split("/").filter(Boolean).pop();
    if (name) return name;
  }
  const parts = text.split(" · ");
  return (parts.length > 1 ? parts[0] : text).trim();
}
// 标题可能被其它逻辑写回完整信息，重排前统一收敛为纯文件名。
const dockTitleObserver = (typeof MutationObserver !== "undefined")
  ? new MutationObserver(function (muts) {
      for (let i = 0; i < muts.length; i++) {
        const t = muts[i].target;
        const el = t.nodeType === 3 ? t.parentElement : t;
        if (el && el.closest && el.closest(".mol-win.win-min")) {
          ensureDockTitles();
          layoutMinDock();
          break;
        }
      }
    }) : null;
function ensureDockTitles() {
  minDock.forEach(function (el) {
    if (!el || !el.classList.contains("win-min")) return;
    const mask = el.closest(".mol-mask");
    const h2 = mask && mask.querySelector(".mol-head h2");
    if (!h2) return;
    if (dockTitleObserver) {
      dockTitleObserver.observe(h2, { childList: true, characterData: true, subtree: true });
    }
    if (mask.dataset.fullTitle === undefined) mask.dataset.fullTitle = h2.textContent;
    const name = dockFileName(mask, h2);
    const tag = String(mask.dataset.dockTag || "");
    h2.dataset.dockName = tag ? name + " · " + tag : name; // CSS 停靠态只渲染该属性，可带类型标签
    if (h2.textContent !== name) h2.textContent = name;
  });
}
// 还原文件浮窗停靠栏中被精简的标题（停靠时只留文件名）。
function restoreDockTitle(mask) {
  const h2 = mask.querySelector(".mol-head h2");
  if (mask.dataset.fullTitle !== undefined) {
    if (h2) h2.textContent = mask.dataset.fullTitle;
    delete mask.dataset.fullTitle;
  }
  if (h2) delete h2.dataset.dockName;
}
// 从最小化停靠还原文件浮窗：恢复几何/标题，清理停靠位并重排。
function restoreMaskFromMin(mask) {
  if (!mask) return false;
  const win = mask.querySelector(".mol-win");
  if (!win || !win.classList.contains("win-min")) return false;
  win.classList.remove("win-min");
  minDockRemove(win);
  restoreDockTitle(mask);
  const saved = mask.dataset.minRect;
  if (saved && typeof mask._applyFree === "function") {
    try { mask._applyFree(JSON.parse(saved)); } catch (e) {}
  }
  delete mask.dataset.minRect;
  layoutMinDock();
  return true;
}
function layoutMinDock() {
  // 多个最小化图标紧贴左下角（图标间无间隙），终端固定在最左下；按实际宽度换行，不回拉造成重叠。
  ensureDockTitles();
  const ROW_H = 40, GAP = 0, EDGE = 4;
  const VW = window.innerWidth, VH = window.innerHeight;
  // 终端最小化时固定在最左下角；文件浮窗按剩余空间从左到右、自下而上逐行排列，不堆叠。
  const term = minDock.find(function (el) {
    return el && el.isConnected && el.classList.contains("win-min") && el.classList.contains("term-wrap");
  });
  const files = minDock.filter(function (el) {
    return el && el !== term && el.isConnected && el.classList.contains("win-min");
  });
  function place(el, x, row) {
    const w = Math.ceil(el.getBoundingClientRect().width || 120);
    // 用内联 !important 固定停靠几何，避免 maxed/free 等规则覆盖 left/top 造成重叠。
    el.style.setProperty("left", Math.round(Math.max(EDGE, x)) + "px", "important");
    el.style.setProperty("top", Math.round(VH - (row + 1) * ROW_H - row * GAP - EDGE) + "px", "important");
    return w;
  }
  // 终端占最底行最左
  if (term) place(term, EDGE, 0);
  let x = EDGE + (term ? Math.ceil(term.getBoundingClientRect().width || 120) + GAP : 0);
  let row = 0;
  for (let i = 0; i < files.length; i++) {
    const w = Math.ceil(files[i].getBoundingClientRect().width || 120);
    if (x > EDGE && x + w > VW - EDGE) { x = EDGE; row += 1; }
    x += place(files[i], x, row) + GAP;
  }
}
window.addEventListener("resize", layoutMinDock);
// 隐藏或移除停靠项时同步清理数组
const minDockObserver = new MutationObserver(function () {
  let changed = false;
  for (let i = minDock.length - 1; i >= 0; i--) {
    const el = minDock[i];
    if (!el.isConnected || !el.classList.contains("win-min")) { minDock.splice(i, 1); changed = true; }
  }
  if (changed) requestAnimationFrame(layoutMinDock);
});
minDockObserver.observe(document.body, { attributes: true, childList: true, subtree: true, attributeFilter: ["class"] });

// 复用隐藏窗口；没有可用窗口时从原始模板克隆一个。
// openKey 非空时，同一文件已打开则直接复用并置顶，不再克隆新窗口。
// cloneNode 不复制 .on* 处理器，这里按元素顺序补回去。
function acquireMask(baseId, openKey) {
  const all = document.querySelectorAll('.mol-mask[data-base-id="' + baseId + '"]');
  if (openKey) {
    for (let i = 0; i < all.length; i++) {
      if (!all[i].classList.contains("hidden") && all[i].dataset.openKey === openKey) {
        // 已打开但被最小化：再次点击同一文件时还原，并置于显示浮窗上层。
        const restored = restoreMaskFromMin(all[i]);
        switchMask(all[i]);
        bringFloatToFront(all[i]);
        if (restored && all[i].dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
        return all[i];
      }
    }
  }
  for (let i = 0; i < all.length; i++) {
    if (all[i].classList.contains("hidden")) {
      if (baseId === "molView") all[i]._ctx = freshMolCtx();
      all[i].dataset.openKey = openKey || "";
      switchMask(all[i]);
      bringFloatToFront(all[i]);
      return all[i];
    }
  }
  const src = document.getElementById(baseId);
  const mask = src.cloneNode(true);
  mask.id = baseId + "-" + (++maskSeq);
  mask.dataset.openKey = openKey || "";
  document.body.appendChild(mask);
  const a = [src].concat(Array.prototype.slice.call(src.querySelectorAll("*")));
  const b = [mask].concat(Array.prototype.slice.call(mask.querySelectorAll("*")));
  for (let i = 0; i < a.length && i < b.length; i++) {
    for (const key in a[i]) {
      if (key.indexOf("on") === 0 && typeof a[i][key] === "function") b[i][key] = a[i][key];
    }
  }
  initModalFloating(mask);
  observeModal(mask);
  switchMask(mask);
  bringFloatToFront(mask);
  return mask;
}

function anyViewerOpen() {
  return !!document.querySelector(".mol-mask:not(.hidden)");
}

// 点击/聚焦任一弹窗时，后续 $() 与结构状态都指向该窗口。
function switchMask(next) {
  if (activeMask && activeMask.dataset.baseId === "molView") activeMask._ctx = MC;
  activeMask = next;
  if (next && next.dataset.baseId === "molView") {
    MC = next._ctx || freshMolCtx();
    molSyncMeasureButton();
    molSyncSelectButton();
  }
}
["pointerdown", "focusin"].forEach(function (evt) {
  document.addEventListener(evt, function (e) {
    const floatEl = e.target.closest && e.target.closest(".mol-mask, .term-wrap.floating, #browser.floating");
    if (!floatEl) return;
    bringFloatToFront(floatEl);
    if (floatEl.classList.contains("mol-mask")) switchMask(floatEl);
  }, true);
});

function toast(msg, err, anchor) {
  const el = $("toast");
  el.textContent = tx(msg);
  el.classList.toggle("err", !!err);
  const anchored = !!(anchor && (anchor.getBoundingClientRect || typeof anchor.clientX === "number"));
  el.classList.toggle("anchored", anchored);
  if (anchored) {
    // 警告贴着所点击的文件显示，并限制在视口内，避免被浮窗遮挡。
    let x, y;
    if (anchor.getBoundingClientRect) {
      const r = anchor.getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top;
    } else {
      x = anchor.clientX;
      y = anchor.clientY;
    }
    const w = el.offsetWidth || 160;
    const h = el.offsetHeight || 36;
    el.style.left = Math.round(Math.max(w / 2 + 8, Math.min(window.innerWidth - w / 2 - 8, x))) + "px";
    el.style.top = Math.round(Math.max(h + 12, Math.min(window.innerHeight - 8, y - 8))) + "px";
    el.style.bottom = "auto";
  } else {
    el.style.left = "";
    el.style.top = "";
    el.style.bottom = "";
  }
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(function () { el.classList.remove("show"); }, 2200);
}

function fmtSize(n) {
  if (n === null || n === undefined) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
}

async function api(url, opts, signal) {
  // 所有请求都带上窗口会话 ID：后端据此使用该窗口自己的终端目录做路径放行。
  // signal 用于取消长时间请求（例如切换文件时中止大结构渲染）。
  const sep = url.indexOf("?") >= 0 ? "&" : "?";
  const settings = opts ? Object.assign({}, opts) : {};
  if (signal) settings.signal = signal;
  const res = await fetch(url + sep + "sid=" + q(SESSION_ID), settings);
  let data = {};
  try { data = await res.json(); } catch (e) { /* 非 JSON */ }
  if (!res.ok) {
    const err = new Error(data.error || res.statusText);
    err.status = res.status;
    err.retryAfter = Number(data.retry_after || res.headers.get("Retry-After") || 0) || 0;
    throw err;
  }
  return data;
}

function q(path) { return encodeURIComponent(path); }

// 图片/PDF/媒体/下载使用原生 <img>/<iframe>/window.open，不会经过 api()，
// 必须显式带上窗口会话 ID：否则后端按默认终端（cwd=运行目录）放行，
// 浏览到运行目录之外的目录（如 /mnt/d/test）时会被判为越界而 404。
function withSid(url) {
  const sep = url.indexOf("?") >= 0 ? "&" : "?";
  return url + sep + "sid=" + q(SESSION_ID);
}

// 目录浮窗最小化时，路径入口不导航，只还原窗口（与点击顶栏一致）。
function crumbNavigate(path) {
  const br = $("browser");
  if (br && br.classList.contains("win-min")) {
    const head = br.querySelector(".head");
    if (head) head.click();
    return;
  }
  load(path);
}

// 面包屑右侧的输入入口：编辑态隐藏除“运行目录”外的路径按钮，图标由输入变为回车。
const CRUMB_EDIT_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m14 6 4 4"/></svg>';
const CRUMB_ENTER_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 10 5 14l4 4"/><path d="M5 14h9a5 5 0 0 0 5-5V6"/></svg>';
let crumbEditing = false;
let crumbEditValue = "";
let crumbsPath = null;
let crumbsRebuilding = false;

function syncCrumbEdit() {
  const box = $("crumbs");
  if (!box) return;
  box.classList.toggle("crumb-edit", crumbEditing);
  const input = box.querySelector(".crumb-path-input");
  if (input) {
    input.value = crumbEditing ? crumbEditValue : "";
    input.title = tx("输入路径后回车切换目录");
    input.setAttribute("aria-label", tx("输入路径后回车切换目录"));
  }
  const btn = box.querySelector(".crumb-path-btn");
  if (btn) {
    btn.innerHTML = crumbEditing ? CRUMB_ENTER_ICON : CRUMB_EDIT_ICON;
    const label = tx(crumbEditing ? "回车切换目录" : "输入路径");
    btn.title = label;
    btn.setAttribute("aria-label", label);
  }
}

function closeCrumbEdit() {
  crumbEditing = false;
  crumbEditValue = "";
  syncCrumbEdit();
}

function openCrumbEdit() {
  const note = $("pathNote");
  crumbEditValue = (note && note.dataset.label) || state.cwd || "";
  crumbEditing = true;
  syncCrumbEdit();
  const input = $("crumbs") && $("crumbs").querySelector(".crumb-path-input");
  if (input) { input.focus(); input.select(); }
}

function submitCrumbPath() {
  const value = crumbEditValue;
  closeCrumbEdit();
  navigateToPath(value);
}

function renderCrumbs() {
  const box = $("crumbs");
  if (!box) return;
  const hadFocus = !!(document.activeElement && document.activeElement.classList &&
    document.activeElement.classList.contains("crumb-path-input"));
  // 目录真正变化时才退出编辑态；同一目录的后台刷新不会打断输入。
  if (crumbsPath !== state.cwd) {
    crumbEditing = false;
    crumbEditValue = "";
    crumbsPath = state.cwd;
  }
  crumbsRebuilding = true;
  box.innerHTML = "";
  crumbsRebuilding = false;
  const base = document.createElement("a");
  base.className = "crumb-home";
  base.title = tx("运行目录");
  base.setAttribute("aria-label", tx("运行目录"));
  base.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11 12 4l9 7"/><path d="M5 10v9h14v-9"/><path d="M9 19v-6h6v6"/></svg>';
  base.onclick = function () { crumbNavigate(""); };
  box.appendChild(base);
  // 远程模式下 state.cwd 是远端绝对路径；面包屑按“相对运行目录”显示，
  // 与本地启动一致：运行目录不显示逐级菜单，只保留输入路径入口。
  let crumbPath = state.cwd || "";
  const crumbBase = (state.root || "").replace(/\/+$/, "");
  if (crumbBase && crumbPath === crumbBase) {
    crumbPath = "";
  } else if (crumbBase && crumbPath.indexOf(crumbBase + "/") === 0) {
    crumbPath = crumbPath.slice(crumbBase.length + 1);
  }
  const absolute = crumbPath.charAt(0) === "/";
  const parts = crumbPath ? crumbPath.split("/").filter(function (p) { return p; }) : [];
  let acc = "";
  parts.forEach(function (part) {
    const sep = document.createElement("span");
    sep.textContent = "/";
    box.appendChild(sep);
    if (absolute) {
      acc = acc + "/" + part;
    } else {
      acc = acc ? acc + "/" + part : part;
    }
    const link = document.createElement("a");
    link.textContent = part;
    const target = acc;
    link.onclick = function () { crumbNavigate(target); };
    box.appendChild(link);
  });

  const input = document.createElement("input");
  input.type = "text";
  input.className = "crumb-path-input";
  input.spellcheck = false;
  input.autocomplete = "off";
  input.addEventListener("input", function () { crumbEditValue = input.value; });
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); submitCrumbPath(); }
    else if (ev.key === "Escape") { ev.preventDefault(); closeCrumbEdit(); }
  });
  input.addEventListener("blur", function () {
    if (crumbEditing && !crumbsRebuilding && document.contains(input)) closeCrumbEdit();
  });
  box.appendChild(input);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "crumb-path-btn";
  // 防止按钮抢焦点，避免 blur 先把输入内容还原。
  btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
  btn.addEventListener("click", function (ev) {
    ev.stopPropagation();
    const br = $("browser");
    if (br && br.classList.contains("win-min")) {
      const head = br.querySelector(".head");
      if (head) head.click();
      return;
    }
    if (crumbEditing) submitCrumbPath(); else openCrumbEdit();
  });
  box.appendChild(btn);
  // 最小化停靠态显示当前路径纯文本（面包屑此时整体隐藏）。
  const minPath = $("crumbMinPath");
  if (minPath) minPath.textContent = state.cwd || tx("运行目录");
  syncCrumbEdit();
  if (hadFocus && crumbEditing) {
    const active = box.querySelector(".crumb-path-input");
    if (active) active.focus();
  }
}

// ---------- 文件多选、拖入上传与目录面板浮窗 ----------
function addSelectBox(host, entry) {
  const box = document.createElement("input");
  box.type = "checkbox";
  box.className = "sel";
  box.title = entry.name;
  box.setAttribute("aria-label", entry.name);
  box.checked = state.selected.has(entry.path);
  box.addEventListener("click", function (e) { e.stopPropagation(); });
  box.addEventListener("change", function () {
    if (box.checked) state.selected.add(entry.path);
    else state.selected.delete(entry.path);
    host.classList.toggle("selected", box.checked);
    syncDownloadButton();
  });
  host.appendChild(box);
}

function syncDownloadButton() {
  const btn = $("btnDownloadSel");
  if (!btn) return;
  btn.disabled = state.selected.size === 0;
  const badge = $("downloadBadge");
  if (badge) badge.textContent = state.selected.size || "";
  const label = tx("下载选中") + (state.selected.size ? " (" + state.selected.size + ")" : "");
  btn.title = label;
  btn.setAttribute("aria-label", label);
}

async function downloadSelected() {
  const paths = Array.from(state.selected);
  if (!paths.length) return;
  try {
    const res = await fetch(withSid("/api/download"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: paths })
    });
    if (!res.ok) {
      let data = {};
      try { data = await res.json(); } catch (e) { /* 忽略 */ }
      throw new Error(data.error || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mcta-download.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  } catch (err) { toast(err.message, true); }
}

function initBrowserFloat() {
  const br = $("browser");
  const head = br ? br.querySelector(".head") : null;
  if (!br || !head) return;
  const tools = br.querySelector(".browser-tools");
  // 浮窗最小高度与侧栏终端一致（窄屏 CSS 变量会变小，取不到时回退 310）。
  function minBrowserHeight() {
    let n = 0;
    try { n = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--term-side-h")); }
    catch (err) { /* 忽略 */ }
    return Number.isFinite(n) && n > 0 ? n : 310;
  }
  const HEAD_TIP = "点击顶栏可浮动为小窗口";
  const MIN_W = 320, MIN_H = minBrowserHeight();
  let uiMode = "dock";        // 'dock' | 'float'
  let maximized = false;
  let minimized = false;
  let prevRect = null;        // 最大化前的几何
  let minRect = null;         // 最小化前的几何
  let placeholder = null;
  let drag = null;
  let resize = null;

  head.title = tx(HEAD_TIP);

  function currentRect() {
    const r = br.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  // 与终端浮窗一致：约束顶栏上下边沿的中心点留在页面内，
  // 水平方向窗口最多移出半宽，垂直方向顶栏不得移出屏幕。
  function clampRect(r) {
    r.w = Math.min(Math.max(MIN_W, r.w || 560), Math.max(MIN_W, window.innerWidth - 8));
    r.h = Math.min(Math.max(MIN_H, r.h || 400), Math.max(MIN_H, window.innerHeight - 4));
    const HEAD = 44;
    r.x = Math.min(Math.max(-r.w / 2, r.x || 0), window.innerWidth - r.w / 2);
    r.y = Math.min(Math.max(0, r.y || 0), Math.max(0, window.innerHeight - HEAD));
    return r;
  }
  function applyRect(r) {
    br.style.left = Math.round(r.x) + "px";
    br.style.top = Math.round(r.y) + "px";
    br.style.width = Math.round(r.w) + "px";
    br.style.height = Math.round(r.h) + "px";
  }
  function maxRect() {
    // 与其它浮窗一致：顶端紧贴页面，底部留 4px。
    return { x: 4, y: 0, w: window.innerWidth - 8, h: window.innerHeight - 4 };
  }
  function defaultRect() {
    const w = Math.min(560, Math.max(MIN_W, window.innerWidth - 24));
    const h = Math.max(MIN_H, window.innerHeight - 8); // 浮窗初始高度 = 页面高度（上下各留 4px）
    // 与终端浮窗贴左边缘一致，初始贴右边缘留 4px。
    return clampRect({ x: Math.max(4, window.innerWidth - w - 4), y: 4, w: w, h: h });
  }

  function syncTools() {
    head.title = uiMode === "float" ? "" : tx(HEAD_TIP);
    if (!tools) return;
    const labels = {
      min: tx("最小化"),
      restore: tx("还原"),
      max: maximized ? tx("缩回原始大小") : tx("放大到整个页面"),
      dock: tx("还原到页面")
    };
    tools.querySelectorAll("button[data-browser-act]").forEach(function (b) {
      const label = labels[b.getAttribute("data-browser-act")];
      if (!label) return;
      b.title = label;
      b.setAttribute("aria-label", label);
    });
    const maxBtn = tools.querySelector('button[data-browser-act="max"]');
    if (maxBtn) setModalMaxButton(maxBtn, maximized);
  }

  function floatAt(rect) {
    if (uiMode !== "float") {
      placeholder = document.createElement("div");
      placeholder.className = "browser-ph";
      placeholder.textContent = tx("目录面板已浮动");
      br.parentNode.insertBefore(placeholder, br);
      document.body.appendChild(br);
      br.classList.add("floating");
      uiMode = "float";
    }
    br.classList.remove("win-min");
    markTopSnap(br, false);
    minDockRemove(br);
    layoutMinDock();
    bringFloatToFront(br);
    applyRect(clampRect(rect));
    maximized = false;
    minimized = false;
    prevRect = null;
    minRect = null;
    syncTools();
  }

  function dock() {
    if (uiMode !== "float") return;
    br.classList.remove("floating", "win-min", "drag-over", "dragging");
    markTopSnap(br, false);
    br.style.left = br.style.top = br.style.width = br.style.height = br.style.zIndex = "";
    minDockRemove(br);
    layoutMinDock();
    if (placeholder && placeholder.parentNode) {
      placeholder.parentNode.insertBefore(br, placeholder);
      placeholder.remove();
    } else {
      document.querySelector("main").appendChild(br);
    }
    placeholder = null;
    uiMode = "dock";
    maximized = false;
    minimized = false;
    prevRect = null;
    minRect = null;
    syncTools();
  }

  function minimizeWin() {
    if (uiMode !== "float" || minimized) return;
    let r = currentRect();
    if (maximized && prevRect) {
      applyRect(clampRect(prevRect));
      r = currentRect();
    }
    minimized = true;
    maximized = false;
    prevRect = null;
    minRect = r;
    br.classList.add("win-min");
    bringFloatToFront(br);
    minDockAdd(br);
    layoutMinDock();
    syncTools();
  }

  function restoreWin() {
    if (uiMode !== "float") { floatAt(defaultRect()); return; }
    if (!minimized) { floatAt(defaultRect()); return; }
    minimized = false;
    maximized = false;
    prevRect = null;
    br.classList.remove("win-min");
    minDockRemove(br);
    layoutMinDock();
    bringFloatToFront(br);
    if (minRect) applyRect(clampRect(minRect));
    minRect = null;
    syncTools();
  }

  function toggleMax() {
    if (uiMode !== "float") return;
    if (minimized) restoreWin();
    if (maximized) {
      maximized = false;
      if (prevRect) applyRect(clampRect(prevRect));
      prevRect = null;
    } else {
      prevRect = currentRect();
      maximized = true;
      applyRect(clampRect(maxRect()));
    }
    syncTools();
  }

  if (tools) {
    tools.addEventListener("click", function (e) {
      const btn = e.target.closest("button[data-browser-act]");
      if (!btn) return;
      e.stopPropagation();
      const act = btn.getAttribute("data-browser-act");
      if (act === "dock") { dock(); return; }
      if (uiMode !== "float") floatAt(defaultRect());
      if (act === "min") { minimizeWin(); return; }
      if (act === "restore") { restoreWin(); return; }
      if (act === "max") { toggleMax(); return; }
    });
  }

  // 点击顶栏只负责“停靠态 → 浮窗”；浮窗态点击顶栏不再还原到页面，
  // 还原统一交给顶栏最右侧的“还原到页面”按钮。
  head.addEventListener("click", function (e) {
    if (e.target.closest("button,input,a")) return;
    if (uiMode === "float") {
      if (minimized) { e.stopPropagation(); restoreWin(); }
      return;
    }
    floatAt(defaultRect());
    toast(tx("目录面板已浮动"));
  });

  head.addEventListener("pointerdown", function (e) {
    if (uiMode !== "float" || minimized || e.target.closest("button,input,a")) return;
    const r = currentRect();
    drag = { dx: e.clientX - r.x, dy: e.clientY - r.y, w: r.w, h: r.h, id: e.pointerId };
    try { head.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
    e.preventDefault();
  });
  head.addEventListener("pointermove", function (e) {
    if (!drag) return;
    e.preventDefault();
    const raw = { x: e.clientX - drag.dx, y: e.clientY - drag.dy, w: drag.w, h: drag.h };
    const r = clampRect(raw);
    if (raw.y <= (drag.snap ? TOP_SNAP_HYST : TOP_SNAP_Y)) {
      if (!drag.snap) drag.prev = { w: r.w, h: r.h };
      drag.snap = true;
      const snapped = topSnapRect(r);
      drag.w = snapped.w;
      drag.h = snapped.h;
      applyRect(snapped);
      markTopSnap(br, true);
    } else {
      if (drag.snap && drag.prev) { drag.w = drag.prev.w; drag.h = drag.prev.h; }
      drag.snap = false;
      markTopSnap(br, false);
      applyRect(clampRect({ x: e.clientX - drag.dx, y: raw.y, w: drag.w, h: drag.h }));
    }
    if (maximized) { maximized = false; syncTools(); }
  });
  const endDrag = function () {
    if (!drag) return;
    try { head.releasePointerCapture(drag.id); } catch (err) { /* 忽略 */ }
    drag = null;
  };
  head.addEventListener("pointerup", endDrag);
  head.addEventListener("pointercancel", endDrag);

  // 四边/四角缩放：与终端浮窗一致，通过独立的热区拖动改变几何。
  br.querySelectorAll(".browser-rh").forEach(function (handle) {
    handle.addEventListener("pointerdown", function (e) {
      if (uiMode !== "float" || minimized || maximized) return;
      markTopSnap(br, false);
      const cls = handle.className.split(/\s+/).filter(Boolean);
      const part = (cls.find(function (c) { return c.indexOf("brh-") === 0; }) || "").slice(4);
      if (!part) return;
      const r = currentRect();
      resize = { part: part, x: e.clientX, y: e.clientY,
                 left: r.x, top: r.y, w: r.w, h: r.h, id: e.pointerId };
      try { handle.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      e.preventDefault();
      e.stopPropagation();
    });
    handle.addEventListener("pointermove", function (e) {
      if (!resize) return;
      const dx = e.clientX - resize.x, dy = e.clientY - resize.y;
      let x = resize.left, y = resize.top, w = resize.w, h = resize.h;
      const p = resize.part;
      if (p.indexOf("r") >= 0) w = resize.w + dx;
      if (p.indexOf("l") >= 0) { w = Math.max(MIN_W, resize.w - dx); x = resize.left + (resize.w - w); }
      if (p.indexOf("b") >= 0) h = resize.h + dy;
      if (p.indexOf("t") >= 0) { h = Math.max(MIN_H, resize.h - dy); y = resize.top + (resize.h - h); }
      applyRect(clampRect({ x: x, y: y, w: w, h: h }));
    });
    const endResize = function () {
      if (!resize) return;
      try { handle.releasePointerCapture(resize.id); } catch (err) { /* 忽略 */ }
      resize = null;
    };
    handle.addEventListener("pointerup", endResize);
    handle.addEventListener("pointercancel", endResize);
  });

  window.addEventListener("resize", function () {
    if (uiMode !== "float") return;
    if (maximized) applyRect(clampRect(maxRect()));
    else applyRect(clampRect(currentRect()));
  });
}

function walkDroppedEntry(entry, prefix, out) {
  return new Promise(function (resolve) {
    if (entry.isFile) {
      entry.file(function (file) { out.push({ file: file, path: prefix + file.name }); resolve(); },
                 function () { resolve(); });
    } else if (entry.isDirectory) {
      out.push({ dir: prefix + entry.name });
      const reader = entry.createReader();
      const read = function () {
        reader.readEntries(function (entries) {
          let chain = Promise.resolve();
          entries.forEach(function (child) {
            chain = chain.then(function () {
              return walkDroppedEntry(child, prefix + entry.name + "/", out);
            });
          });
          chain.then(function () { if (entries.length) read(); else resolve(); });
        }, function () { resolve(); });
      };
      read();
    } else resolve();
  });
}

async function collectDropped(dt) {
  const out = [];
  const items = Array.prototype.slice.call(dt.items || []);
  for (const item of items) {
    if (item.kind !== "file") continue;
    const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
    if (entry) await walkDroppedEntry(entry, "", out);
  }
  if (!out.length) {
    Array.prototype.forEach.call(dt.files || [], function (file) {
      out.push({ file: file, path: file.webkitRelativePath || file.name });
    });
  }
  return out;
}

async function uploadDropped(dt) {
  const items = await collectDropped(dt);
  if (!items.length) return;
  toast(tx("正在上传 ") + items.length + tx(" 项…"));
  let good = 0;
  let failed = 0;
  for (const item of items) {
    try {
      const headers = { "X-Upload-Dir": state.cwd, "X-File-Path": encodeURIComponent(item.path) };
      let body = "";
      if (item.dir) headers["X-File-Kind"] = "dir";
      else { headers["X-File-Kind"] = "file"; body = item.file; }
      const res = await fetch(withSid("/api/upload"), { method: "POST", headers: headers, body: body });
      if (!res.ok) {
        let data = {};
        try { data = await res.json(); } catch (e) { /* 忽略 */ }
        throw new Error(data.error || res.statusText);
      }
      good += 1;
    } catch (err) { failed += 1; console.error(err); }
  }
  toast(tx("已上传 ") + good + tx(" 项") + (failed ? " · " + tx("上传失败：") + failed : ""), failed > 0);
  load(state.cwd, true);
}

function initBrowserDrop() {
  const br = $("browser");
  if (!br) return;
  br.dataset.dropHint = tx("拖入文件或目录以上传");
  const dropRow = $("dropRow");
  if (dropRow) dropRow.dataset.hint = tx("拖入文件或目录以上传");
  const hasFiles = function (e) {
    return Array.prototype.indexOf.call((e.dataTransfer && e.dataTransfer.types) || [], "Files") >= 0;
  };
  br.addEventListener("dragenter", function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    br.classList.add("drag-over");
  });
  br.addEventListener("dragover", function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  br.addEventListener("dragleave", function (e) {
    if (!br.contains(e.relatedTarget)) br.classList.remove("drag-over");
  });
  br.addEventListener("drop", function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    br.classList.remove("drag-over");
    uploadDropped(e.dataTransfer);
  });
}

function showBrowser() {
  // 文件浮窗不再随目录切换关闭；只有没有浮窗时才重置结构状态。
  if (!anyViewerOpen()) {
    MC = freshMolCtx();
    molSyncPanButton();
    molSyncMeasureButton();
    molSyncSelectButton();
    activeMask = null;
  }
  state.viewing = null;
  state.selected.clear();
  syncDownloadButton();
  $("browser").classList.remove("hidden");
}

// 页面导航到新目录后，把终端 cwd 同步到同一路径。
// 用 state.lastCwd（syncCwd 已记录终端真实 cwd）比较，避免来回 cd 形成循环。
function syncTermToDir(pathLabel) {
  if (!state.term || !pathLabel) return;
  const abs = absNormPath(pathLabel, "/");
  const cur = state.lastCwd ? absNormPath(state.lastCwd, "/") : "";
  if (cur && cur === abs) return;
  sendTermCd(abs).catch(function () { /* 终端不可用则忽略 */ });
}

function signatureOf(data) {
  return data.path + "|" + data.entries.map(function (entry) {
    return [entry.name, entry.dir ? 1 : 0, entry.kind, entry.size,
            entry.kind === "image" ? entry.ts : 0].join(":");
  }).join("|");
}

async function watchDir() {
  if (state.viewing || document.hidden) return;
  try {
    const data = await api("/api/list?path=" + q(state.cwd));
    if (signatureOf(data) === state.signature) return;
    await load(state.cwd, true);
  } catch (err) { /* 忽略目录监测错误 */ }
}

// 图片缩略图布局：按当前目录图片数量与可用宽度/视口高度动态计算列数和高度。
// 单图按两列布局的“单张瓦片”尺寸计算，与两图时的缩略图大小一致并居中；
// 多图按最小瓦片宽度排布，行数越多单张越矮，避免整页被图片撑满。
function molLayoutGallery() {
  const gallery = $("gallery");
  if (!gallery || gallery.classList.contains("hidden")) return;
  const count = gallery.querySelectorAll(".shot").length;
  if (!count) return;
  const W = gallery.clientWidth || (gallery.parentElement && gallery.parentElement.clientWidth) || window.innerWidth || 900;
  const vh = window.innerHeight || 800;
  const gap = 16;
  // 单图借用两图的布局参数计算尺寸，保证瓦片大小完全相同。
  const layoutCount = Math.max(count, 2);
  const minTile = W < 640 ? 150 : 210;
  let cols = Math.max(2, Math.min(6, Math.floor((W + gap) / (minTile + gap))));
  cols = Math.min(cols, layoutCount);
  const rows = Math.ceil(layoutCount / cols);
  const tileW = Math.max(80, (W - (cols - 1) * gap) / cols);
  const budget = Math.min(Math.max(260, vh * 0.72), 760);
  const maxH = Math.min(380, Math.max(180, vh * 0.42));
  let h = Math.floor((budget - (rows - 1) * gap - rows * 36) / rows);
  h = Math.max(130, Math.min(maxH, h));
  h = Math.min(h, Math.max(130, Math.round(tileW * 0.85)));
  if (count === 1) {
    gallery.style.gridTemplateColumns = tileW + "px";
    gallery.style.justifyContent = "center";
  } else {
    gallery.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";
    gallery.style.justifyContent = "";
  }
  Array.prototype.forEach.call(gallery.querySelectorAll(".shot img"), function (img) {
    img.style.height = h + "px";
  });
}
let galleryResizeTimer = null;
window.addEventListener("resize", function () {
  clearTimeout(galleryResizeTimer);
  galleryResizeTimer = setTimeout(molLayoutGallery, 120);
});

async function load(path, quiet) {
  // 真正切换目录前，先处理未保存的文本修改与已调整的 3D 视图。
  if (path !== state.cwd && dirtyMasks().length) {
    if (!(await resolveUnsaved())) return false;
  }
  try {
    const data = await api("/api/list?path=" + q(path));
    if (data.path !== state.cwd) closeMenu();
    state.cwd = data.path;
    state.signature = signatureOf(data);
    state.viewing = null;
    let basePath = data.root;
    while (basePath.length > 1 && basePath.endsWith("/")) { basePath = basePath.slice(0, -1); }
    if (basePath === "/") { basePath = ""; }
    let pathLabel;
    if (data.path.charAt(0) === "/") pathLabel = data.path;
    else pathLabel = data.path ? basePath + "/" + data.path : (basePath || "/");
    const pathInput = $("pathNote");
    pathInput.value = pathLabel;
    pathInput.dataset.label = pathLabel;
    renderCrumbs();
    showBrowser();

    const images = data.entries.filter(function (entry) {
      return !entry.dir && entry.kind === "image";
    });
    const others = data.entries.filter(function (entry) {
      return entry.dir || entry.kind !== "image";
    });

    const gallery = $("gallery");
    gallery.innerHTML = "";
    gallery.classList.toggle("hidden", images.length === 0);
    gallery.classList.toggle("g1", images.length === 1);
    gallery.classList.toggle("g2", images.length === 2);
    gallery.classList.toggle("g3", images.length >= 3);
    images.forEach(function (entry) {
      const tile = document.createElement("div");
      tile.className = "shot";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = entry.name;
      img.src = withSid("/raw?path=" + q(entry.path)) + "&v=" + encodeURIComponent(entry.ts);
      const cap = document.createElement("span");
      cap.textContent = entry.name;
      tile.appendChild(img);
      tile.appendChild(cap);
      addSelectBox(tile, entry);
      bindEntry(tile, entry);
      gallery.appendChild(tile);
    });
    molLayoutGallery();
    $("othersLabel").classList.toggle("hidden", images.length === 0 || others.length === 0);

    const rows = $("fileTable");
    rows.innerHTML = "";
    others.forEach(function (entry) {
      const card = document.createElement("div");
      card.className = "entry";

      const wrap = document.createElement("div");
      wrap.className = "name";
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = entry.name;
      wrap.appendChild(label);
      const tag = document.createElement("span");
      tag.className = "tag";
      const ext = quickExt(entry.name);
      const kindTag = entry.kind === "structure" ? "3D"
        : entry.kind === "pdf" ? tx("PDF")
        : entry.kind === "media" ? tx(entry.mediaType === "audio" ? "音频" : "视频")
        : entry.kind === "image" ? tx("图片")
        : QUICK_MD_EXTS.indexOf(ext) >= 0 ? tx("Markdown")
        : QUICK_TABLE_EXTS.indexOf(ext) >= 0 ? tx("表格")
        : ext === "json" ? "JSON"
        : ext === "xml" ? "XML"
        : ext === "xsd" ? "XSD" : tx("文件");
      tag.textContent = entry.dir ? tx("目录") : kindTag;
      wrap.appendChild(tag);
      card.appendChild(wrap);

      const meta = document.createElement("span");
      meta.className = "chip-meta";
      meta.textContent = fmtSize(entry.size) + " · " + entry.mtime;
      card.appendChild(meta);

      addSelectBox(card, entry);
      bindEntry(card, entry);
      rows.appendChild(card);
    });
    $("fileTable").classList.toggle("hidden", others.length === 0);
    $("empty").classList.toggle("hidden", data.entries.length > 0);
    // 点击目录/面包屑/右键进入目录后，让终端 cwd 跟随页面目录。
    syncTermToDir(pathLabel);
  } catch (err) {
    if (!quiet) toast(err.message, true);
  }
}

function setQuickAction(label, icon) {
  const action = $("quickAction");
  const text = tx(label);
  action.classList.toggle("win-icon", icon);
  action.querySelector(".win-glyph").classList.toggle("hidden", !icon);
  action.querySelector(".action-text").textContent = icon ? "" : text;
  action.title = text;
  action.setAttribute("aria-label", text);
}

// 新建目录/新建文本/重命名弹窗：顶栏只保留“存档”“关闭”两个按钮。
function setQuickDialogToolbar(onSave) {
  const view = $("quickView");
  const min = view.querySelector(".min-btn");
  const restore = view.querySelector(".restore-btn");
  if (min) min.classList.add("hidden");
  if (restore) restore.classList.add("hidden");
  $("btnQuickMax").classList.add("hidden");
  const action = $("quickAction");
  action.classList.add("hidden");
  action.onclick = null;
  const archive = $("quickArchive");
  archive.classList.remove("hidden");
  archive.disabled = false;
  archive.onclick = onSave;
}

// 普通文件预览弹窗：恢复最小化/还原按钮。
function resetQuickToolbar() {
  const view = $("quickView");
  const min = view.querySelector(".min-btn");
  const restore = view.querySelector(".restore-btn");
  if (min) min.classList.remove("hidden");
  if (restore) restore.classList.remove("hidden");
}

function closeQuick() {
  clearDirty($("quickView"));
  resetModalMax($("quickView"));
  $("quickView").classList.add("hidden");
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  $("btnQuickMax").classList.remove("hidden");
  resetQuickToolbar();
  $("quickBody").innerHTML = "";
  const oldStatus = $("quickName").querySelector(".large-text-status");
  if (oldStatus) oldStatus.remove();
  resetQuickMedia();
  $("quickAction").onclick = null;
  $("quickAction").classList.add("hidden");
  $("quickArchive").onclick = null;
  $("quickArchive").classList.add("hidden");
  $("quickArchive").disabled = false;
  activeMask = null;
  if (!anyViewerOpen() && state.viewing) state.viewing = null;
}

/* 大文本只加载视窗附近的行，滚动右侧滚动条时按行号重新取窗口。 */
function openLargeTextView(path, data, rawUrl, body, action, archive) {
  const LINE_H = 20;
  const WINDOW = 800;
  const EDGE = 120;
  const total = Math.max(1, Number(data.totalLines || 1));
  setQuickAction("下载到电脑", true);
  action.onclick = function () { window.open(rawUrl, "_blank"); };
  archive.classList.add("hidden");
  archive.disabled = true;
  archive.onclick = null;

  const wrap = document.createElement("div");
  wrap.className = "large-text-view";
  wrap.innerHTML =
    '<div class="large-text-scroll" tabindex="0">' +
      '<div class="large-text-spacer" style="height:' + (total * LINE_H) + 'px"></div>' +
      '<pre class="large-text-window"></pre>' +
    "</div>";
  const scroll = wrap.querySelector(".large-text-scroll");
  const pre = wrap.querySelector(".large-text-window");
  const status = document.createElement("span");
  status.className = "large-text-status";
  $("quickName").appendChild(status);
  body.appendChild(wrap);

  let loadedStart = -1;
  let loadedCount = 0;
  let loading = false;
  let pending = null;
  let reqId = 0;
  let timer = null;

  function visibleLine() {
    return Math.max(0, Math.floor(scroll.scrollTop / LINE_H));
  }

  function render() {
    status.textContent = tx("只读分段加载") + " " + tx("已加载") + " " +
      (loadedStart + 1) + "-" + (loadedStart + loadedCount) + " / " + total + " " + tx("行");
  }

  function loadAround(line, force) {
    if (!force && loadedStart >= 0 && line >= loadedStart + EDGE &&
        line < loadedStart + loadedCount - EDGE) return;
    if (loading) { pending = line; return; }
    loading = true;
    const my = ++reqId;
    const start = Math.max(0, line - Math.floor(WINDOW / 2));
    api("/api/text?path=" + q(path) + "&start=" + start + "&count=" + WINDOW)
      .then(function (res) {
        if (my !== reqId || !wrap.isConnected) return;
        loadedStart = Number(res.start || 0);
        loadedCount = (res.lines || []).length;
        const chunk = (res.lines || []).join("\n");
        const xmlLabel = codeTextLabel(data.name);
        if (xmlLabel === "XML" || xmlLabel === "XSD") pre.innerHTML = xmlHighlight(chunk);
        else pre.textContent = chunk;
        pre.style.transform = "translateY(" + (loadedStart * LINE_H) + "px)";
        render();
      })
      .catch(function (err) {
        if (my !== reqId || !wrap.isConnected) return;
        status.textContent = tx("加载失败：") + err.message;
      })
      .finally(function () {
        loading = false;
        if (pending !== null) {
          const next = pending;
          pending = null;
          loadAround(next, true);
        }
      });
  }

  scroll.addEventListener("scroll", function () {
    const line = visibleLine();
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      loadAround(line + Math.max(1, Math.floor(scroll.clientHeight / LINE_H / 2)));
    }, 50);
  });
  setTimeout(function () { loadAround(0, true); }, 0);
}

function openQuick(path, data) {
  const mask = acquireMask("quickView", "view:" + path);
  clearDirty(mask);
  resetQuickToolbar();
  mask.dataset.dockTag = quickDockTag(data);
  state.viewing = path;
  $("quickView").classList.toggle("image-mode", data.kind === "image");
  $("quickView").classList.add("preview");
  $("quickName").textContent = data.name + " · " + fmtSize(data.size) + " · " + data.mtime;
  const body = $("quickBody");
  body.innerHTML = "";
  resetQuickMedia();
  const action = $("quickAction");
  action.classList.remove("hidden");
  action.disabled = false;
  const archive = $("quickArchive");
  archive.classList.add("hidden");
  archive.disabled = true;
  archive.onclick = null;
  const rawUrl = withSid(data.url || ("/raw?path=" + q(path)));
  if (data.kind === "pdf") {
    const frame = document.createElement("iframe");
    frame.className = "pdf-frame";
    frame.title = data.name;
    frame.src = rawUrl + "#view=FitH";
    body.appendChild(frame);
    setQuickAction("下载到电脑", true);
    action.onclick = function () { window.open(rawUrl, "_blank"); };
  } else if (data.kind === "media") {
    let media;
    if (data.mediaType === "audio") {
      const view = document.createElement("div");
      view.className = "audio-view";
      view.innerHTML = '<div class="audio-glyph"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V6l10-2v12M9 18a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3zm10-2a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3z"/></svg></div>' +
        "<div><div>" + escHtml(data.name) + '</div><div class="data-note">' + escHtml(tx("音频")) + "</div></div>";
      media = document.createElement("audio");
      media.preload = "metadata";
      media.src = rawUrl;
      view.appendChild(media);
      body.appendChild(view);
    } else {
      media = document.createElement("video");
      media.className = "quick-media";
      media.preload = "metadata";
      media.playsInline = true;
      media.src = rawUrl;
      body.appendChild(media);
    }
    quickMedia = media;
    $("quickPlayer").classList.remove("hidden");
    bindQuickMedia(media);
    setQuickAction("下载到电脑", true);
    action.onclick = function () { window.open(rawUrl, "_blank"); };
  } else if (data.kind === "image") {
    const box = document.createElement("div");
    box.className = "zoom-box";
    const img = document.createElement("img");
    img.src = rawUrl + "&v=" + Date.now();
    img.alt = data.name;
    img.draggable = false;
    box.appendChild(img);
    body.appendChild(box);
    bindImageZoom(box, img);
    setQuickAction("下载到电脑", true);
    action.onclick = function () { window.open(rawUrl, "_blank"); };
  } else if (data.kind === "largeText") {
    openLargeTextView(path, data, rawUrl, body, action, archive);
  } else {
    const ext = quickExt(data.name);
    if (QUICK_MD_EXTS.indexOf(ext) >= 0) {
      const view = document.createElement("div");
      view.className = "md-view";
      view.innerHTML = renderMarkdown(data.text || "");
      body.appendChild(view);
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
    } else if (QUICK_TABLE_EXTS.indexOf(ext) >= 0) {
      const view = document.createElement("div");
      view.innerHTML = renderDataTable(data.text || "", ext === "tsv" ? "\t" : ",");
      body.appendChild(view);
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
    } else if (ext === "json" || ext === "xml" || ext === "xsd") {
      body.innerHTML = ext === "json" ? renderJsonTree(data.text || "")
        : renderXmlText(data.text || "");
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
    } else {
      const area = document.createElement("textarea");
      area.value = data.text;
      area.spellcheck = false;
      area.addEventListener("input", function () {
        const changed = area.value !== data.text;
        archive.disabled = !changed;
        if (changed) markDirty(mask, { type: "text", path: path, name: data.name });
        else clearDirty(mask);
      });
      area.addEventListener("keydown", function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
          event.preventDefault();
          saveQuick(path, data.name, area);
        }
      });
      body.appendChild(area);
      setQuickAction("下载到电脑", true);
      action.onclick = function () { window.open(rawUrl, "_blank"); };
      // 文本文件在下载按钮左边显示“存档”：保存修改到服务器；未修改时不可点击
      archive.classList.remove("hidden");
      archive.disabled = true;
      archive.onclick = function () { saveQuick(path, data.name, area); };
    }
  }
  $("quickView").classList.remove("hidden");
  const area = body.querySelector("textarea");
  if (area) {
    area.focus();
    area.setSelectionRange(0, 0);
    area.scrollTop = 0;
  }
}

function bindImageZoom(box, img) {
  let scale = 1;
  let ox = 0;
  let oy = 0;
  let rotation = 0;
  let drag = null;
  let idleTimer = null;
  const IDLE_MS = 2600;

  // 左下角控件：复位按钮在缩放滑杆左边，↺/↻ 旋转按钮在缩放滑杆右边。
  // 闲置后淡到全透明，点一下图片再恢复半透明。
  const ctl = document.createElement("div");
  ctl.className = "zoom-ctl";
  ctl.setAttribute("role", "group");
  ctl.setAttribute("aria-label", tx("图片缩放"));
  const rot = document.createElement("div");
  rot.className = "mol-rot-group";
  rot.setAttribute("role", "group");
  rot.setAttribute("aria-label", tx("旋转"));
  rot.innerHTML =
    '<button id="imgRotL" class="tool-icon" type="button" title="' + tx("逆时针旋转") + '" aria-label="' + tx("逆时针旋转") + '"><span class="tool-glyph" aria-hidden="true">↺</span></button>' +
    '<button id="imgRotR" class="tool-icon" type="button" title="' + tx("顺时针旋转") + '" aria-label="' + tx("顺时针旋转") + '"><span class="tool-glyph" aria-hidden="true">↻</span></button>';
  const reset = document.createElement("button");
  reset.type = "button";
  reset.title = tx("恢复初始视图");
  reset.setAttribute("aria-label", reset.title);
  reset.innerHTML = '<span class="tool-glyph" aria-hidden="true">↫</span>';
  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = "0.2";
  slider.max = "8";
  slider.step = "0.05";
  slider.value = "1";
  slider.title = tx("图片缩放");
  slider.setAttribute("aria-label", tx("图片缩放"));
  ctl.appendChild(reset);
  ctl.appendChild(slider);
  ctl.appendChild(rot);
  box.appendChild(ctl);

  function reveal() {
    ctl.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () { ctl.classList.add("idle"); }, IDLE_MS);
  }
  function apply() {
    img.style.transform = "translate(" + ox + "px," + oy + "px) rotate(" + rotation + "deg) scale(" + scale + ")";
    slider.value = String(scale);
  }
  function resetView() {
    scale = 1;
    ox = 0;
    oy = 0;
    rotation = 0;
    apply();
    reveal();
  }
  function rotateBy(delta) {
    rotation = ((rotation + delta) % 360 + 360) % 360;
    apply();
    reveal();
  }
  rot.querySelector("#imgRotL").onclick = function (event) {
    event.stopPropagation();
    rotateBy(-90);
  };
  rot.querySelector("#imgRotR").onclick = function (event) {
    event.stopPropagation();
    rotateBy(90);
  };
  reset.addEventListener("click", function (event) {
    event.stopPropagation();
    resetView();
  });
  slider.addEventListener("input", function () {
    const next = Math.min(8, Math.max(0.2, Number(slider.value) || 1));
    const k = next / scale;
    ox = -k * ox;
    oy = -k * oy;
    scale = next;
    apply();
    reveal();
  });
  box.addEventListener("pointerdown", reveal, true);
  box.addEventListener("click", reveal, true);
  ctl.addEventListener("pointerenter", reveal);
  ctl.addEventListener("pointermove", reveal);

  box.addEventListener("wheel", function (event) {
    event.preventDefault();
    reveal();
    const rect = box.getBoundingClientRect();
    const cx = event.clientX - rect.left - rect.width / 2;
    const cy = event.clientY - rect.top - rect.height / 2;
    const next = Math.min(8, Math.max(0.2, scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
    if (next === scale) return;
    const k = next / scale;
    ox = cx - k * (cx - ox);
    oy = cy - k * (cy - oy);
    scale = next;
    apply();
  }, {passive: false});

  box.addEventListener("pointerdown", function (event) {
    if (event.target && event.target.closest && event.target.closest(".zoom-ctl")) return;
    if (event.button !== 0) return;
    drag = {x: event.clientX - ox, y: event.clientY - oy};
    box.classList.add("dragging");
    box.setPointerCapture(event.pointerId);
  });
  box.addEventListener("pointermove", function (event) {
    if (!drag) return;
    ox = event.clientX - drag.x;
    oy = event.clientY - drag.y;
    apply();
  });
  function endDrag() {
    drag = null;
    box.classList.remove("dragging");
  }
  box.addEventListener("pointerup", endDrag);
  box.addEventListener("pointercancel", endDrag);

  box.addEventListener("dblclick", function (event) {
    if (event.target && event.target.closest && event.target.closest(".zoom-ctl")) return;
    resetView();
  });
  reveal();
}

async function saveQuick(path, name, area) {
  const action = $("quickArchive");
  if (action) action.disabled = true;
  let saved = false;
  try {
    const data = await api("/api/file", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: path, text: area.value})
    });
    $("quickName").textContent = name + " · " + fmtSize(data.size) + " · " + data.mtime;
    const mask = area.closest && area.closest(".mol-mask");
    if (mask) clearDirty(mask);
    if (action) action.disabled = true;
    toast("已存档 " + data.path);
    saved = true;
  } catch (err) {
    toast(err.message, true);
    if (action) action.disabled = false;
  }
  return saved;
}

function openRename(entry) {
  acquireMask("quickView", "rename:" + entry.path);
  resetQuickMedia();
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  state.viewing = entry.path;
  $("quickName").textContent = tx("重命名 · ") + entry.name;
  const body = $("quickBody");
  body.innerHTML = "";
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = entry.name;
  input.spellcheck = false;
  body.appendChild(input);
  setQuickDialogToolbar(function () { doRename(entry, input); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      doRename(entry, input);
    }
  });
  $("quickView").classList.remove("hidden");
  input.focus();
  const dot = entry.name.lastIndexOf(".");
  if (dot > 0) input.setSelectionRange(0, dot);
  else input.select();
}

async function doRename(entry, input) {
  const name = input.value.trim();
  if (!name) { toast("名称不能为空", true); return; }
  if (name === entry.name) { closeQuick(); return; }
  const action = $("quickArchive");
  action.disabled = true;
  try {
    const data = await api("/api/rename", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: entry.path, name: name})
    });
    closeQuick();
    toast("已重命名为 " + data.name);
    await load(state.cwd, true);
  } catch (err) {
    toast(err.message, true);
    action.disabled = false;
  }
}

function openNewText() {
  acquireMask("quickView");
  resetQuickMedia();
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  state.viewing = state.cwd || "/";
  $("quickName").textContent = tx("新建文本文件 · ") + (state.cwd || tx("运行目录"));
  const body = $("quickBody");
  body.innerHTML = "";
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = tx("新建文本.txt");
  input.spellcheck = false;
  input.placeholder = tx("输入文件名");
  body.appendChild(input);
  setQuickDialogToolbar(function () { createText(input); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      createText(input);
    }
  });
  $("quickView").classList.remove("hidden");
  input.focus();
  input.setSelectionRange(0, input.value.lastIndexOf("."));
}

function openNewDir() {
  acquireMask("quickView");
  resetQuickMedia();
  $("quickView").classList.remove("image-mode");
  $("quickView").classList.remove("preview");
  state.viewing = state.cwd || "/";
  $("quickName").textContent = tx("新建目录 · ") + (state.cwd || tx("运行目录"));
  const body = $("quickBody");
  body.innerHTML = "";
  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = tx("新建文件夹");
  input.spellcheck = false;
  input.placeholder = tx("输入目录名");
  body.appendChild(input);
  setQuickDialogToolbar(function () { createDir(input); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); createDir(input); }
  });
  $("quickView").classList.remove("hidden");
  input.focus();
  input.select();
}

async function createText(input) {
  const name = input.value.trim();
  if (!name) { toast("请输入文件名", true); return; }
  const action = $("quickArchive");
  action.disabled = true;
  try {
    const data = await api("/api/new", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: state.cwd, name: name})
    });
    closeQuick();
    toast("已创建 " + data.name);
    await load(state.cwd, true);
    openFile(data.path, false);
  } catch (err) {
    toast(err.message, true);
    action.disabled = false;
  }
}

async function createDir(input) {
  const name = input.value.trim();
  if (!name) { toast("请输入目录名", true); return; }
  const action = $("quickArchive");
  action.disabled = true;
  try {
    const data = await api("/api/newdir", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: state.cwd, name: name})
    });
    closeQuick();
    toast("已创建目录 " + data.name);
    await load(state.cwd, true);
  } catch (err) {
    toast(err.message, true);
    action.disabled = false;
  }
}

function closeMenu() {
  const menu = $("fileMenu");
  if (menu.classList.contains("hidden")) return;
  menu.classList.add("hidden");
  menu.innerHTML = "";
}

function downloadFile(path) {
  window.open(withSid("/raw?path=" + q(path)), "_blank");
}

let confirmResolve = null;
function openConfirm(title, html, opts) {
  opts = opts || {};
  return new Promise(function (resolve) {
    confirmResolve = resolve;
    $("confirmTitle").textContent = tx(title || "确认");
    $("confirmMessage").innerHTML = html || "";
    const ok = $("confirmOk");
    ok.textContent = tx(opts.okText || "确定");
    ok.classList.toggle("danger", !!opts.danger);
    $("confirmCancel").textContent = tx(opts.cancelText || "取消");
    const extra = $("confirmExtra");
    if (extra) {
      extra.textContent = tx(opts.extraText || "不保存");
      extra.classList.toggle("hidden", !opts.extraText);
    }
    $("confirmMask").classList.remove("hidden");
  });
}
function closeConfirm(result) {
  const mask = $("confirmMask");
  if (mask.classList.contains("hidden")) return;
  mask.classList.add("hidden");
  if (confirmResolve) {
    confirmResolve(result);
    confirmResolve = null;
  }
}
$("confirmOk").onclick = function () { closeConfirm(true); };
$("confirmCancel").onclick = function () { closeConfirm(false); };
$("confirmExtra").onclick = function () { closeConfirm("extra"); };
$("confirmMask").addEventListener("click", function (ev) {
  if (ev.target === this) closeConfirm(false);
});
// 在全局 Escape 处理里也加确认弹窗
document.addEventListener("keydown", function (event) {
  if (event.key === "Escape" && confirmResolve) { closeConfirm(false); event.stopPropagation(); return; }
}, true);

/* ---- 未保存改动：文本编辑 / 3D 视图调整 ---- */
function maskDirty(mask) { return !!(mask && mask.dataset.dirty === "1"); }
function dirtyMasks() {
  return Array.prototype.slice.call(document.querySelectorAll(".mol-mask"))
    .filter(function (m) { return !m.classList.contains("hidden") && maskDirty(m); });
}
function markDirty(mask, info) {
  if (!mask) return;
  mask.dataset.dirty = "1";
  if (info) mask._unsaved = info;
}
function clearDirty(mask) {
  if (!mask) return;
  delete mask.dataset.dirty;
  delete mask._unsaved;
}
function maskOf(baseId) {
  if (activeMask && activeMask.dataset.baseId === baseId && !activeMask.classList.contains("hidden")) return activeMask;
  return document.querySelector('.mol-mask[data-base-id="' + baseId + '"]:not(.hidden)');
}
function setMolArchiveEnabled(on) {
  const btn = $("molArchive");
  if (btn) btn.disabled = !on;
}
function molMarkViewDirty() {
  if (!MC || !MC.viewDirtyArmed) return;
  const mask = maskOf("molView");
  if (mask) markDirty(mask, { type: "view" });
  setMolArchiveEnabled(true);
}

let molSaveResolve = null;
function saveMolView() {
  const mask = maskOf("molView");
  if (!mask || !MC.viewer) return Promise.resolve(false);
  openMolSave();
  return new Promise(function (resolve) { molSaveResolve = resolve; });
}

// 逐个处理未保存窗口：返回 true 可继续关闭/切换，false 表示用户取消。
async function resolveUnsaved(list) {
  const masks = list || dirtyMasks();
  for (let i = 0; i < masks.length; i++) {
    const mask = masks[i];
    if (!maskDirty(mask)) continue;
    switchMask(mask);
    const info = mask._unsaved || {};
    if (mask.dataset.baseId === "molView") {
      const answer = await openConfirm("视图已调整", tx("是否存档当前视图？"),
        { okText: "存档", extraText: "不保存", cancelText: "取消" });
      if (answer === false) return false;
      if (answer === true && !(await molSaveArchive())) return false;
    } else {
      const answer = await openConfirm("文件已修改",
        tx("文件已修改") + "：" + escHtml(info.name || "") + "，" + tx("是否存档修改？"),
        { okText: "存档", extraText: "不保存", cancelText: "取消" });
      if (answer === false) return false;
      if (answer === true) {
        const area = mask.querySelector("textarea");
        if (area && !(await saveQuick(info.path || "", info.name || "", area))) return false;
      }
    }
    clearDirty(mask);
  }
  return true;
}

async function closeQuickWithConfirm() {
  const mask = maskOf("quickView");
  if (!mask) { closeQuick(); return; }
  if (!(await resolveUnsaved([mask]))) return;
  switchMask(mask);
  closeQuick();
}

async function closeStructureWithConfirm() {
  const mask = maskOf("molView");
  if (!mask) { closeStructure(); return; }
  if (!(await resolveUnsaved([mask]))) return;
  switchMask(mask);
  closeStructure();
}

window.addEventListener("beforeunload", function (ev) {
  if (!dirtyMasks().length) return;
  ev.preventDefault();
  ev.returnValue = "";
});

async function confirmDelete(entry) {
  const label = entry.dir ? "删除目录" : "删除文件";
  const ok = await openConfirm(tx(label),
    tx("确定删除 <b>") + escHtml(entry.name) + tx("</b> 吗？<br>此操作不可恢复。"),
    { danger: true, okText: "删除" });
  if (!ok) return;
  try {
    await api("/api/delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: entry.path})
    });
    toast("已删除 " + entry.name);
    await load(state.cwd, true);
  } catch (err) {
    toast(err.message, true);
  }
}

function openMenu(entry, x, y) {
  const menu = $("fileMenu");
  menu.innerHTML = "";
  function add(label, fn) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = tx(label);
    btn.onclick = function () { closeMenu(); fn(); };
    menu.appendChild(btn);
  }
  if (entry.dir) {
    add("进入目录", function () { load(entry.path); });
  } else if (entry.kind === "structure") {
    add("查看立体构型", function () { openStructure(entry.path); });
    add("打开文本", function () { openFile(entry.path, false); });
  } else if (entry.kind === "image") {
    add("查看图片", function () { openFile(entry.path, false); });
  } else {
    add("打开", function () { openFile(entry.path, false); });
  }
  add("重命名", function () { openRename(entry); });
  if (!entry.dir) add("下载", function () { downloadFile(entry.path); });
  add("删除", function () { confirmDelete(entry); });
  // 目录面板浮动后会被 bringFloatToFront 提到 floatZ(30+)，菜单须高于当前浮窗
  // 才能看见；但保持低于最小化停靠图标(MIN_DOCK_Z)与确认对话框。
  menu.style.zIndex = String(Math.min(Math.max(14, floatZ + 1), MIN_DOCK_Z - 1));
  menu.classList.remove("hidden");
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8)) + "px";
  menu.style.top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8)) + "px";
}

function defaultAction(entry, anchor) {
  if (entry.dir) { load(entry.path); return; }
  if (entry.kind === "structure") { openStructure(entry.path, anchor); return; }
  openFile(entry.path, true, anchor);
}

function bindEntry(el, entry) {
  // 目录项支持长按与右键菜单；单击进入目录/打开文件
  let pressTimer = null;
  let pressX = 0;
  let pressY = 0;
  let longPressed = false;
  let rightClicked = false;

  function clearPress() {
    if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
  }

  el.addEventListener("contextmenu", function (event) {
    event.preventDefault();
    event.stopPropagation();
    rightClicked = true;
    longPressed = false;
    clearPress();
    openMenu(entry, event.clientX, event.clientY);
  });
  el.addEventListener("pointerdown", function (event) {
    if (event.button !== 0) return;
    rightClicked = false;
    pressX = event.clientX;
    pressY = event.clientY;
    longPressed = false;
    clearPress();
    pressTimer = setTimeout(function () {
      pressTimer = null;
      longPressed = true;
    }, 550);
  });
  el.addEventListener("pointermove", function (event) {
    if (!pressTimer) return;
    if (Math.abs(event.clientX - pressX) > 8 || Math.abs(event.clientY - pressY) > 8) clearPress();
  });
  el.addEventListener("pointerup", function (event) {
    const held = longPressed;
    clearPress();
    if (held) {
      openMenu(entry, pressX, pressY);
      event.preventDefault();
    }
  });
  el.addEventListener("pointercancel", function () {
    longPressed = false;
    clearPress();
  });
  el.addEventListener("pointerleave", clearPress);
  el.addEventListener("click", function (event) {
    if (longPressed || rightClicked) {
      longPressed = false;
      rightClicked = false;
      event.stopImmediatePropagation();
      event.preventDefault();
      return;
    }
    defaultAction(entry, el);
  });
}

async function openFile(path, fromClick, anchor) {
  try {
    const data = await api("/api/file?path=" + q(path));
    if (["text", "largeText", "image", "pdf", "media"].indexOf(data.kind) >= 0) {
      openQuick(path, data);
      return;
    }
    toast(fromClick ? "该文件无法预览，长按可选择下载" : "该文件为二进制，无法在窗口中打开", true, anchor);
  } catch (err) {
    toast(err.message, true, anchor);
  }
}

/* ---- 侧栏终端字符雨特效 ---- */
(function () {
  const box = $("termBox");
  const canvas = $("termRain");
  if (!box || !canvas) return;
  const ctx = canvas.getContext("2d");
  let raf = null, active = false, visible = true, last = 0, step = null;
  let paused = false, resizeTimer = null, lastTick = 0, disabled = false;

  function setup() {
    // 高分屏画布像素翻倍是卡顿来源之一，上限压到 1.5。
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const chars = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789=<>+-*/|\#@$%&";
    const fontSize = 13;
    const cols = Math.floor(w / fontSize);
    const drops = new Array(cols).fill(1).map(() => Math.random() * -20);
    return function () {
      ctx.fillStyle = "rgba(16, 21, 29, 0.09)";
      ctx.fillRect(0, 0, w, h);
      ctx.font = fontSize + "px ui-monospace, Menlo, Consolas, monospace";
      for (let i = 0; i < cols; i++) {
        const ch = chars[Math.floor(Math.random() * chars.length)];
        ctx.fillStyle = "rgba(126, 231, 135, 0.85)";
        ctx.fillText(ch, i * fontSize, drops[i] * fontSize);
        if (drops[i] * fontSize > h && Math.random() > 0.975) drops[i] = 0;
        drops[i]++;
      }
    };
  }

  function canRun() {
    // 字符雨只在侧栏终端显示；浮窗（含最小化停靠）不呈现。
    // 不再用 elementFromPoint 做遮挡检测：它会强制同步布局，在滚动/浮层堆叠时
    // 反复触发布局抖动，是卡顿主因。可见性改由 IntersectionObserver + 浮窗状态
    // + document.hidden + 交互暂停统一表达，覆盖/LICENSE 浮层下照常运行。
    const wrap = box.closest(".term-wrap");
    if (wrap && wrap.classList.contains("floating")) return false;
    // 用户执行过一次命令后永久关闭；页面目录点击产生的自动 cd 不走这条路径。
    if (disabled) return false;
    return !paused && !document.hidden && visible;
  }

  function frame(ts) {
    if (!active) return;
    if (!last || ts - last >= 60) {
      last = ts;
      try { step(); lastTick = Date.now(); }
      catch (err) { stop(); lastTick = 0; return; } // 绘制异常后停止，不再往下排队 RAF
    }
    raf = requestAnimationFrame(frame);
  }

  function start() {
    if (active || !canRun()) return;
    let next;
    try { next = setup(); } catch (err) { return; }
    step = next;
    active = true;
    canvas.style.opacity = "";
    last = 0;
    lastTick = Date.now();
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    active = false;
    canvas.style.opacity = "0";
    if (raf) { cancelAnimationFrame(raf); raf = null; }
  }

  // 卡死自恢复：RAF 停摆、绘制抛错、暂停标记残留时强制重建。
  function kick() {
    stop();
    lastTick = 0;
    start();
  }
  setInterval(function () {
    const now = Date.now();
    if (disabled) { stop(); return; }
    if (!canRun()) {
      if (paused && !resizeTimer) paused = false; // 暂停定时器丢失时解除卡住的暂停
      return;
    }
    if (!active || !lastTick || now - lastTick > 1500) kick();
  }, 1000);

  function syncRain() { if (canRun()) start(); else stop(); }
  // 全局 pointer/scroll 高频事件节流：避免每次事件都 setState 造成抖动。
  let rainSyncTimer = null;
  function scheduleSync() {
    if (rainSyncTimer) return;
    rainSyncTimer = setTimeout(function () { rainSyncTimer = null; syncRain(); }, 120);
  }
  ["pointerdown", "click", "scroll"].forEach(function (evt) {
    document.addEventListener(evt, scheduleSync, true);
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else start();
  });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      visible = entries[0].isIntersecting;
      if (visible) start(); else stop();
    }, { threshold: 0.01 }).observe(box);
  }
  // 统一暂停入口：模式切换、浮窗缩放、页面缩放、终端交互都走这里；结束后按当前终端尺寸重建。
  function pauseRain(ms) {
    const wait = typeof ms === "number" && ms > 0 ? ms : 180;
    paused = true;
    stop();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      resizeTimer = null;
      paused = false;
      start();
    }, wait);
  }
  function pauseRainForResize() { pauseRain(180); }
  // 用户真正输入并回车执行过命令后关闭字符雨；目录点击触发的自动 cd 不会调用这里。
  function disableRain() {
    if (disabled) return;
    disabled = true;
    clearTimeout(resizeTimer);
    resizeTimer = null;
    paused = false;
    stop();
  }
  window.addEventListener("resize", pauseRainForResize);
  if ("ResizeObserver" in window) {
    let roFirst = true;
    new ResizeObserver(function () {
      if (roFirst) { roFirst = false; return; }
      pauseRainForResize();
    }).observe(box);
  }
  // 鼠标选择、键盘输入期间暂停字符雨，停止操作后自动恢复。
  box.addEventListener("pointerdown", function () { pauseRain(500); }, true);
  box.addEventListener("pointermove", function (e) { if (e.buttons) pauseRain(500); }, true);
  box.addEventListener("pointerup", function () { pauseRain(500); }, true);
  box.addEventListener("keydown", function () { pauseRain(500); }, true);
  box.addEventListener("input", function () { pauseRain(500); }, true);
  start();
  window.__mctaRainPause = function (ms) { pauseRain(ms); };
  window.__mctaRainResize = function () { pauseRain(180); };
  window.__mctaRainDisable = disableRain;
  window.__mctaRainKick = kick;
  window.__mctaRainState = function () {
    return { active: active, paused: paused, disabled: disabled, lastTick: lastTick, canRun: canRun() };
  };
})();

function legacyCopyText(text) {
  const active = document.activeElement;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
  ta.remove();
  if (active && active.focus) {
    try { active.focus(); } catch (err) { /* 忽略 */ }
  }
  return ok;
}

function fitTerm() {
  if (!state.term) return;
  const next = termSize();
  state.term.resize(next.cols, next.rows);
  centerTermGrid(next);
}

function startTerminal() {
  if (state.term || !state.user || !window.Terminal) return;
  $("termHint").classList.add("hidden");
  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: 'ui-monospace, Consolas, "Courier New", monospace',
    theme: {background: "#10151d", foreground: "#d7deea", cursor: "#7fa8ff", selectionBackground: "#2a3b57"}
  });
  term.open($("termBox"));
  state.term = term;
  fitTerm();

  const termBox = $("termBox");
  termBox.addEventListener("mouseup", function () {
    setTimeout(function () {
      const text = state.term ? state.term.getSelection() : "";
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          toast("已复制选中文字");
        }, function () {
          if (legacyCopyText(text)) {
            toast("已复制选中文字");
            if (state.term) state.term.focus();
          }
        });
      } else if (legacyCopyText(text)) {
        toast("已复制选中文字");
        if (state.term) state.term.focus();
      }
    }, 0);
  });
  termBox.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    if (!(navigator.clipboard && navigator.clipboard.readText)) {
      toast("无法读取剪切板", true);
      return;
    }
    navigator.clipboard.readText().then(function (text) {
      if (!text) { toast("剪切板为空"); return; }
      if (state.term.paste) state.term.paste(text);
      else state.term.write(text);
      toast("已粘贴剪切板内容");
    }, function () {
      toast("无法读取剪切板", true);
    });
  }, true);

  let cwdKick = null;
  term.onData(function (data) {
    api("/api/term/input", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({data: b64encode(data), sid: SESSION_ID})
    }).catch(function (err) { toast(err.message, true); });
    if (data.indexOf("\r") >= 0 || data.indexOf("\n") >= 0) {
      // 只有真实终端输入回车才判定为用户执行命令；页面目录跳转走 sendTermCd，不会触发这里。
      if (window.__mctaRainDisable) window.__mctaRainDisable();
      clearTimeout(cwdKick);
      cwdKick = setTimeout(syncCwd, 200);
    }
  });

  term.onResize(function (ev) {
    api("/api/term/resize", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({cols: ev.cols, rows: ev.rows, sid: SESSION_ID})
    }).catch(function () { /* 忽略 */ });
  });

  const es = new EventSource("/api/term/stream?cols=" + term.cols + "&rows=" + term.rows + "&sid=" + q(SESSION_ID));
  state.es = es;
  es.onmessage = function (event) {
    if (!event.data) return;
    term.write(b64decode(event.data));
  };
  es.onerror = function () {
    $("termState").textContent = tx("连接中断，正在重试…") + " · " + state.user;
  };
  es.onopen = function () {
    $("termState").textContent = tx("已连接") + " · " + state.user;
  };

  state.cwdTimer = setInterval(syncCwd, 400);
  syncCwd();

  window.addEventListener("resize", function () {
    if (!state.term) return;
    fitTerm();
  });
}

/* ---- 终端浮窗：点击终端顶端栏浮起，可拖动、缩放、停靠、最小化 ---- */
(function initTermFloat() {
  const box = $("termBox");
  const wrap = box ? box.closest(".term-wrap") : null;
  if (!wrap) return;
  const head = wrap.querySelector(".term-head");
  const tools = wrap.querySelector(".term-tools");
  const handles = wrap.querySelectorAll(".resize-handle");
  const dockParent = wrap.parentNode;
  const dockNext = wrap.nextSibling;
  const UI_KEY = "mcta-term-ui";
  let uiMode = "dock";        // 'dock' | 'float'
  let maximized = false;
  let minimized = false;
  let prevRect = null;
  let drag = null;
  let resize = null;
  let uiState = {};

  try { uiState = JSON.parse(localStorage.getItem(UI_KEY) || "{}") || {}; }
  catch (e) { uiState = {}; }

  function saveUI(patch) {
    Object.keys(patch).forEach(function (k) { uiState[k] = patch[k]; });
    try { localStorage.setItem(UI_KEY, JSON.stringify(uiState)); } catch (e) { /* 忽略 */ }
  }

  function currentRect() {
    const r = wrap.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  // 最小高度与侧栏终端一致，缩得太小时边框会比 xterm 字符显示区还小。
  function minTermHeight() {
    let n = 0;
    try { n = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--term-side-h")); }
    catch (err) { /* 忽略 */ }
    return Number.isFinite(n) && n > 0 ? n : 310;
  }
  const MIN_W = 260, MIN_H = minTermHeight();

  function clampRect(r) {
    const maxW = Math.max(MIN_W, window.innerWidth - 8);
    const maxH = Math.max(MIN_H, window.innerHeight - 4);
    r.w = Math.min(Math.max(MIN_W, r.w || 520), maxW);
    r.h = Math.min(Math.max(MIN_H, r.h || 380), maxH);
    // 约束顶栏边沿的中心点：顶栏上边沿中心 (x+w/2, y) 与下边沿中心 (x+w/2, y+HEAD)
    // 都必须留在页面内。水平按中心点，垂直上边沿>=0、下边沿<=innerHeight。
    const HEAD = 44;
    r.x = Math.min(Math.max(-r.w / 2, r.x || 0), window.innerWidth - r.w / 2);
    r.y = Math.min(Math.max(0, r.y || 0), Math.max(0, window.innerHeight - HEAD));
    return r;
  }

  function applyRect(r) {
    wrap.style.left = Math.round(r.x) + "px";
    wrap.style.top = Math.round(r.y) + "px";
    wrap.style.width = Math.round(r.w) + "px";
    wrap.style.height = Math.round(r.h) + "px";
  }

  function maxRect() {
    // 与目录/文件浮窗一致：顶端紧贴页面，底部留 4px。
    return { x: 4, y: 0, w: window.innerWidth - 8, h: window.innerHeight - 4 };
  }

  function defaultRect() {
    const w = Math.min(560, Math.max(300, window.innerWidth - 32));
    const h = Math.min(420, Math.max(240, window.innerHeight - 120));
    // 初始向左下贴紧屏幕边缘（与最小化停靠栏一致的 4px 边距）
    return clampRect({ x: 4, y: window.innerHeight - h - 4, w: w, h: h });
  }

  function floatAt(rect) {
    if (uiMode !== "float") {
      document.body.appendChild(wrap);
      wrap.classList.add("floating");
      uiMode = "float";
    }
    wrap.classList.remove("win-min");
    markTopSnap(wrap, false);
    minDockRemove(wrap);
    layoutMinDock(); // 终端离开停靠栏后，其余图标自动左移补位
    bringFloatToFront(wrap);
    applyRect(clampRect({ x: rect.x, y: rect.y, w: rect.w, h: rect.h }));
    maximized = false;
    minimized = false;
    prevRect = null;
    showHandles(true);
    syncTools();
    scheduleFit();
  }

  function dock() {
    if (uiMode !== "float") return;
    wrap.classList.remove("floating", "win-min");
    markTopSnap(wrap, false);
    minDockRemove(wrap);
    layoutMinDock(); // 终端离开停靠栏后，其余图标自动补位
    wrap.style.left = wrap.style.top = wrap.style.width = wrap.style.height = "";
    wrap.style.zIndex = "";
    showHandles(false);
    dockParent.insertBefore(wrap, dockNext && dockNext.parentNode === dockParent ? dockNext : null);
    uiMode = "dock";
    maximized = false;
    minimized = false;
    prevRect = null;
    saveUI({ mode: "dock", x: null, y: null, w: null, h: null, max: false, restore: null });
    syncTools();
    scheduleFit();
  }

  function minimizeWin() {
    if (uiMode !== "float" || minimized) return;
    // 最小化前记录当前几何，供还原时恢复；最大化态先还原到之前的尺寸再记录。
    let r = currentRect();
    if (maximized && prevRect) {
      applyRect(prevRect);
      r = currentRect();
    }
    minimized = true;
    maximized = false;
    prevRect = null;
    wrap.classList.add("win-min");
    showHandles(false);
    minDockAdd(wrap);
    bringFloatToFront(wrap);
    layoutMinDock();
    saveUI({ mode: "float", min: true, x: r.x, y: r.y, w: r.w, h: r.h, max: false, restore: null });
    syncTools();
    scheduleFit();
  }

  function restoreWin() {
    if (uiMode !== "float") { floatAt(uiState.w ? uiState : defaultRect()); return; }
    if (!minimized) { resetToDefault(); return; }
    minimized = false;
    wrap.classList.remove("win-min");
    minDockRemove(wrap);
    const saved = (typeof uiState.w === "number" && uiState.w > 0)
      ? { x: uiState.x, y: uiState.y, w: uiState.w, h: uiState.h } : null;
    floatAt(saved || defaultRect());
    saveUI({ min: false });
    layoutMinDock();
  }

  function resetToDefault() {
    floatAt(defaultRect());
  }

  function scheduleFit() {
    // 侧栏/浮窗切换、最小化还原、浮窗缩放结束后都要按新尺寸重建字符雨。
    if (window.__mctaRainPause) window.__mctaRainPause(180);
    requestAnimationFrame(function () {
      fitTerm();
      if (window.__mctaRainResize) window.__mctaRainResize();
    });
  }

  function syncTools() {
    if (tools) {
      const labels = {
        min: tx("最小化"),
        restore: tx("还原"),
        max: maximized ? tx("缩回原始大小") : tx("放大到整个页面"),
        dock: tx("还原到侧栏")
      };
      tools.querySelectorAll("button[data-term-act]").forEach(function (b) {
        const label = labels[b.getAttribute("data-term-act")];
        if (!label) return;
        b.title = label;
        b.setAttribute("aria-label", label);
      });
      // 最大化按钮与文件浮窗同款：⬀/⬃ 双图标切换
      const maxBtn = tools.querySelector('button[data-term-act="max"]');
      if (maxBtn) setModalMaxButton(maxBtn, maximized);
    }
    // 提示只挂在终端顶栏：悬停终端内部不再出现“点击终端顶端栏可浮动为小窗口”。
    if (wrap) wrap.title = "";
    if (head) head.title = uiMode === "float" ? "" : tx("点击终端顶端栏可浮动为小窗口");
  }

  function showHandles(show) {
    const display = show ? "block" : "none";
    handles.forEach(function (h) { h.style.display = display; });
  }

  function persistRect() {
    if (uiMode !== "float" || minimized) return;
    const r = currentRect();
    saveUI({
      mode: "float", min: false, x: r.x, y: r.y, w: r.w, h: r.h,
      max: maximized, restore: maximized ? prevRect : null
    });
  }

  function toggleMax() {
    if (uiMode !== "float") return;
    if (minimized) restoreWin();
    if (maximized) {
      maximized = false;
      if (prevRect) applyRect(clampRect(prevRect));
      prevRect = null;
    } else {
      prevRect = currentRect();
      maximized = true;
      applyRect(maxRect());
    }
    persistRect();
    syncTools();
    scheduleFit();
  }

  if (tools) {
    tools.addEventListener("click", function (e) {
      const btn = e.target.closest("button[data-term-act]");
      if (!btn) return;
      e.stopPropagation();
      const act = btn.getAttribute("data-term-act");
      if (act === "dock") { if (uiMode === "float") dock(); return; }
      if (uiMode !== "float") floatAt(uiState.w ? uiState : defaultRect());
      if (act === "max") { toggleMax(); return; }
      if (act === "min") { minimizeWin(); return; }
      if (act === "restore") { restoreWin(); return; }
    });
  }

  if (head) {
    head.addEventListener("pointerdown", function (e) {
      if (e.target.closest("button") || minimized) return;
      if (uiMode !== "float") floatAt(uiState.w ? uiState : defaultRect());
      const r = currentRect();
      drag = { dx: e.clientX - r.x, dy: e.clientY - r.y, w: r.w, h: r.h, id: e.pointerId };
      try { head.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      wrap.classList.add("dragging");
    });
    head.addEventListener("pointermove", function (e) {
      if (!drag) return;
      e.preventDefault();
      const raw = { x: e.clientX - drag.dx, y: e.clientY - drag.dy, w: drag.w, h: drag.h };
      const r = clampRect(raw);
      if (raw.y <= (drag.snap ? TOP_SNAP_HYST : TOP_SNAP_Y)) {
        if (!drag.snap) drag.prev = { w: r.w, h: r.h };
        drag.snap = true;
        const snapped = topSnapRect(r);
        drag.w = snapped.w;
        drag.h = snapped.h;
        applyRect(snapped);
        markTopSnap(wrap, true);
      } else {
        if (drag.snap && drag.prev) { drag.w = drag.prev.w; drag.h = drag.prev.h; }
        drag.snap = false;
        markTopSnap(wrap, false);
        applyRect(clampRect({ x: e.clientX - drag.dx, y: raw.y, w: drag.w, h: drag.h }));
      }
      maximized = false;
    });
    const endDrag = function () {
      if (!drag) return;
      try { head.releasePointerCapture(drag.id); } catch (err) { /* 忽略 */ }
      drag = null;
      wrap.classList.remove("dragging");
      persistRect();
      syncTools();
      // 拖到顶端吸附半屏后几何已改变，必须重算 xterm 行列，
      // 否则仍按浮窗初始高度渲染，字符只占屏幕上半部分。
      scheduleFit();
    };
    head.addEventListener("pointerup", endDrag);
    head.addEventListener("pointercancel", endDrag);
    // 最小化态点击顶栏文字还原（跳过按钮）
    head.addEventListener("click", function (e) {
      if (!minimized || e.target.closest("button")) return;
      e.stopPropagation();
      restoreWin();
    });
  }

  handles.forEach(function (h) {
    h.addEventListener("pointerdown", function (e) {
      e.stopPropagation();
      if (window.__mctaRainPause) window.__mctaRainPause(300);
      maximized = false; prevRect = null;
      markTopSnap(wrap, false);
      const r = currentRect();
      const cls = h.className;
      let sx = e.clientX, sy = e.clientY;
      resize = {
        startX: sx, startY: sy,
        x: r.x, y: r.y, w: r.w, h: r.h,
        edgeT: cls.indexOf("rh-t") >= 0 && cls.indexOf("rh-tr") < 0 && cls.indexOf("rh-tl") < 0,
        edgeB: cls.indexOf("rh-b") >= 0 && cls.indexOf("rh-br") < 0 && cls.indexOf("rh-bl") < 0,
        edgeL: cls.indexOf("rh-l") >= 0 && cls.indexOf("rh-tl") < 0 && cls.indexOf("rh-bl") < 0,
        edgeR: cls.indexOf("rh-r") >= 0 && cls.indexOf("rh-tr") < 0 && cls.indexOf("rh-br") < 0,
        cornerTL: cls.indexOf("rh-tl") >= 0,
        cornerTR: cls.indexOf("rh-tr") >= 0,
        cornerBL: cls.indexOf("rh-bl") >= 0,
        cornerBR: cls.indexOf("rh-br") >= 0,
        id: e.pointerId
      };
      try { h.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      wrap.classList.add("dragging");
    });
    h.addEventListener("pointermove", function (e) {
      if (!resize) return;
      e.preventDefault();
      if (window.__mctaRainPause) window.__mctaRainPause(300);
      const dx = e.clientX - resize.startX;
      const dy = e.clientY - resize.startY;
      let x = resize.x, y = resize.y, w = resize.w, h = resize.h;
      if (resize.edgeR || resize.cornerTR || resize.cornerBR) w = resize.w + dx;
      if (resize.edgeL || resize.cornerTL || resize.cornerBL) { w = Math.max(MIN_W, resize.w - dx); x = resize.x + (resize.w - w); }
      if (resize.edgeB || resize.cornerBL || resize.cornerBR) h = resize.h + dy;
      if (resize.edgeT || resize.cornerTL || resize.cornerTR) { h = Math.max(MIN_H, resize.h - dy); y = resize.y + (resize.h - h); }
      const r = clampRect({ x: x, y: y, w: w, h: h });
      wrap.style.left = Math.round(r.x) + "px";
      wrap.style.top = Math.round(r.y) + "px";
      wrap.style.width = Math.round(r.w) + "px";
      wrap.style.height = Math.round(r.h) + "px";
    });
    const endResize = function () {
      if (!resize) return;
      try { h.releasePointerCapture(resize.id); } catch (err) { /* 忽略 */ }
      resize = null;
      wrap.classList.remove("dragging");
      persistRect();
      scheduleFit();
    };
    h.addEventListener("pointerup", endResize);
    h.addEventListener("pointercancel", endResize);
  });

  window.addEventListener("resize", function () {
    if (uiMode !== "float") return;
    if (maximized) applyRect(maxRect());
    else applyRect(clampRect(currentRect()));
    scheduleFit();
  });

  syncTools();
  if (uiState.mode === "float") {
    const saved = {
      x: typeof uiState.x === "number" ? uiState.x : window.innerWidth - 580,
      y: typeof uiState.y === "number" ? uiState.y : window.innerHeight - 460,
      w: uiState.w || 560,
      h: uiState.h || 420
    };
    if (uiState.min) {
      // 上次停靠在最小化栏：浮起后立即转为最小化并重新加入停靠栏。
      floatAt(saved);
      minimizeWin();
    } else {
      floatAt(saved);
      if (uiState.max) {
        maximized = true;
        prevRect = uiState.restore || null;
        applyRect(maxRect());
        syncTools();
        scheduleFit();
      }
    }
  }
})();

function applyInfo(info) {
  state.user = info.user;
  state.root = info.root;
  $("rootPath").textContent = info.root;
  $("rootLabel").textContent = tx("运行目录");
  $("authText").textContent = info.user;
  $("termState").textContent = tx("连接中…") + " · " + info.user;
}

/* ---- 浮窗拖到页面顶端时的吸附放大 ---- */
// 阈值很小：只有顶栏真的贴到页面上沿才触发，普通拖动不受影响。
const TOP_SNAP_Y = 2;        // 触发吸附：顶栏抵达页面上沿
const TOP_SNAP_HYST = 24;    // 离开阈值：避免轻微抖动就退出吸附
// 按视口宽高比分屏：窄屏整屏；≤2 两屏、≤3 三屏、≤4 四屏、≤5 五屏、>5 六屏。
// 横向选区按吸附瞬间窗口中心的落点判断，顶端贴紧页面、底部与最大化几何一致留 4px。
function topSnapRect(rect) {
  const vw = window.innerWidth, vh = window.innerHeight;
  // 与最大化几何一致：左右各留 4px，顶端贴紧页面、底部留 4px。
  const fullW = Math.max(320, vw - 8);
  const fullH = Math.max(200, vh - 4);
  const center = rect.x + rect.w / 2;
  const ratio = vw / Math.max(1, vh);
  const cols = ratio <= 1.1 ? 1 : (ratio <= 2 ? 2 : (ratio <= 3 ? 3 : (ratio <= 4 ? 4 : (ratio <= 5 ? 5 : 6))));
  const w = Math.floor(fullW / cols);
  let x = 4;
  if (cols > 1) {
    const col = Math.max(0, Math.min(cols - 1, Math.floor(center / (vw / cols))));
    // 最右一列以右缘留 4px 为准，与全屏/左半屏一致。
    x = col === cols - 1 ? vw - w - 4 : 4 + col * w;
  }
  return { x: Math.round(x), y: 0, w: w, h: fullH };
}
function markTopSnap(el, on) {
  if (!el || !el.dataset) return;
  if (on) el.dataset.topSnap = "1";
  else delete el.dataset.topSnap;
}

// 弹窗最大化：占满整个页面，再点一次回到原始大小
function setModalMaxButton(btn, on) {
  const maxIcon = btn.querySelector(".max-icon");
  const restoreIcon = btn.querySelector(".restore-icon");
  if (maxIcon && restoreIcon) {
    maxIcon.classList.toggle("hidden", on);
    restoreIcon.classList.toggle("hidden", !on);
  } else {
    btn.textContent = on ? tx("还原") : tx("放大");
  }
  const title = on ? tx("缩回原始大小") : tx("放大到整个页面");
  btn.title = title;
  btn.setAttribute("aria-label", title);
}

function resetModalMax(mask) {
  mask.classList.remove("maxed");
  const btn = mask.querySelector(".max-btn");
  if (btn) setModalMaxButton(btn, false);
}

Array.prototype.forEach.call(document.querySelectorAll(".max-btn"), function (btn) {
  btn.onclick = function () {
    const mask = this.closest(".mol-mask");
    const win = mask.querySelector(".mol-win");
    // 最小化态下先还原窗口，再执行最大化
    if (win && win.classList.contains("win-min")) {
      win.classList.remove("win-min");
      minDockRemove(win);
      const saved = mask.dataset.minRect;
      if (saved) { try { const o = JSON.parse(saved); mask._applyFree(o); } catch (e) {} }
      delete mask.dataset.minRect;
      restoreDockTitle(mask);
      layoutMinDock();
    }
    const on = !mask.classList.contains("maxed");
    mask.classList.toggle("maxed", on);
    setModalMaxButton(this, on);
    if (mask.dataset.baseId === "molView" && MC.viewer) {
      requestAnimationFrame(function () { MC.viewer.resize(); MC.viewer.render(); });
    }
  };
});

/* ---- 弹窗浮动：拖动标题栏、右下角调整大小、还原到初始状态 ---- */
function initModalFloating(mask) {
  const MIN_W = 320;
  const MIN_H = 200;
  function winOf(mask) { return mask.querySelector(".mol-win"); }

  function ensureHandle(mask) {
    const win = winOf(mask);
    if (!win) return;
    ["t", "b", "l", "r", "tl", "tr", "bl", "br"].forEach(function (part) {
      if (!win.querySelector(".mol-rh-" + part)) {
        const h = document.createElement("span");
        h.className = "mol-rh mol-rh-" + part;
        h.setAttribute("aria-hidden", "true");
        h.dataset.corner = part;
        win.appendChild(h);
      }
    });
  }

  function snapshot(mask) {
    // 记录初始位置/尺寸：以未拖动状态下浏览器布局为准
    const win = winOf(mask);
    if (!win) return null;
    if (mask.dataset.initRect) {
      try { return JSON.parse(mask.dataset.initRect); } catch (e) { /* 忽略 */ }
    }
    // 计算 mask 的 flex 居中位置
    const wasFree = win.classList.contains("free");
    const saved = wasFree ? {
      left: win.style.left, top: win.style.top,
      width: win.style.width, height: win.style.height
    } : null;
    if (wasFree) {
      win.classList.remove("free");
      win.style.left = win.style.top = win.style.width = win.style.height = "";
    }
    const r = win.getBoundingClientRect();
    const rect = { x: r.left, y: r.top, w: r.width, h: r.height };
    mask.dataset.initRect = JSON.stringify(rect);
    if (wasFree) {
      win.classList.add("free");
      win.style.left = saved.left; win.style.top = saved.top;
      win.style.width = saved.width; win.style.height = saved.height;
    }
    return rect;
  }

  function applyFree(mask, rect) {
    const win = winOf(mask);
    if (!win) return;
    win.classList.add("free");
    win.style.left = Math.round(rect.x) + "px";
    win.style.top = Math.round(rect.y) + "px";
    win.style.width = Math.round(rect.w) + "px";
    win.style.height = Math.round(rect.h) + "px";
    ensureHandle(mask);
  }

  function resetFree(mask) {
    const win = winOf(mask);
    if (!win) return;
    win.classList.remove("free", "win-min");
    markTopSnap(win, false);
    minDockRemove(win);
    layoutMinDock(); // 浮窗关闭/隐藏后，其余停靠图标自动补位
    restoreDockTitle(mask);
    win.style.left = win.style.top = win.style.width = win.style.height = "";
    delete mask.dataset.initRect;
    delete mask.dataset.minRect;
    if (mask.dataset.baseId === "molView" && MC.viewer) {
      requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
    }
  }

  function clampRect(r) {
    r.w = Math.min(Math.max(MIN_W, r.w), window.innerWidth - 16);
    r.h = Math.min(Math.max(MIN_H, r.h), window.innerHeight - 16);
    // 约束顶栏边沿的中心点：上边沿中心 (x+w/2, y)、下边沿中心 (x+w/2, y+HEAD) 留在页面内。
    // 与终端浮窗使用同一判断，窗口最多移出半宽，顶栏始终留在屏幕内。
    const HEAD = 44;
    r.x = Math.min(Math.max(-r.w / 2, r.x), window.innerWidth - r.w / 2);
    r.y = Math.min(Math.max(0, r.y), Math.max(0, window.innerHeight - HEAD));
    return r;
  }

  mask._snapshot = function () { return snapshot(mask); };
  mask._applyFree = function (rect) { applyFree(mask, rect); };
  mask._resetFree = function () { resetFree(mask); };
  // 页面尺寸变化时，对已自由定位且非最小化的浮窗重新 clamp，保证顶栏中心点仍在页面内。
  mask._reclamp = function () {
    const win = winOf(mask);
    if (!win || !win.classList.contains("free") || win.classList.contains("win-min")) return;
    if (mask.classList.contains("maxed")) return;
    applyFree(mask, clampRect(snapshot(mask)));
  };

  const head = mask.querySelector(".mol-head");
  const win = winOf(mask);
  if (!head || !win) return;
    ensureHandle(mask);

    // 拖动标题栏
    let drag = null;
    head.addEventListener("pointerdown", function (e) {
      if (mask.classList.contains("maxed") || win.classList.contains("win-min")) return;
      if (e.target.closest("button")) return;
      const rect = win.classList.contains("free")
        ? { x: parseFloat(win.style.left) || 0, y: parseFloat(win.style.top) || 0,
            w: win.getBoundingClientRect().width, h: win.getBoundingClientRect().height }
        : snapshot(mask);
      if (!rect) return;
      drag = { dx: e.clientX - rect.x, dy: e.clientY - rect.y, w: rect.w, h: rect.h, id: e.pointerId };
      applyFree(mask, rect);
      try { head.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });
    head.addEventListener("pointermove", function (e) {
      if (!drag) return;
      e.preventDefault();
      const raw = { x: e.clientX - drag.dx, y: e.clientY - drag.dy, w: drag.w, h: drag.h };
      const r = clampRect(raw);
      if (raw.y <= (drag.snap ? TOP_SNAP_HYST : TOP_SNAP_Y)) {
        if (!drag.snap) drag.prev = { w: r.w, h: r.h };
        drag.snap = true;
        const snapped = topSnapRect(r);
        drag.w = snapped.w;
        drag.h = snapped.h;
        applyFree(mask, snapped);
        markTopSnap(win, true);
      } else {
        if (drag.snap && drag.prev) { drag.w = drag.prev.w; drag.h = drag.prev.h; }
        drag.snap = false;
        markTopSnap(win, false);
        applyFree(mask, clampRect({ x: e.clientX - drag.dx, y: raw.y, w: drag.w, h: drag.h }));
      }
    });
    const endDrag = function () {
      if (!drag) return;
      try { head.releasePointerCapture(drag.id); } catch (err) {}
      drag = null;
    };
    head.addEventListener("pointerup", endDrag);
    head.addEventListener("pointercancel", endDrag);

    // 四边/四角 resize
    let resize = null;
    win.querySelectorAll(".mol-rh").forEach(function (handle) {
      handle.addEventListener("pointerdown", function (e) {
        if (mask.classList.contains("maxed") || win.classList.contains("win-min")) return;
        e.stopPropagation();
        markTopSnap(win, false);
        const r = win.getBoundingClientRect();
        resize = {
          startX: e.clientX, startY: e.clientY,
          x: r.left, y: r.top, w: r.width, h: r.height,
          corner: handle.dataset.corner, id: e.pointerId
        };
        applyFree(mask, { x: r.left, y: r.top, w: r.width, h: r.height });
        try { handle.setPointerCapture(e.pointerId); } catch (err) {}
        e.preventDefault();
      });
      handle.addEventListener("pointermove", function (e) {
        if (!resize) return;
        e.preventDefault();
        const dx = e.clientX - resize.startX;
        const dy = e.clientY - resize.startY;
        let x = resize.x, y = resize.y, w = resize.w, h = resize.h;
        const c = resize.corner;
        if (c === "br" || c === "tr" || c === "r") w = resize.w + dx;
        else if (c === "bl" || c === "tl" || c === "l") { w = Math.max(MIN_W, resize.w - dx); x = resize.x + (resize.w - w); }
        if (c === "br" || c === "bl" || c === "b") h = resize.h + dy;
        else if (c === "tr" || c === "tl" || c === "t") { h = Math.max(MIN_H, resize.h - dy); y = resize.y + (resize.h - h); }
        applyFree(mask, clampRect({ x: x, y: y, w: w, h: h }));
      });
      const endResize = function () {
        if (!resize) return;
        try { handle.releasePointerCapture(resize.id); } catch (err) {}
        resize = null;
        if (mask.dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
      };
      handle.addEventListener("pointerup", endResize);
      handle.addEventListener("pointercancel", endResize);
    });

    // 最小化态点击顶栏标题文字还原（跳过按钮）
    head.addEventListener("click", function (e) {
      const win0 = winOf(mask);
      if (!win0 || !win0.classList.contains("win-min")) return;
      if (e.target.closest("button")) return;
      if (e.target.closest("h2")) { e.stopPropagation(); restoreBtn.click(); }
    });

    // 最小化：主体隐藏、只留顶栏，停靠页面下方
    const minBtn = mask.querySelector(".min-btn");
    if (minBtn) {
      minBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const win = winOf(mask);
        if (!win || win.classList.contains("win-min")) return;
        // 记录当前几何，供还原恢复；最大化态先退回之前的尺寸。
        let r;
        if (mask.classList.contains("maxed")) {
          resetModalMax(mask);
          const saved = mask.dataset.minRect;
          if (saved) {
            try { const o = JSON.parse(saved); applyFree(mask, o); } catch (err) {}
          }
        }
        r = win.getBoundingClientRect();
        mask.dataset.minRect = JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height });
        // 停靠栏只显示文件名：保存完整标题，再精简为纯文件名
        const h2 = head.querySelector("h2");
        if (h2) {
          if (mask.dataset.fullTitle === undefined) mask.dataset.fullTitle = h2.textContent;
          const name = dockFileName(mask, h2);
          const tag = String(mask.dataset.dockTag || "");
          h2.dataset.dockName = tag ? name + " · " + tag : name;
          h2.textContent = name;
        }
        win.classList.add("win-min");
        minDockAdd(win);
        bringFloatToFront(mask);
        layoutMinDock();
        if (mask.dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
      });
    }

    // 还原：最小化时回到最小化前位置/尺寸；否则归位弹窗
    const restoreBtn = mask.querySelector(".restore-btn");
    if (restoreBtn) {
      restoreBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const win = winOf(mask);
        if (win && win.classList.contains("win-min")) {
          win.classList.remove("win-min");
          minDockRemove(win);
          const saved = mask.dataset.minRect;
          if (saved) {
            try { const o = JSON.parse(saved); applyFree(mask, o); } catch (err) {}
          }
          delete mask.dataset.minRect;
          const h2 = head.querySelector("h2");
          if (h2 && mask.dataset.fullTitle !== undefined) {
            h2.textContent = mask.dataset.fullTitle;
            delete mask.dataset.fullTitle;
          }
          if (h2) delete h2.dataset.dockName;
          bringFloatToFront(mask);
          layoutMinDock();
        } else {
          resetModalMax(mask);
          resetFree(mask);
        }
        if (mask.dataset.baseId === "molView" && MC.viewer) {
          requestAnimationFrame(function () { try { MC.viewer.resize(); MC.viewer.render(); } catch (e) {} });
        }
      });
    }
}

// 弹窗每次隐藏时清除 free 状态，回到初始居中
const modalObserver = new MutationObserver(function (muts) {
  muts.forEach(function (m) {
    const mask = m.target;
    if (!(mask instanceof HTMLElement)) return;
    if (mask.classList.contains("hidden") && typeof mask._resetFree === "function") mask._resetFree();
  });
});
function observeModal(mask) {
  modalObserver.observe(mask, { attributes: true, attributeFilter: ["class"] });
}
["molView", "quickView"].forEach(function (id) {
  const mask = document.getElementById(id);
  if (mask) { initModalFloating(mask); observeModal(mask); }
});

/* 空白点击不关闭弹窗（按需求移除），仅 ESC 或关闭按钮退出 */
$("btnQuickClose").onclick = closeQuickWithConfirm;
$("btnNewText").onclick = openNewText;
$("btnNewDir").onclick = openNewDir;
$("btnDownloadSel").onclick = downloadSelected;
initBrowserFloat();
initBrowserDrop();
syncDownloadButton();
document.addEventListener("click", closeMenu);
document.addEventListener("click", function (ev) {
  if (MC.longPressClickGuard) { MC.longPressClickGuard = false; return; }
  const periodic = $("molPeriodicPanel");
  if (periodic && !periodic.classList.contains("hidden")) {
    if (ev.target && periodic.contains(ev.target)) return;
    molHidePeriodicPanel();
    const add = $("molAddPanel");
    if (add && !add.classList.contains("hidden") && ev.target && add.contains(ev.target)) return;
  }
  const panel = $("molPickPanel");
  if (!panel || panel.classList.contains("hidden")) {
    molClosePickPops();
    const add = $("molAddPanel");
    if (add && !add.classList.contains("hidden") && ev.target && !add.contains(ev.target)) molHideAddPanel();
    return;
  }
  if (panel.contains(ev.target)) {
    if (!ev.target.closest(".mol-pick-pop") && !ev.target.closest(".mol-pick-num-btn")) molClosePickPops();
    return;
  }
  molClosePickPops();
  const win = panel.closest(".mol-win");
  if (win && win.contains(ev.target)) molHidePickPanel();
});
document.addEventListener("keydown", function (event) {
  if (event.key !== "Escape") return;
  if (!$("molSaveBox").classList.contains("hidden")) { closeMolSave(); return; }
  if (!$("fileMenu").classList.contains("hidden")) { closeMenu(); return; }
  const periodic = $("molPeriodicPanel");
  if (periodic && !periodic.classList.contains("hidden")) { molHidePeriodicPanel(); return; }
  const addPanel = $("molAddPanel");
  if (addPanel && !addPanel.classList.contains("hidden")) { molHideAddPanel(); return; }
  const pickPanel = $("molPickPanel");
  if (pickPanel && !pickPanel.classList.contains("hidden")) { molHidePickPanel(); return; }
  if (MC.atomPanel && MC.atomPanel.panel) { molHideAtomPanel(); return; }
  const openMask = activeMask && !activeMask.classList.contains("hidden")
    ? activeMask : document.querySelector(".mol-mask:not(.hidden)");
  if (openMask && openMask.dataset.baseId === "quickView") { closeQuickWithConfirm(); return; }
  if (openMask && openMask.dataset.baseId === "molView") closeStructureWithConfirm();
});
window.addEventListener("resize", function () {
  molClampGizmo();
  molLayoutColorSwatches();
  if (!MC.viewer) return;
  MC.viewer.resize();
  MC.viewer.render();
});
// 页面尺寸变化后，重新约束所有文件浮窗，使顶栏边沿中心点仍在页面内。
window.addEventListener("resize", function () {
  Array.prototype.forEach.call(document.querySelectorAll(".mol-mask"), function (m) {
    if (m._reclamp) m._reclamp();
  });
});

(function () {
  const letters = Array.prototype.slice.call(document.querySelectorAll(".wordmark span"));
  function rand(min, max) { return Math.random() * (max - min) + min; }
  function pop(el) {
    const rot = (Math.random() < 0.5 ? -1 : 1) * rand(12, 30);
    const scale = rand(0.72, 1.45);
    const skew = rand(-12, 12);
    const dx = rand(-4, 4);
    const dy = rand(-4, 4);
    el.style.transition = "transform .3s cubic-bezier(.34, 1.56, .64, 1)";
    el.style.transform = "translate(" + dx.toFixed(1) + "px, " + dy.toFixed(1) + "px) rotate(" + rot.toFixed(1) + "deg) scale(" + scale.toFixed(2) + ") skew(" + skew.toFixed(1) + "deg)";
    clearTimeout(el._timer);
    el._timer = setTimeout(function () {
      el.style.transition = "transform .5s cubic-bezier(.34, 1.56, .64, 1)";
      el.style.transform = "";
    }, 420);
  }
  letters.forEach(function (el) {
    el.addEventListener("mouseenter", function () { pop(el); });
    el.addEventListener("click", function () { pop(el); });
  });
})();

(async function init() {
  try {
    const info = await api("/api/info");
    applyInfo(info);
    await load("");
    startTerminal();
    state.watchTimer = setInterval(watchDir, 2000);
  } catch (err) {
    toast(err.message, true);
  }
})();

/* ---------- MIT License：打字机浮层 ---------- */
(function initLicense() {
  const LICENSE_LINES = [
    "MIT License",
    "",
    "Copyright (c) 2026 Kan",
    "",
    "Permission is hereby granted, free of charge, to any person obtaining a copy",
    "of this software and associated documentation files (the \"Software\"), to deal",
    "in the Software without restriction, including without limitation the rights",
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell",
    "copies of the Software, and to permit persons to whom the Software is",
    "furnished to do so, subject to the following conditions:",
    "",
    "The above copyright notice and this permission notice shall be included in all",
    "copies or substantial portions of the Software.",
    "",
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR",
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,",
    "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE",
    "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER",
    "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,",
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE",
    "SOFTWARE."
  ];
  const LICENSE_TEXT = LICENSE_LINES.join("\n");
  const overlay = $("licenseOverlay");
  const out = $("licenseText");
  if (!overlay || !out) return;
  let timer = null;

  function hide() {
    if (timer) { clearInterval(timer); timer = null; }
    overlay.classList.add("hidden");
  }
  function show(ev) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    if (timer) { clearInterval(timer); timer = null; }
    // 先把全部行放进 DOM 并隐藏，首行从一开始就在全文显示时的最终位置。
    out.textContent = "";
    const frag = document.createDocumentFragment();
    LICENSE_LINES.forEach(function (line) {
      const span = document.createElement("span");
      span.className = "license-line";
      span.textContent = line;
      frag.appendChild(span);
    });
    out.appendChild(frag);
    const rows = out.querySelectorAll(".license-line");
    out.scrollTop = 0;
    overlay.classList.remove("hidden");
    let i = 0;
    function reveal() {
      if (i >= rows.length) { clearInterval(timer); timer = null; return; }
      const row = rows[i];
      row.classList.add("shown");
      // 仅当屏幕放不下时，才向上移动到刚显示的行。
      const bottom = row.offsetTop + row.offsetHeight;
      if (bottom > out.scrollTop + out.clientHeight) out.scrollTop = bottom - out.clientHeight;
      else if (row.offsetTop < out.scrollTop) out.scrollTop = row.offsetTop;
      i += 1;
    }
    reveal();
    if (i < rows.length) timer = setInterval(reveal, 80);
  }
  ["sideMit", "footMit"].forEach(function (id) {
    const el = $(id);
    if (!el) return;
    el.addEventListener("click", show);
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") show(e);
    });
  });
  overlay.addEventListener("click", hide);
  document.addEventListener("click", function (ev) {
    if (overlay.classList.contains("hidden")) return;
    if (ev.target.closest && ev.target.closest(".license-link")) return;
    hide();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !overlay.classList.contains("hidden")) hide();
  });
})();

