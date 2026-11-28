function hasWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return !!(window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
  } catch (err) {
    return false;
  }
}

function molLabel() {
  $("molCount").textContent = (MC.index + 1) + " / " + MC.frames;
  $("molRange").value = String(MC.index);
}

function showMolFrame(index) {
  if (!MC.viewer || MC.frames < 1) return;
  MC.index = ((index % MC.frames) + MC.frames) % MC.frames;
  MC.viewer.setFrame(MC.index);
  // 换帧后 3Dmol 使用新一帧的原子对象，单键覆盖/全局虚线需重新写入。
  if ((MC.bondStyles && Object.keys(MC.bondStyles).length) || molBondDashed || molBondHidden || molBondColor) {
    MC.bondBaseOrders = {};
    molApplyBondStyles();
  }
  // 播放中跳过逐帧重建命中几何（会卡顿）；暂停后由 stopMolPlay 补注册。
  // 单步/拖动切帧时 MC.timer 已清空，这里立即给当前帧注册拾取。
  if (!MC.timer) {
    molEnableFrameClickables();
    molRebuildBondPickShapes();
    molRedrawSupercell();
  }
  MC.viewer.render();
  // 轨迹播放：保留选中的原子，并按当前帧重新取坐标后重画测量，
  // 这样距离/角度会随帧实时变化；没有选中时无需重画。
  if ((MC.pickAtoms || []).length || (MC.pickBonds || []).length) molRefreshPicksForFrame();
  if (MC.selectMode && (MC.selectedAtoms || []).length) { molRedrawSelection(); molFillAtomPanel(); }
  else if (Object.keys(MC.atomDeleted || {}).length || Object.keys(MC.atomEdits || {}).length) {
    molApplyAtomEdits();
    molApplyHiddenAtoms();
    if (Object.keys(MC.atomEdits || {}).length) MC.viewer.addStyle({}, {});
    if (MC.viewer.render) MC.viewer.render();
  }
  molLabel();
  molMarkViewDirty();
}

// 多帧轨迹切帧后重新给“当前帧”的原子注册点击回调。
// 3Dmol 的 setFrame 会把 model.atoms 换成对应帧的原子对象，而 setClickable
// 只给调用时的 this.atoms 打 clickable / intersectionShape 标记；不重新注册
// 的话新帧原子射线命中不到，就只能在第一帧选中原子测距/测角。
function molEnableFrameClickables() {
  if (!MC.viewer || !MC.viewer.setClickable || MC.frames < 1) return;
  try { MC.viewer.setClickable({}, true, molOnAtomClick); }
  catch (err) { /* 注册失败不影响切帧，仅该帧无法拾取 */ }
}

// 轨迹切帧后刷新测量：用保存的 model/index 从当前帧重新取原子对象
// （3Dmol 的 setFrame 会把该帧坐标写入 model.atoms，selectedAtoms 返回的就是更新后的引用），
// 再据此重算元素名、连线与距离/角度。取不到时退化为原对象，保持选中不丢。
function molRefreshPicksForFrame() {
  if (!MC.viewer || (!(MC.pickAtoms || []).length && !(MC.pickBonds || []).length)) return;
  MC.pickAtoms = MC.pickAtoms.map(function (atom) {
    let cur = atom;
    try {
      if (MC.viewer.selectedAtoms && Number.isInteger(atom.index)) {
        const sel = { index: atom.index };
        if (atom.model !== undefined) sel.model = atom.model;
        const hits = MC.viewer.selectedAtoms(sel);
        if (hits && hits.length) cur = hits[0];
      }
    } catch (err) { /* 取帧失败时沿用原原子 */ }
    return cur;
  });
  molDrawMeasure();
}

function setMolPlayIcon(playing) {
  const svg = document.getElementById("molPlayIcon");
  if (!svg) return;
  if (playing) {
    svg.innerHTML = '<rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/>';
    $("molPlay").title = tx("暂停");
  } else {
    svg.innerHTML = '<path d="M7 5l12 7-12 7z"/>';
    $("molPlay").title = tx("播放");
  }
}

function stopMolPlay() {
  if (MC.timer) { clearInterval(MC.timer); MC.timer = null; }
  setMolPlayIcon(false);
  // 暂停在任意帧后，当前帧原子与键需要重新注册才能被右键拾取。
  molEnableFrameClickables();
  molRebuildBondPickShapes();
  molRedrawSupercell();
}

function startMolPlay() {
  if (!MC.viewer || MC.frames < 2) return;
  stopMolPlay();
  setMolPlayIcon(true);
  const speed = Number(getMolSpeed()) || 1;
  const interval = Math.max(40, Math.round(MOL_BASE_MS / speed));
  MC.timer = setInterval(function () {
    if (!MC.viewer) { stopMolPlay(); return; }
    showMolFrame(MC.index + 1);
  }, interval);
}

// 晶胞：3Dmol 的 GL 线在 WebGL 下固定 1px（linewidth 不生效），
// 所以晶胞棱改用圆柱绘制，线型由 cell.style 控制（无/实线/虚线），visible=false 时不画线。
// 虚线由 3Dmol 拆成一串短圆柱；细线时给每段加平端盖并设最小有效半径，避免短圆柱变成
// 无盖细管、被抗锯齿与着色冲淡而“发虚”。
// repeat=[na,nb,nc] 为沿 A/B/C 的扩胞数；所有格线都画出，保留晶胞之间的分隔线。
// 以下样式只保存在页面状态中，可在空白处右键的“样式设置”弹窗中调整，即时生效。
let molCellStyle = { radius: 0.015, dashed: true, visible: true, repeat: [1, 1, 1],
                     dashLength: 0.35, gapLength: 0.15, color: "#0000FF", labels: true,
                     wrapMode: "as-is" };  // as-is 按文件坐标；inside 把原子折回晶胞内部
const MOL_CELL_REPEAT_MAX = 12;
const MOL_CELL_DASH_MIN_RADIUS = 0.02;  // 虚线细于该半径时按该值渲染，保证每段有足够像素
let molAxisVisible = true;  // 左上角坐标轴指示器是否显示（样式设置 → 外观 → 显示坐标轴）
let molDepthCue = 0;  // 0 = 关闭深度雾，1 = 最强
// 轴箭头默认值：半径 0.06、不透明、红/绿/蓝三色（箭头位置不再单独设置，固定在轴末端）。
// length 为轴长倍率：默认 0.3；改小缩短、改大延长，即时生效。
// 轴标签与测量标注共用同一套字体选择；选项名一律用英文字体名，中文界面也不翻译。
// 3Dmol 把 font 拼到字号之后（"<px>px  <font>"），CSS font 简写不接受字号之后的
// italic/bold，故带字形样式的选项统一用 @font-face 别名传递，而不是 "italic " 前缀。
// 旧存档中的 "italic …" 仍迁移到 serif italic 别名。
const MOL_FONT_FAMILIES = [
  { key: "Sans",    label: "sans-serif", value: "sans-serif" },
  { key: "Serif",   label: "serif",      value: "Georgia, 'Times New Roman', serif" },
  { key: "Mono",    label: "Monospace",  value: "ui-monospace, Consolas, 'Courier New', monospace" },
  { key: "Rounded", label: "Rounded",    value: "'Trebuchet MS', 'Segoe UI', sans-serif" }
];
const MOL_ITALIC_SERIF_FAMILY = '"MctaSerifItalic", Georgia, "Times New Roman", serif';
const MOL_LABEL_FONTS = [
  MOL_FONT_FAMILIES[1], // serif
  { key: "SerifItalic",     label: "serif italic",             value: MOL_ITALIC_SERIF_FAMILY },
  MOL_FONT_FAMILIES[0], // sans-serif
  { key: "UISans",          label: "ui-sans-serif",            value: "ui-sans-serif, system-ui, sans-serif" },
  MOL_FONT_FAMILIES[2], // Monospace
  MOL_FONT_FAMILIES[3], // Rounded
  { key: "Times",           label: "Times New Roman",          value: '"Times New Roman", serif' },
  { key: "TimesItalic",     label: "Times New Roman Italic",   value: '"MctaTimesItalic", "Times New Roman", serif' },
  { key: "TimesBold",       label: "Times New Roman Bold",     value: '"MctaTimesBold", "Times New Roman", serif' },
  { key: "TimesBoldItalic",  label: "Times New Roman Bold Italic", value: '"MctaTimesBoldItalic", "Times New Roman", serif' }
];
function molFontValue(key) {
  const hit = MOL_LABEL_FONTS.filter(function (f) { return f.key === key; })[0];
  return hit ? hit.value : MOL_FONT_FAMILIES[0].value;
}
// 坐标轴标签默认 Times New Roman 斜体；测量标注默认 Times New Roman。
const MOL_AXIS_FONT_DEFAULT = molFontValue("TimesItalic");
const MOL_MEASURE_FONT_DEFAULT = molFontValue("Times");
// 晶胞原点 o 与三个晶格方向 a/b/c 的标注。3Dmol addLabel 只接受 font-family，
// 故用 Times New Roman Italic 的 @font-face 别名传递斜体；颜色 o 黑 / a 红 / b 绿 / c 蓝。
const MOL_CELL_LABEL_FONT = molFontValue("TimesItalic");
const MOL_CELL_LABEL_SIZE = 18;
const MOL_CELL_LABEL_SPECS = [
  { text: "o", color: "#000000" },
  { text: "a", color: "#FF0000" },
  { text: "b", color: "#00FF00" },
  { text: "c", color: "#0000FF" }
];
function molFontLabel(v) {
  const hit = MOL_LABEL_FONTS.filter(function (f) { return f.value === v; })[0];
  return hit ? tx(hit.label) : (v || MOL_FONT_FAMILIES[0].value);
}
function molCanvasFont(weight, size, family) {
  const f = family || MOL_FONT_FAMILIES[0].value;
  const italic = /^\s*italic\s+/i.test(f);
  return weight + (italic ? " italic" : "") + " " + size + "px " + f.replace(/^\s*italic\s+/i, "");
}
// 旧存档中的 "italic …" 只在 canvas 路径有效；统一迁移到共享的斜体字体族
function molNormalizeFontFamily(v) {
  return typeof v === "string" && /^\s*italic\s+/i.test(v) ? MOL_ITALIC_SERIF_FAMILY : v;
}
let molAxisStyle = {
  radius: 0.06, headRatio: 1.618, opacity: 1, length: 0.3,
  fontFamily: MOL_AXIS_FONT_DEFAULT,
  colors: ["#FF0000", "#00FF00", "#0000FF"]
};
// 测量标注样式：点击原子显示的元素名/距离/角度标签，以及相邻选中原子之间的连线。
// 默认 Times New Roman、字号 24、连线粗细 0.015、连线颜色 #ADFF2F；可在空白处右键“样式设置 → 测量”分组中即时调整。
let molMeasureStyle = {
  fontSize: 24, fontColor: "#87CEFA", fontFamily: MOL_MEASURE_FONT_DEFAULT,
  lineRadius: 0.015, lineColor: "#ADFF2F",
  lineDashed: true, lineDashLength: 0.08, lineGapLength: 0.06
};
// gizmo 可见圆：半径 = 轴长滑杆上限对应的绘制半径 + x/y/z 标签占用长度。
// 画布半径取该值，保证任意旋转角度下最长轴的端点与标签都落在圆内，不被边缘裁切/遮挡。
const MOL_AXIS_LEN_MAX = 0.4;                                   // = MOL_STYLE_FIELDS AxisLength.max
const MOL_AXIS_R_SCALE = 160;                                   // 轴长 → 绘制半径映射
const MOL_AXIS_R_MAX = MOL_AXIS_LEN_MAX * MOL_AXIS_R_SCALE;      // 64：最长轴绘制半径
const MOL_AXIS_LABEL_OFFSET = 16;                               // 标签圆心外移轴端点的距离
const MOL_AXIS_LABEL_LEN = MOL_AXIS_LABEL_OFFSET + 8;            // 24：标签外移 + 半字高
const MOL_GIZMO_VISIBLE_R = MOL_AXIS_R_MAX + MOL_AXIS_LABEL_LEN; // 88：可见圆半径
// CSS 边长 = 可见圆直径 + 4px 抗锯齿余量；后备像素至少 2×（高清屏按 DPR 提升）保证清晰。
const MOL_GIZMO_SIZE = Math.ceil(MOL_GIZMO_VISIBLE_R * 2) + 4;   // 180
// 键样式选项：全局“键”与单键右键面板共用；无 = 不显示该键。
const MOL_BOND_STYLE_MODES = [
  { key: "none", label: "无" }, { key: "solid", label: "实线" }, { key: "dashed", label: "虚线" }
];
// 等值面默认配色：正值浅黄、负值淡红；右键/长按等值面可即时修改。
const MOL_ISO_POS_COLOR_DEFAULT = "#fff59d";
const MOL_ISO_NEG_COLOR_DEFAULT = "#ffb3b3";
const MOL_ISO_OPACITY_DEFAULT = 0.6;
let molIsoPosColor = MOL_ISO_POS_COLOR_DEFAULT;
let molIsoNegColor = MOL_ISO_NEG_COLOR_DEFAULT;
// 等值面阈值/透明度统一由“等值面设置”弹窗控制；正负值均为正数幅度，绘制时再取负号。
let molIsoOpacity = MOL_ISO_OPACITY_DEFAULT;
let molIsoPosValue = 0.02;
let molIsoNegValue = 0.02;

// “样式设置”弹窗字段：分组、标签、取值范围与实时生效函数。
// 这些条目可在页面 UI 直接调整，改动即时生效，无需重启服务。
const MOL_STYLE_GROUPS = [
  { key: "bond", label: "外观", fields: [
    { key: "DepthCue", label: "深度雾", min: 0, max: 1, step: 0.01,
      get: function () { return molDepthCue; },
      set: function (v) { molDepthCue = v; molApplyDepthCue(); } },
    { key: "CellAxesVisible", label: "显示坐标轴", type: "bool",
      get: function () { return molAxisVisible; },
      set: function (v) { molAxisVisible = v; molRedrawAxes(); } },
    { key: "CellWrapMode", id: "molStCellWrapMode", label: "显示样式", type: "select",
      options: [{ key: "as-is", label: "原样" }, { key: "inside", label: "内部" }],
      get: function () { return molCellStyle.wrapMode; },
      set: function (v) {
        molCellStyle.wrapMode = v === "inside" ? "inside" : "as-is";
        molApplySupercellModel();
        molRedrawCell();
      } },
    { key: "AtomsVisible", label: "显示原子", type: "bool",
      get: function () { return molAtomsVisible; },
      set: function (v) { molAtomsVisible = v; molApplyVisibility(); } },
    { key: "AtomRadius", id: "molStAtomRadius", label: "原子大小", min: 0.05, max: 0.8, step: 0.01,
      get: function () { return molAtomRadius || MOL_DEFAULT_ATOM_RADIUS; },
      set: function (v) {
        molAtomRadius = Math.abs(v - MOL_DEFAULT_ATOM_RADIUS) < 1e-9 ? 0 : v;
        MC.atomStyles = {};
        molApplyGlobalAtomStyle();
      } },
    { key: "AtomColor", id: "molStAtomColor", label: "原子颜色", type: "color",
      get: function () { return molAtomColor || MOL_DEFAULT_ATOM_COLOR; },
      set: function (v) {
        molAtomColor = String(v).toLowerCase() === MOL_DEFAULT_ATOM_COLOR ? "" : v;
        MC.atomStyles = {};
        molApplyGlobalAtomStyle();
      } }
  ] },
  { key: "bonds", label: "键", fields: [
    { key: "BondsVisible", label: "显示键", type: "bool",
      get: function () { return molBondsVisible; },
      set: function (v) { molBondsVisible = v; molApplyVisibility(); } },
    { key: "BondStyle", id: "molPickBondStyle", label: "键样式", type: "select",
      options: MOL_BOND_STYLE_MODES,
      get: function () { return molBondHidden ? "none" : (molBondDashed ? "dashed" : "solid"); },
      set: function (v) {
        molClearBondOverrides();
        molBondHidden = v === "none";
        molBondDashed = v === "dashed";
        molApplyBondRadius();
      } },
    { key: "BondRadius", id: "molPickBondRadius", label: "键粗", min: 0.02, max: 0.30, step: 0.01,
      get: function () { return molBondRadius; },
      set: function (v) { molClearBondOverrides(); molBondRadius = v; molApplyBondRadius(); } },
    { key: "BondColorMode", id: "molPickBondColorMode", label: "键颜色模式", type: "select",
      options: [{ key: "element", label: "按元素" }, { key: "custom", label: "自定义" }],
      get: function () { return molBondColor ? "custom" : "element"; },
      set: function (v) {
        molClearBondOverrides();
        molBondColor = v === "custom" ? (molBondColor || "#9aa4b2") : "";
        molApplyBondRadius();
        molSyncStyleFields();
      } },
    { key: "BondColor", id: "molPickBondColor", label: "键颜色", type: "color",
      get: function () { return molBondColor || "#9aa4b2"; },
      // “按元素”模式下颜色框只作占位展示；恢复默认时不得把占位色写成全局色。
      set: function (v) {
        if (!molBondColor) return;
        molClearBondOverrides();
        molBondColor = v;
        molApplyBondRadius();
        molSyncStyleFields();
      } }
  ] },
  { key: "cell", label: "晶格", fields: [
    { key: "CellLabels", label: "晶格标记", type: "bool",
      get: function () { return molCellStyle.labels; },
      set: function (v) { molCellStyle.labels = v; molRedrawCell(); } },
    { key: "CellDashed", id: "molStCellDashed", label: "晶格样式", type: "select",
      options: [{ key: "none", label: "无" }, { key: "solid", label: "实线" }, { key: "dashed", label: "虚线" }],
      get: function () {
        return !molCellStyle.visible ? "none" : (molCellStyle.dashed ? "dashed" : "solid");
      },
      set: function (v) {
        molCellStyle.visible = v !== "none";
        molCellStyle.dashed = v === "dashed";
        molRedrawCell();
        molSyncDashRow();
      } },
    { key: "CellDashLength", label: "虚线段长", inline: "dash", min: 0.01, max: 5, step: 0.01,
      get: function () { return molCellStyle.dashLength; },
      set: function (v) { molCellStyle.dashLength = v; molRedrawCell(); } },
    { key: "CellGapLength", label: "间隙", inline: "dash", min: 0.01, max: 5, step: 0.01,
      get: function () { return molCellStyle.gapLength; },
      set: function (v) { molCellStyle.gapLength = v; molRedrawCell(); } },
    { key: "CellRadius", label: "晶格线宽", min: 0.005, max: 0.05, step: 0.001,
      get: function () { return molCellStyle.radius; },
      set: function (v) { molCellStyle.radius = v; molRedrawCell(); } },
    { key: "CellColor", label: "晶格颜色", type: "color",
      get: function () { return molCellStyle.color; },
      set: function (v) { molCellStyle.color = v; molRedrawCell(); } },
    { key: "CellRepeatA", label: "范围A", inline: "repeat", min: 1, max: MOL_CELL_REPEAT_MAX, step: 1,
      get: function () { return molCellStyle.repeat[0]; },
      set: function (v) { molCellStyle.repeat[0] = Math.max(1, Math.round(v)); molApplySupercellModel(); molRedrawCell(); molSyncStyleFields(); } },
    { key: "CellRepeatB", label: "范围B", inline: "repeat", min: 1, max: MOL_CELL_REPEAT_MAX, step: 1,
      get: function () { return molCellStyle.repeat[1]; },
      set: function (v) { molCellStyle.repeat[1] = Math.max(1, Math.round(v)); molApplySupercellModel(); molRedrawCell(); molSyncStyleFields(); } },
    { key: "CellRepeatC", label: "范围C", inline: "repeat", min: 1, max: MOL_CELL_REPEAT_MAX, step: 1,
      get: function () { return molCellStyle.repeat[2]; },
      set: function (v) { molCellStyle.repeat[2] = Math.max(1, Math.round(v)); molApplySupercellModel(); molRedrawCell(); molSyncStyleFields(); } }
  ] },
  { key: "axis", label: "坐标轴", fields: [
    { key: "AxisLength", label: "轴长度", min: 0.06, max: 0.4, step: 0.01,
      get: function () { return molAxisStyle.length; },
      set: function (v) { molAxisStyle.length = v; molRedrawAxes(); } },
    { key: "AxisRadius", label: "轴半径", min: 0.05, max: 0.17, step: 0.005,
      get: function () { return molAxisStyle.radius; },
      set: function (v) { molAxisStyle.radius = v; molRedrawAxes(); } },
    { key: "AxisHeadRatio", label: "箭头比例", min: 1.62, max: 3.8, step: 0.01,
      get: function () { return molAxisStyle.headRatio; },
      set: function (v) { molAxisStyle.headRatio = v; molRedrawAxes(); } },
    { key: "AxisOpacity", label: "轴透明度", min: 0, max: 1, step: 0.01,
      get: function () { return molAxisStyle.opacity; },
      set: function (v) { molAxisStyle.opacity = v; molRedrawAxes(); } },
    { key: "AxisFont", label: "轴标签字体", type: "font", options: MOL_LABEL_FONTS,
      get: function () { return molAxisStyle.fontFamily; },
      set: function (v) { molAxisStyle.fontFamily = v; molRedrawAxes(); } }
  ] },
  { key: "axisColor", label: "轴颜色", fields: [
    { key: "AxisColorA", label: "X轴颜色", type: "color",
      get: function () { return molAxisStyle.colors[0]; },
      set: function (v) { molAxisStyle.colors[0] = v; molRedrawAxes(); } },
    { key: "AxisColorB", label: "Y轴颜色", type: "color",
      get: function () { return molAxisStyle.colors[1]; },
      set: function (v) { molAxisStyle.colors[1] = v; molRedrawAxes(); } },
    { key: "AxisColorC", label: "Z轴颜色", type: "color",
      get: function () { return molAxisStyle.colors[2]; },
      set: function (v) { molAxisStyle.colors[2] = v; molRedrawAxes(); } }
  ] },
  { key: "iso", label: "等值面", fields: [
    { key: "IsoOpacity", id: "molStIsoOpacity", label: "透明度", min: 0.05, max: 1, step: 0.05,
      get: function () { return molIsoOpacity; },
      set: function (v) { molIsoOpacity = v; scheduleMolDensityUpdate(); } },
    { key: "IsoPos", id: "molStIsoPos", label: "正值", min: 0.001, max: 1, step: 0.001,
      get: function () { return molIsoPosValue; },
      set: function (v) { molIsoPosValue = v; scheduleMolDensityUpdate(); } },
    { key: "IsoPosColor", id: "molStIsoPosColor", label: "正值颜色", type: "color",
      get: function () { return molIsoPosColor; },
      set: function (v) { molIsoPosColor = v; scheduleMolDensityUpdate(); } },
    { key: "IsoNeg", id: "molStIsoNeg", label: "负值", min: 0.001, max: 1, step: 0.001,
      get: function () { return molIsoNegValue; },
      set: function (v) { molIsoNegValue = v; scheduleMolDensityUpdate(); } },
    { key: "IsoNegColor", id: "molStIsoNegColor", label: "负值颜色", type: "color",
      get: function () { return molIsoNegColor; },
      set: function (v) { molIsoNegColor = v; scheduleMolDensityUpdate(); } }
  ] },
  { key: "measure", label: "测量", fields: [
    { key: "MeasureFontSize", label: "标注字号", min: 8, max: 40, step: 1,
      get: function () { return molMeasureStyle.fontSize; },
      set: function (v) { molMeasureStyle.fontSize = v; molRedrawMeasure(); } },
    { key: "MeasureFontColor", label: "标注颜色", type: "color",
      get: function () { return molMeasureStyle.fontColor; },
      set: function (v) { molMeasureStyle.fontColor = v; molRedrawMeasure(); } },
    { key: "MeasureFontFamily", label: "标注字体", type: "font",
      options: MOL_LABEL_FONTS,
      get: function () { return molMeasureStyle.fontFamily; },
      set: function (v) { molMeasureStyle.fontFamily = v; molRedrawMeasure(); } },
    { key: "MeasureLineDashed", label: "虚线连线", type: "bool",
      get: function () { return molMeasureStyle.lineDashed; },
      set: function (v) { molMeasureStyle.lineDashed = v; molRedrawMeasure(); } },
    { key: "MeasureLineRadius", label: "连线粗细", min: 0.002, max: 0.05, step: 0.001,
      get: function () { return molMeasureStyle.lineRadius; },
      set: function (v) { molMeasureStyle.lineRadius = v; molRedrawMeasure(); } },
    { key: "MeasureLineColor", label: "连线颜色", type: "color",
      get: function () { return molMeasureStyle.lineColor; },
      set: function (v) { molMeasureStyle.lineColor = v; molRedrawMeasure(); } }
  ] }
];
const MOL_STYLE_FIELDS = MOL_STYLE_GROUPS.reduce(function (all, g) {
  return all.concat(g.fields);
}, []);
MOL_STYLE_FIELDS.forEach(function (f) {
  f.id = f.id || ("molSt" + f.key);
  f.def = f.get();
});

function molHexColor(v) {
  if (typeof v === "number") return "#" + ("000000" + v.toString(16)).slice(-6);
  return String(v || "#000000").slice(0, 7);
}

// 默认原子样式方案（来源见下）：
// · 颜色：参考 Materials Studio 的元素配色（MS 内置 CPK 色表，H 白 / C 灰 / N 蓝 / O 红 / S 黄 / Fe 橙），
//   为浅色背景把 H 等极亮色略微压暗，避免白底上完全看不见；
// · 半径：VESTA 的 atomic radii（金属/共价半径，单位 Å），球棍图按 VESTA 规则取 40%，
//   夹在 0.10–0.60 Å；VESTA 手册：球棍图的球半径 = 实际原子半径 × 40%。
const MOL_ATOM_COLORS = {
  H:"#dfe4ea", He:"#b3e3f5", Li:"#a066d9", Be:"#7acb00", B:"#e3a0a0", C:"#828282",
  N:"#3050f8", O:"#ff0d0d", F:"#7fbf50", Ne:"#80d1e3", Na:"#9154dd", Mg:"#5fbf00",
  Al:"#9f8a8a", Si:"#d0a878", P:"#f08a1a", S:"#e6d400", Cl:"#2fbf5f", Ar:"#6ab7cf",
  K:"#7f45c0", Ca:"#35b000", Ti:"#9aa2ab", V:"#8d93a0", Cr:"#7482b4", Mn:"#9a6fbe",
  Fe:"#e06633", Co:"#c96a86", Ni:"#45a045", Cu:"#b87939", Zn:"#6b78a8", Ga:"#b08080",
  Ge:"#6f8f8f", As:"#a873cf", Se:"#d98a00", Br:"#a33b3b", Kr:"#64abc4", Rb:"#7f3fba",
  Sr:"#25c000", Y:"#80d8d8", Zr:"#80c8c8", Nb:"#6bb0bb", Mo:"#54aaaa", Tc:"#459a9a",
  Ru:"#2d9090", Rh:"#227f8c", Pd:"#157089", Ag:"#a8b0b8", Cd:"#d0b585", In:"#a87b79",
  Sn:"#7f9090", Sb:"#9f6bb8", Te:"#c07b00", I:"#8a008a", Xe:"#5aa0b8", Cs:"#6b3aa8",
  Ba:"#20bd00", La:"#70c8ee", Ce:"#d8d8a8", Pr:"#b5d8a8", Nd:"#9fd8a8", Sm:"#8fd8a8",
  Eu:"#7fd8a8", Gd:"#6fd8a8", Tb:"#5fd8a8", Dy:"#52d8a8", Ho:"#44d0a0", Er:"#38c890",
  Tm:"#30bd78", Yb:"#28b060", Lu:"#22a858", Hf:"#5ab4e0", Ta:"#5aa0e0", W:"#3a90c8",
  Re:"#3f80a8", Os:"#3c7096", Ir:"#2f6488", Pt:"#9fa6bb", Au:"#d0a62c", Hg:"#a6aec4",
  Tl:"#a86b5e", Pb:"#707681", Bi:"#9f66b8", Po:"#a06200", At:"#8a6058", Rn:"#5a98aa",
  Th:"#2ab0e0", U:"#1f9fe0", Np:"#1f8fd8", Pu:"#1f7fc8"
};
const MOL_ATOM_RADII = {
  H:0.37, He:0.32, Li:1.52, Be:1.12, B:0.85, C:0.77, N:0.75, O:0.73, F:0.71, Ne:0.71,
  Na:1.86, Mg:1.60, Al:1.43, Si:1.18, P:1.10, S:1.04, Cl:0.99, Ar:0.98, K:2.27, Ca:1.97,
  Sc:1.62, Ti:1.47, V:1.36, Cr:1.28, Mn:1.27, Fe:1.24, Co:1.26, Ni:1.24, Cu:1.28, Zn:1.34,
  Ga:1.41, Ge:1.37, As:1.21, Se:1.16, Br:1.14, Kr:1.03, Rb:2.48, Sr:2.15, Y:1.78, Zr:1.60,
  Nb:1.46, Mo:1.39, Tc:1.36, Ru:1.34, Rh:1.34, Pd:1.37, Ag:1.44, Cd:1.51, In:1.67, Sn:1.50,
  Sb:1.41, Te:1.37, I:1.33, Xe:1.08, Cs:2.65, Ba:2.17, La:1.87, Ce:1.82, Pr:1.82, Nd:1.81,
  Sm:1.80, Eu:1.99, Gd:1.79, Tb:1.76, Dy:1.75, Ho:1.74, Er:1.73, Tm:1.72, Yb:1.94, Lu:1.72,
  Hf:1.56, Ta:1.46, W:1.39, Re:1.37, Os:1.35, Ir:1.36, Pt:1.39, Au:1.44, Hg:1.51, Tl:1.70,
  Pb:1.75, Bi:1.70, Po:1.40, At:1.50, Rn:1.50, Th:1.80, U:1.75, Np:1.75, Pu:1.75
};
// 新增原子用的元素信息：[符号, 英文名, 中文名]。
const MOL_ELEMENTS = [
  ["H","Hydrogen","氢"], ["He","Helium","氦"], ["Li","Lithium","锂"], ["Be","Beryllium","铍"],
  ["B","Boron","硼"], ["C","Carbon","碳"], ["N","Nitrogen","氮"], ["O","Oxygen","氧"],
  ["F","Fluorine","氟"], ["Ne","Neon","氖"], ["Na","Sodium","钠"], ["Mg","Magnesium","镁"],
  ["Al","Aluminum","铝"], ["Si","Silicon","硅"], ["P","Phosphorus","磷"], ["S","Sulfur","硫"],
  ["Cl","Chlorine","氯"], ["Ar","Argon","氩"], ["K","Potassium","钾"], ["Ca","Calcium","钙"],
  ["Sc","Scandium","钪"], ["Ti","Titanium","钛"], ["V","Vanadium","钒"], ["Cr","Chromium","铬"],
  ["Mn","Manganese","锰"], ["Fe","Iron","铁"], ["Co","Cobalt","钴"], ["Ni","Nickel","镍"],
  ["Cu","Copper","铜"], ["Zn","Zinc","锌"], ["Ga","Gallium","镓"], ["Ge","Germanium","锗"],
  ["As","Arsenic","砷"], ["Se","Selenium","硒"], ["Br","Bromine","溴"], ["Kr","Krypton","氪"],
  ["Rb","Rubidium","铷"], ["Sr","Strontium","锶"], ["Y","Yttrium","钇"], ["Zr","Zirconium","锆"],
  ["Nb","Niobium","铌"], ["Mo","Molybdenum","钼"], ["Tc","Technetium","锝"], ["Ru","Ruthenium","钌"],
  ["Rh","Rhodium","铑"], ["Pd","Palladium","钯"], ["Ag","Silver","银"], ["Cd","Cadmium","镉"],
  ["In","Indium","铟"], ["Sn","Tin","锡"], ["Sb","Antimony","锑"], ["Te","Tellurium","碲"],
  ["I","Iodine","碘"], ["Xe","Xenon","氙"], ["Cs","Cesium","铯"], ["Ba","Barium","钡"],
  ["La","Lanthanum","镧"], ["Ce","Cerium","铈"], ["Pr","Praseodymium","镨"], ["Nd","Neodymium","钕"],
  ["Pm","Promethium","钷"], ["Sm","Samarium","钐"], ["Eu","Europium","铕"], ["Gd","Gadolinium","钆"],
  ["Tb","Terbium","铽"], ["Dy","Dysprosium","镝"], ["Ho","Holmium","钬"], ["Er","Erbium","铒"],
  ["Tm","Thulium","铥"], ["Yb","Ytterbium","镱"], ["Lu","Lutetium","镥"], ["Hf","Hafnium","铪"],
  ["Ta","Tantalum","钽"], ["W","Tungsten","钨"], ["Re","Rhenium","铼"], ["Os","Osmium","锇"],
  ["Ir","Iridium","铱"], ["Pt","Platinum","铂"], ["Au","Gold","金"], ["Hg","Mercury","汞"],
  ["Tl","Thallium","铊"], ["Pb","Lead","铅"], ["Bi","Bismuth","铋"], ["Po","Polonium","钋"],
  ["At","Astatine","砹"], ["Rn","Radon","氡"], ["Ac","Actinium","锕"], ["Th","Thorium","钍"],
  ["Pa","Protactinium","镤"], ["U","Uranium","铀"], ["Np","Neptunium","镎"], ["Pu","Plutonium","钚"]
];
// 周期表位置：键为 0–17 的列号，后两行分别是镧系/锕系。
const MOL_PERIODIC_ROWS = [
  {0:"H",17:"He"},
  {0:"Li",1:"Be",12:"B",13:"C",14:"N",15:"O",16:"F",17:"Ne"},
  {0:"Na",1:"Mg",12:"Al",13:"Si",14:"P",15:"S",16:"Cl",17:"Ar"},
  {0:"K",1:"Ca",2:"Sc",3:"Ti",4:"V",5:"Cr",6:"Mn",7:"Fe",8:"Co",9:"Ni",10:"Cu",11:"Zn",12:"Ga",13:"Ge",14:"As",15:"Se",16:"Br",17:"Kr"},
  {0:"Rb",1:"Sr",2:"Y",3:"Zr",4:"Nb",5:"Mo",6:"Tc",7:"Ru",8:"Rh",9:"Pd",10:"Ag",11:"Cd",12:"In",13:"Sn",14:"Sb",15:"Te",16:"I",17:"Xe"},
  {0:"Cs",1:"Ba",2:"La",3:"Hf",4:"Ta",5:"W",6:"Re",7:"Os",8:"Ir",9:"Pt",10:"Au",11:"Hg",12:"Tl",13:"Pb",14:"Bi",15:"Po",16:"At",17:"Rn"},
  {2:"La",3:"Ce",4:"Pr",5:"Nd",6:"Pm",7:"Sm",8:"Eu",9:"Gd",10:"Tb",11:"Dy",12:"Ho",13:"Er",14:"Tm",15:"Yb",16:"Lu"},
  {2:"Ac",3:"Th",4:"Pa",5:"U",6:"Np",7:"Pu"}
];
function molElementInfo(sym) {
  const s = String(sym || "");
  return MOL_ELEMENTS.find(function (e) { return e[0].toLowerCase() === s.toLowerCase(); }) || null;
}
function molResolveElement(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;
  const low = raw.toLowerCase();
  const hit = MOL_ELEMENTS.find(function (e) {
    return e[0].toLowerCase() === low || e[1].toLowerCase() === low || e[2] === raw;
  });
  return hit ? hit[0] : null;
}
// VESTA elements.ini 中的 atomic radius（金属/共价半径，Å）；球棍图按 40% 显示球半径。
function molElemKey(elem) {
  const s = String(elem || "").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "";
}
function molDefaultColor(elem) {
  return MOL_ATOM_COLORS[molElemKey(elem)] || "#9aa4b2";
}
function molDefaultRadius(elem) {
  const r = MOL_ATOM_RADII[molElemKey(elem)];
  return Math.min(0.6, Math.max(0.1, (typeof r === "number" ? r : 0.9) * 0.4));
}

function molApplyDefaultAtomStyle() {
  if (!MC.viewer) return;
  // 3Dmol 的 setStyle 会先清空整组原子样式，后续 addStyle 才是在此基础上叠加。
  MC.viewer.setStyle({}, { stick: { radius: MOL_BOND_RADIUS },
    sphere: { color: "#9aa4b2", radius: molDefaultRadius("") } });
  Object.keys(MOL_ATOM_RADII).forEach(function (elem) {
    MC.viewer.addStyle({ elem: elem }, {
      sphere: { color: molDefaultColor(elem), radius: molDefaultRadius(elem) }
    });
  });
  molRedrawSupercell();
}

// 全局原子大小/颜色：先统一覆盖到所有原子（用显式默认值而非 undefined，避免
// 未知元素在 3Dmol 内留下空样式），再把保持“按元素”的项逐元素写回。
function molApplyGlobalAtomStyle() {
  if (!MC.viewer) return;
  MC.viewer.addStyle({}, { sphere: {
    color: molAtomColor || MOL_DEFAULT_ATOM_COLOR,
    radius: molAtomRadius || MOL_DEFAULT_ATOM_RADIUS
  } });
  if (!molAtomColor || !molAtomRadius) {
    Object.keys(MOL_ATOM_RADII).forEach(function (elem) {
      const sp = {};
      if (!molAtomColor) sp.color = molDefaultColor(elem);
      if (!molAtomRadius) sp.radius = molDefaultRadius(elem);
      MC.viewer.addStyle({ elem: elem }, { sphere: sp });
    });
  }
  molApplyVisibility();
}

// 深度雾（Depth cue）强度 0–1：0 关闭；>0 时 fogStart 从 0.4 线性降到 0，
// fogEnd 从 1 降到 0.5，数值越大远处原子被雾遮得越明显。
function molApplyDepthCue() {
  if (!MC.viewer) return;
  const s = Math.min(1, Math.max(0, Number(molDepthCue) || 0));
  if (s <= 0) {
    MC.viewer.enableFog(false);
    return;
  }
  MC.viewer.enableFog({ fogStart: 0.4 * (1 - s), fogEnd: 1 - 0.5 * s });
  MC.viewer.render();
}

function molAxisSpec(color) {
  return {
    color: color, radius: molAxisStyle.radius, radiusRatio: molAxisStyle.headRatio,
    opacity: molAxisStyle.opacity
  };
}

function molCellRepeat() {
  const r = molCellStyle.repeat || [1, 1, 1];
  return [0, 1, 2].map(function (i) {
    const n = Math.round(Number(r[i]) || 1);
    return Math.max(1, Math.min(MOL_CELL_REPEAT_MAX, n));
  });
}
// 超晶胞第 (a,b,c) 个格点：A/B/C 三个方向分别按 repeat 数扩展。
function molCellCorner(cell, a, b, c) {
  const o = MC.cellOrigin || { x: 0, y: 0, z: 0 };
  return {
    x: o.x + cell[0][0] * a + cell[1][0] * b + cell[2][0] * c,
    y: o.y + cell[0][1] * a + cell[1][1] * b + cell[2][1] * c,
    z: o.z + cell[0][2] * a + cell[1][2] * b + cell[2][2] * c
  };
}
// 每个方向逐段画格线：既画超晶胞外框，也画隔开每个单胞的内部线。
function molCellEdges(n) {
  const edges = [];
  for (let b = 0; b <= n[1]; b++) for (let c = 0; c <= n[2]; c++)
    for (let a = 0; a < n[0]; a++) edges.push([[a, b, c], [a + 1, b, c]]);
  for (let a = 0; a <= n[0]; a++) for (let c = 0; c <= n[2]; c++)
    for (let b = 0; b < n[1]; b++) edges.push([[a, b, c], [a, b + 1, c]]);
  for (let a = 0; a <= n[0]; a++) for (let b = 0; b <= n[1]; b++)
    for (let c = 0; c < n[2]; c++) edges.push([[a, b, c], [a, b, c + 1]]);
  return edges;
}

function drawMolCell(cell) {
  const shapes = [];
  if (cell && cell.length >= 3 && molCellStyle.visible !== false) {
    molCellEdges(molCellRepeat()).forEach(function (edge) {
      try {
        const dashed = !!molCellStyle.dashed;
        const spec = {
          start: molCellCorner(cell, edge[0][0], edge[0][1], edge[0][2]),
          end: molCellCorner(cell, edge[1][0], edge[1][1], edge[1][2]),
          radius: dashed ? Math.max(molCellStyle.radius, MOL_CELL_DASH_MIN_RADIUS)
                         : molCellStyle.radius,
          color: molCellStyle.color,
          dashed: dashed,
          dashLength: molCellStyle.dashLength,
          gapLength: molCellStyle.gapLength
        };
        if (dashed) { spec.fromCap = 2; spec.toCap = 2; }  // 每段虚线封口，端头不发虚
        const shape = MC.viewer.addCylinder(spec);
        if (shape) shapes.push(shape);
      } catch (err) { /* 忽略画线失败 */ }
    });
  }
  // 原点 O 与三条晶胞向量末端的 A/B/C 标注（label 用 viewer.removeLabel 清理，
  // 与圆柱 shape 分开存到 MC.cellLabels）。扩胞后仍标在原始单胞上。
  MC.cellLabels = [];
  if (molCellStyle.labels && cell && cell.length >= 3) {
    const ends = [
      { x: 0, y: 0, z: 0 },
      { x: cell[0][0] || 0, y: cell[0][1] || 0, z: cell[0][2] || 0 },
      { x: cell[1][0] || 0, y: cell[1][1] || 0, z: cell[1][2] || 0 },
      { x: cell[2][0] || 0, y: cell[2][1] || 0, z: cell[2][2] || 0 }
    ];
    MOL_CELL_LABEL_SPECS.forEach(function (spec, i) {
      try {
        const label = MC.viewer.addLabel(spec.text, {
          position: ends[i], inFront: true, showBackground: false,
          font: MOL_CELL_LABEL_FONT, fontSize: MOL_CELL_LABEL_SIZE,
          fontColor: spec.color, borderThickness: 0
        });
        if (label) MC.cellLabels.push(label);
      } catch (err) { /* 忽略标签失败 */ }
    });
  }
  return shapes;
}

// 超晶胞：直接把原胞扩成 3Dmol 原生模型（原子和键都由 3Dmol 渲染），
// 不再为每个平移单胞逐个 addSphere/addCylinder —— 后者在大超晶胞下会产生上万个
// 独立 shape，非常卡顿。原胞原子 index 保持不变，逐原子/逐键样式与存档仍有效。
function molClearSupercellCopies() {
  if (MC.viewer && MC.viewer.removeShape) {
    (MC.cellCopies || []).forEach(function (s) {
      try { MC.viewer.removeShape(s); } catch (err) { /* 忽略 */ }
    });
  }
  MC.cellCopies = [];
}
function molShiftPos(pos, off) {
  return { x: pos.x + off.x, y: pos.y + off.y, z: pos.z + off.z };
}

// 把原子按晶胞周期折回原胞内部（分数坐标取 [0,1)），用于“显示样式 → 内部”。
// 折回后原有键不再可靠，统一清空交给 molEnsureBondGrid 按距离重建。
function molWrapFramesToCell(frames, cell) {
  const m = [[cell[0][0], cell[1][0], cell[2][0]],
             [cell[0][1], cell[1][1], cell[2][1]],
             [cell[0][2], cell[1][2], cell[2][2]]];
  const inv = molInv3(m);
  if (!inv) return frames;
  const o = MC.cellOrigin || { x: 0, y: 0, z: 0 };
  return (frames || []).map(function (base) {
    return (base || []).map(function (atom) {
      const copy = Object.assign({}, atom);
      const f = [0, 0, 0];
      const dx = atom.x - o.x, dy = atom.y - o.y, dz = atom.z - o.z;
      for (let k = 0; k < 3; k++) f[k] = inv[k][0]*dx + inv[k][1]*dy + inv[k][2]*dz;
      for (let k = 0; k < 3; k++) f[k] -= Math.floor(f[k]);
      copy.x = o.x + m[0][0]*f[0] + m[0][1]*f[1] + m[0][2]*f[2];
      copy.y = o.y + m[1][0]*f[0] + m[1][1]*f[1] + m[1][2]*f[2];
      copy.z = o.z + m[2][0]*f[0] + m[2][1]*f[1] + m[2][2]*f[2];
      copy.bonds = [];
      copy.bondOrder = [];
      return copy;
    });
  });
}

// 按共价半径 + 0.45 Å 容差补齐缺失的键：扩胞后连接超晶胞边界两侧，
// “内部”模式折回后重建被原坐标拆散的键。网格分桶避免 O(N²) 全扫描。
function molEnsureBondGrid(atoms) {
  if (!atoms || !atoms.length) return;
  const CUT = 6.5;  // 覆盖半径表最大组合 + 容差
  const buckets = Object.create(null);
  const key = function (x, y, z) {
    return Math.floor(x/CUT) + "," + Math.floor(y/CUT) + "," + Math.floor(z/CUT);
  };
  atoms.forEach(function (a, i) {
    const k = key(a.x, a.y, a.z);
    (buckets[k] || (buckets[k] = [])).push(i);
  });
  const radius = function (a) { return MOL_ATOM_RADII[molElemKey(a.elem)] || 0.9; };
  atoms.forEach(function (a, i) {
    const ix = Math.floor(a.x/CUT), iy = Math.floor(a.y/CUT), iz = Math.floor(a.z/CUT);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      const list = buckets[(ix+dx)+","+(iy+dy)+","+(iz+dz)];
      if (!list) continue;
      list.forEach(function (j) {
        if (j <= i) return;
        if ((a.bonds || []).indexOf(j) >= 0) return;
        const b = atoms[j];
        const ddx = b.x-a.x, ddy = b.y-a.y, ddz = b.z-a.z;
        const d2 = ddx*ddx + ddy*ddy + ddz*ddz;
        if (d2 < 0.01) return;
        const t = radius(a) + radius(b) + 0.45;
        if (d2 >= t*t) return;
        a.bonds.push(j); a.bondOrder.push(1);
        b.bonds.push(i); b.bondOrder.push(1);
      });
    }
  });
}

// 由原胞帧生成扩胞帧：每个晶格平移点复制一套原子，键索引同步偏移到新数组。
function molExpandFrames(frames, cell, n) {
  const offsets = [];
  for (let i = 0; i < n[0]; i++) for (let j = 0; j < n[1]; j++) for (let k = 0; k < n[2]; k++) {
    offsets.push({
      x: cell[0][0]*i + cell[1][0]*j + cell[2][0]*k,
      y: cell[0][1]*i + cell[1][1]*j + cell[2][1]*k,
      z: cell[0][2]*i + cell[1][2]*j + cell[2][2]*k
    });
  }
  return (frames || []).map(function (base) {
    const out = [];
    offsets.forEach(function (off) {
      (base || []).forEach(function (atom, ai) {
        const copy = {};
        Object.keys(atom).forEach(function (key) {
          if (key === "style" || key === "bondStyles" || key === "intersectionShape" ||
              key === "bonds" || key === "bondOrder" || key === "clickable" ||
              key === "hoverable" || key === "callback") return;
          copy[key] = atom[key];
        });
        const shift = out.length - ai;
        copy.x = (Number(atom.x) || 0) + off.x;
        copy.y = (Number(atom.y) || 0) + off.y;
        copy.z = (Number(atom.z) || 0) + off.z;
        copy.index = out.length;
        copy.serial = out.length;
        copy.bonds = (atom.bonds || []).map(function (j) { return j + shift; });
        copy.bondOrder = (atom.bondOrder || []).slice();
        out.push(copy);
      });
    });
    return out;
  });
}

// 把扩胞后的原子写回模型。只在超晶胞数改变或结构重新打开时调用。
function molApplySupercellModel() {
  if (!MC.viewer || !MC.sourceFrames || !MC.cell || MC.cell.length < 3) return;
  const models = molViewerModels();
  if (!models.length) return;
  const n = molCellRepeat();
  const base = molCellStyle.wrapMode === "inside"
    ? molWrapFramesToCell(MC.sourceFrames, MC.cell) : MC.sourceFrames;
  const expanded = molExpandFrames(base, MC.cell, n);
  expanded.forEach(function (atoms) { molEnsureBondGrid(atoms); });
  const model = models[0];
  MC.bondBaseOrders = {};
  if (model.frames && model.frames.length) {
    model.frames = expanded;
    const idx = Math.max(0, Math.min(expanded.length - 1, MC.index || 0));
    model.atoms = expanded[idx] || expanded[0] || [];
    if (MC.viewer.setFrame) MC.viewer.setFrame(idx);
  } else {
    model.atoms = expanded[0] || [];
  }
  model.molObj = null;
  MC.pickedCellRepeat = n.slice();

  // 样式走 3Dmol 原生管线；自定义覆盖按 index 重新写入（原胞 index 不变）。
  molApplyDefaultAtomStyle();
  // 扩胞会重建 model.atoms 并重置样式，全局原子大小/颜色必须在其后重新叠加。
  molApplyGlobalAtomStyle();
  Object.keys(MC.atomStyles || {}).forEach(function (key) {
    const s = MC.atomStyles[key];
    if (s) MC.viewer.addStyle(molSelectorAllFrames(s), { sphere: { color: s.color, radius: s.radius } });
  });
  molApplyBondRadius();
  molApplyVisibility();
  molApplyAtomEdits();
  if (Object.keys(MC.atomEdits || {}).length) MC.viewer.addStyle({}, {});
  if (MC.viewer.setClickable) MC.viewer.setClickable({}, true, molOnAtomClick);
  molRebuildBondPickShapes();
  if ((MC.pickAtoms || []).length || (MC.pickBonds || []).length) molRefreshPicksForFrame();
  molDrawMeasure();
  MC.viewer.render();
}

// 兼容原有调用点：扩胞走原生模型后无需重画副本，只重渲染一次即可。
function molRedrawSupercell() {
  if (MC.viewer) MC.viewer.render();
}

// 左上角坐标轴指示器：只取主 viewer 的旋转四元数（getView 索引 4–7），
// 不取平移/缩放，因此轴只跟随结构旋转，长度恒为固定像素值，不会穿过原子。
function molQuatRotateVec(q, v) {
  const x = q[0] || 0, y = q[1] || 0, z = q[2] || 0, w = (typeof q[3] === "number" ? q[3] : 1);
  const tx = 2 * (y*v[2] - z*v[1]);
  const ty = 2 * (z*v[0] - x*v[2]);
  const tz = 2 * (x*v[1] - y*v[0]);
  return {
    x: v[0] + w*tx + (y*tz - z*ty),
    y: v[1] + w*ty + (z*tx - x*tz),
    z: v[2] + w*tz + (x*ty - y*tx)
  };
}

// 三条单位轴经四元数旋转后投影到屏幕（x 右、y 上），返回相对中心的偏移与深度。
// 正交：三条轴在 2D 上一律归一到等长 R（不带深度缩放，读起来是“平面正交”指示器，
//       不再因投影缩短而呈现近大远小的透视感）；
// 透视：按深度 k=D/(D-z) 缩放（朝向观察者的一侧更长），再整体归一到半径 R 内，
//       避免标签被裁掉。切换“视角：正交/透视”按钮时两者形状明显不同。
function molGizmoAxisEnds(q, R) {
  const perspective = !MC || MC.ortho === false;
  const D = 3;
  const out = [[1,0,0], [0,1,0], [0,0,1]].map(function (v) {
    const r = molQuatRotateVec(q, v);
    // 归一化旋转结果：即使 getView 四元数带数值误差而非严格单位化，也保证端点 3D 长度恒为 1。
    const n = Math.sqrt(r.x*r.x + r.y*r.y + r.z*r.z) || 1;
    const x = r.x/n, y = r.y/n, z = r.z/n;
    const k = perspective ? D / Math.max(1, D - z) : 1;
    return { x: x*k*R, y: -y*k*R, z: z };
  });
  if (perspective) {
    let maxLen = 0;
    out.forEach(function (e) { maxLen = Math.max(maxLen, Math.sqrt(e.x*e.x + e.y*e.y)); });
    if (maxLen > R) {
      const f = R / maxLen;
      out.forEach(function (e) { e.x *= f; e.y *= f; });
    }
  } else {
    // 正交：每条轴按各自的屏幕方向归一到等长 R，消除投影造成的长短差。
    out.forEach(function (e) {
      const len = Math.sqrt(e.x*e.x + e.y*e.y);
      if (len > 1e-6) { e.x = e.x / len * R; e.y = e.y / len * R; }
    });
  }
  return out;
}

function molGizmoQuat() {
  if (!MC.viewer || !MC.viewer.getView) return [0, 0, 0, 1];
  try {
    const v = MC.viewer.getView();
    if (v && v.length >= 8) return [v[4], v[5], v[6], v[7]];
  } catch (err) { /* 忽略 */ }
  return [0, 0, 0, 1];
}

// 短轴（如正对 z 轴时投影长度≈0 的 z）不拉伸成假轴：轴线保持真实投影长度，
// 标签改放到其余轴标签之间角度最大的空白扇区，避免叠在圆心或其他标签上。
// 返回相对圆心的标签坐标，并保留 short 标记便于测试。
function molGizmoLabelPoints(ends, R) {
  const MIN_LEN = 11;
  const k = 1 + MOL_AXIS_LABEL_OFFSET / Math.max(R, 1);
  const pts = ends.map(function (e) {
    return { x: e.x * k, y: e.y * k, short: Math.sqrt(e.x * e.x + e.y * e.y) < MIN_LEN };
  });
  const used = pts.filter(function (p) { return !p.short; })
    .map(function (p) { return Math.atan2(p.y, p.x); });
  pts.forEach(function (p) {
    if (!p.short) return;
    let best = -Math.PI, bestGap = -1;
    for (let t = 0; t < 24; t++) {
      const a = -Math.PI + t * Math.PI / 12;
      let gap = Math.PI;
      used.forEach(function (u) {
        const da = Math.abs(Math.atan2(Math.sin(a - u), Math.cos(a - u)));
        if (da < gap) gap = da;
      });
      if (gap > bestGap) { bestGap = gap; best = a; }
    }
    const lr = Math.max(10, R * 0.55);
    p.x = Math.cos(best) * lr;
    p.y = Math.sin(best) * lr;
    used.push(best);
  });
  return pts;
}

// 坐标轴指示器：CSS 尺寸与后备像素常量见上方 MOL_GIZMO_SIZE / molGizmoScale。
let molGizmoPos = null;  // 用户拖动后的位置（相对画布左上角）；null = 默认左上角贴边
function molGizmoScale() {
  const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
  return Math.max(2, Math.min(3, dpr));
}

function molEnsureGizmo() {
  const host = $("molCanvas");
  if (!host) return null;
  let cv = host.querySelector(".mol-axis-gizmo");
  if (cv) return cv;
  cv = document.createElement("canvas");
  cv.className = "mol-axis-gizmo";
  cv.id = "molAxisGizmo";
  const s = molGizmoScale();
  cv.width = Math.round(MOL_GIZMO_SIZE * s);
  cv.height = Math.round(MOL_GIZMO_SIZE * s);
  cv.dataset.scale = String(s);
  cv.style.width = MOL_GIZMO_SIZE + "px";
  cv.style.height = MOL_GIZMO_SIZE + "px";
  cv.setAttribute("role", "img");
  cv.title = tx("坐标轴设置");

  function place(x, y) {
    const maxX = Math.max(0, (host.clientWidth || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
    const maxY = Math.max(0, (host.clientHeight || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
    const nx = Math.max(0, Math.min(maxX, x));
    const ny = Math.max(0, Math.min(maxY, y));
    cv.style.left = nx + "px";
    cv.style.top = ny + "px";
    cv.style.bottom = "auto";
    host._gizmoPos = { left: nx, top: ny };
    molGizmoPos = host._gizmoPos;
  }
  const saved = host._gizmoPos || molGizmoPos;
  if (saved) place(saved.left, saved.top);
  else {
    // 默认停靠左上角并贴紧边框；CSS 初值一致，place() 会改写为具体 left/top 像素
    place(0, 0);
  }

  let drag = null;
  cv.addEventListener("pointerdown", function (ev) {
    if (ev.button !== 0) return;  // 右键仍打开“坐标轴设置”
    ev.preventDefault();
    ev.stopPropagation();
    drag = {
      x: ev.clientX, y: ev.clientY,
      left: parseFloat(cv.style.left) || 0, top: parseFloat(cv.style.top) || 0
    };
    cv.classList.add("dragging");
    if (cv.setPointerCapture) { try { cv.setPointerCapture(ev.pointerId); } catch (err) {} }
  });
  cv.addEventListener("pointermove", function (ev) {
    if (!drag) return;
    ev.preventDefault();
    place(drag.left + (ev.clientX - drag.x), drag.top + (ev.clientY - drag.y));
    // 拖动坐标轴指示器属于视图调整，即使晶胞未动也要允许存档
    molMarkViewDirty();
  });
  function endDrag() {
    if (!drag) return;
    drag = null;
    cv.classList.remove("dragging");
  }
  cv.addEventListener("pointerup", endDrag);
  cv.addEventListener("pointercancel", endDrag);
  cv.addEventListener("contextmenu", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    molOpenContextHere(ev);
  });
  host.appendChild(cv);
  return cv;
}

// 画布尺寸变化后把指示器重新约束回可见区域。
function molClampGizmo() {
  const host = $("molCanvas");
  const cv = host && host.querySelector(".mol-axis-gizmo");
  if (!cv) return;
  const maxX = Math.max(0, (host.clientWidth || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
  const maxY = Math.max(0, (host.clientHeight || (MOL_GIZMO_SIZE + 24)) - MOL_GIZMO_SIZE);
  const x = Math.max(0, Math.min(maxX, parseFloat(cv.style.left) || 0));
  const y = Math.max(0, Math.min(maxY, parseFloat(cv.style.top) || 0));
  cv.style.left = x + "px";
  cv.style.top = y + "px";
  host._gizmoPos = { left: x, top: y };
  molGizmoPos = host._gizmoPos;
}

function molHexRgba(hex, alpha) {
  const h = String(hex || "#000000").replace("#", "");
  const n = parseInt(h.length >= 6 ? h.slice(0, 6) : "000000", 16);
  return "rgba(" + ((n>>16)&255) + "," + ((n>>8)&255) + "," + (n&255) + "," + alpha + ")";
}

function molDrawAxisGizmo() {
  const cv = molEnsureGizmo();
  if (!cv || !cv.getContext) return;
  // 「样式设置 → 外观 → 显示坐标轴」关闭时隐藏指示器；开启后再恢复并继续重画。
  cv.style.display = molAxisVisible ? "" : "none";
  if (!molAxisVisible) return;
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const s = Number(cv.dataset.scale) || molGizmoScale();
  const W = MOL_GIZMO_SIZE, H = MOL_GIZMO_SIZE, cx = W/2, cy = H/2;
  const R = Math.max(10, Math.min(MOL_AXIS_R_MAX, molAxisStyle.length * MOL_AXIS_R_SCALE));
  // 不再给退化轴兜底拉伸：短轴按真实投影长度绘制，标签由 molGizmoLabelPoints
  // 移到旁边空白区域，避免把正对屏幕的轴画成假的长箭头。
  const ends = molGizmoAxisEnds(molGizmoQuat(), R);
  // 逻辑坐标按 CSS 像素绘制，由变换放大到高清后备像素。
  if (ctx.setTransform) ctx.setTransform(s, 0, 0, s, 0, 0);
  else if (ctx.scale) { ctx.save(); ctx.scale(s, s); }
  ctx.clearRect(0, 0, W, H);
  const labels = ["x", "y", "z"];
  const order = [0, 1, 2].sort(function (a, b) { return ends[a].z - ends[b].z; });
  const lw = Math.max(1.5, Math.min(5, molAxisStyle.radius * 30));
  const head = Math.max(6, Math.min(14, 6 * molAxisStyle.headRatio / 1.618));
  // 1) 先画三条轴线（按深度从远到近）；不垫白色描边，避免轴与箭头外圈出现白边。
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  order.forEach(function (i) {
    const e = ends[i];
    // 按深度从远到近淡出；透明度取自 0–1 滑杆，0 时完全不可见（不再设 alpha 下限）。
    const depthFade = 0.7 + 0.3 * Math.max(0, Math.min(1, (e.z + 1) / 2));
    const rgba = molHexRgba(molAxisStyle.colors[i],
      Math.min(1, Math.max(0, molAxisStyle.opacity * depthFade)));
    const ex = cx + e.x, ey = cy + e.y;
    const ang = Math.atan2(e.y, e.x);
    ctx.strokeStyle = rgba; ctx.fillStyle = rgba; ctx.lineWidth = lw;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - head*Math.cos(ang - 0.42), ey - head*Math.sin(ang - 0.42));
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - head*Math.cos(ang + 0.42), ey - head*Math.sin(ang + 0.42));
    ctx.stroke();
  });
  // 2) 三个标签最后统一绘制；短轴标签挪到空白扇区，其余仍贴轴端外侧。
  const labelPts = molGizmoLabelPoints(ends, R);
  ctx.font = molCanvasFont("700", 14, molAxisStyle.fontFamily);
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  order.forEach(function (i) {
    const p = labelPts[i];
    ctx.fillStyle = molHexRgba(molAxisStyle.colors[i], Math.min(1, Math.max(0, molAxisStyle.opacity)));
    ctx.fillText(labels[i], cx + p.x, cy + p.y);
  });
  if (!ctx.setTransform && ctx.restore) ctx.restore();
}

// 样式设置改动后即时重画晶胞棱；轴相关改动即时重画左上角指示器。
function molRedrawCell() {
  molClearSupercellCopies();
  if (!MC.viewer || !MC.cell) return;
  (MC.cellShapes || []).forEach(function (s) {
    try { MC.viewer.removeShape(s); } catch (err) { /* 忽略 */ }
  });
  (MC.cellLabels || []).forEach(function (s) {
    try { MC.viewer.removeLabel(s); } catch (err) { /* 忽略 */ }
  });
  MC.cellShapes = drawMolCell(MC.cell);
  molRedrawSupercell();
  MC.viewer.render();
}

function molRedrawAxes() { molDrawAxisGizmo(); }

// 正交 / 透视投影切换
function molSetProjection(ortho) {
  if (!MC.viewer) return;
  MC.ortho = !!ortho;
  MC.viewer.setProjection(MC.ortho ? "orthographic" : "perspective");
  const proj = $("molProj");
  if (proj) {
    const label = tx(MC.ortho ? "视角：正交" : "视角：透视");
    proj.title = label;
    proj.setAttribute("aria-label", label);
    const orthoIcon = $("molProjOrtho"), perspIcon = $("molProjPersp");
    if (orthoIcon) orthoIcon.classList.toggle("hidden", !MC.ortho);
    if (perspIcon) perspIcon.classList.toggle("hidden", MC.ortho);
  }
  MC.viewer.show();
  molDrawAxisGizmo();
  molMarkViewDirty();
}

// 沿选定坐标轴按选定角度旋转，方向按右手法则定义：右手拇指指向旋转轴正向，
// 四指弯曲方向为逆时针（从轴正向端朝原点看）。3Dmol 的正角四元数正是该方向，
// 故 sign = 1 为逆时针，sign = -1 为顺时针。
function molRotate(sign) {
  if (!MC.viewer) return;
  const axis = getMolAxis();
  const angle = getMolAngle();
  MC.viewer.rotate(sign * angle, axis, 0);
  MC.viewer.render();
  molRevealZoomCtl();
  molMarkViewDirty();
}
// 快捷键专用：绕屏幕坐标轴旋转视图。屏幕横向为 x、纵向为 y、朝向为 z；
// 上/下绕 x 轴，左/右绕 y 轴。轴向量取当前视图姿态下屏幕轴在世界坐标中的表示，
// 角度取工具栏设定值；只动相机，不改原子坐标与晶胞。
function molRotateViewScreen(axisName, sign) {
  if (!MC.viewer) return;
  const axes = molScreenAxes();
  const axis = axisName === "x" ? axes.right : axes.up;
  MC.viewer.rotate(sign * getMolAngle(), axis, 0);
  MC.viewer.render();
  molDrawAxisGizmo();
  molRevealZoomCtl();
  molMarkViewDirty();
}

// 原子拾取：左键选原子做距离/角度测量，右键打开单个原子的颜色/大小设置。
// 晶胞存在时用最小镜像换算键长与键角，避免跨边界原子得到虚假的长键。
function molInv3(m) {
  const a=m[0][0], b=m[0][1], c=m[0][2];
  const d=m[1][0], e=m[1][1], f=m[1][2];
  const g=m[2][0], h=m[2][1], i=m[2][2];
  const A=e*i-f*h, B=-(d*i-f*g), C=d*h-e*g;
  const det=a*A+b*B+c*C;
  if (Math.abs(det) < 1e-10) return null;
  return [[A/det, (c*h-b*i)/det, (b*f-c*e)/det],
          [B/det, (a*i-c*g)/det, -(a*f-c*d)/det],
          [C/det, -(a*h-b*g)/det, (a*e-b*d)/det]];
}

function molWrapVec(v) {
  const cell = MC.cell;
  if (!cell || cell.length < 3) return { x: v.x, y: v.y, z: v.z };
  const a = cell[0], b = cell[1], c = cell[2];
  const m = [[a[0], b[0], c[0]], [a[1], b[1], c[1]], [a[2], b[2], c[2]]];
  const inv = molInv3(m);
  if (!inv) return { x: v.x, y: v.y, z: v.z };
  const frac = [0, 0, 0];
  for (let k = 0; k < 3; k++) frac[k] = inv[k][0]*v.x + inv[k][1]*v.y + inv[k][2]*v.z;
  for (let k = 0; k < 3; k++) frac[k] -= Math.round(frac[k]);
  return {
    x: m[0][0]*frac[0] + m[0][1]*frac[1] + m[0][2]*frac[2],
    y: m[1][0]*frac[0] + m[1][1]*frac[1] + m[1][2]*frac[2],
    z: m[2][0]*frac[0] + m[2][1]*frac[1] + m[2][2]*frac[2]
  };
}

function molVecSub(a, b) { return { x: a.x-b.x, y: a.y-b.y, z: a.z-b.z }; }
function molVecAdd(a, b) { return { x: a.x+b.x, y: a.y+b.y, z: a.z+b.z }; }
function molVecMid(a, b) { return { x: (a.x+b.x)/2, y: (a.y+b.y)/2, z: (a.z+b.z)/2 }; }
function molVecLen(v) { return Math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z); }
function molAtomPos(a) { return { x: a.x, y: a.y, z: a.z }; }
function molAtomKey(a) { return String(a && a.model) + ":" + String(a && a.index); }

// ---- 选中原子：点选/框选、变色标记、坐标编辑、删除与整体移动 ----
// 原子结构编辑仅允许纯结构文件：密度显示或多帧轨迹时禁用删除/移动/旋转/新增。
function molAtomEditBlockReason(add) {
  if (MC.volume) return tx(add ? "密度显示中不可新增原子" : "密度显示中不可编辑原子");
  if (MC.frames > 1) return tx(add ? "轨迹显示中不可新增原子" : "轨迹显示中不可编辑原子");
  return "";
}
function molSyncAtomEditButtons() {
  const b = $("molAddAtom");
  if (!b) return;
  const reason = molAtomEditBlockReason(true);
  b.disabled = !!reason;
  b.title = tx(reason ? reason : "增加原子");
  b.setAttribute("aria-label", b.title);
  const viewReason = molAtomEditBlockReason(false);
  const h = MC.atomHistory || { undo: [], redo: [] };
  [["molUndoEdit", h.undo.length, "撤销"], ["molRedoEdit", h.redo.length, "恢复"]].forEach(function (spec) {
    const btn = $(spec[0]);
    if (!btn) return;
    btn.disabled = !!viewReason || !spec[1];
    btn.title = tx(viewReason ? viewReason : spec[2]);
    btn.setAttribute("aria-label", btn.title);
  });
}
function molAtomHistoryStack() {
  if (!MC.atomHistory || !Array.isArray(MC.atomHistory.undo) || !Array.isArray(MC.atomHistory.redo))
    MC.atomHistory = { undo: [], redo: [] };
  return MC.atomHistory;
}
function molPushAtomHistory(entry) {
  if (MC.historySuspend || !entry) return;
  const h = molAtomHistoryStack();
  h.undo.push(entry);
  h.redo.length = 0;
  molSyncAtomEditButtons();
}
// 坐标变换：记录选中原子变换前后的笛卡尔坐标，供撤销/恢复逐步还原。
function molAtomCoordSnapshots() {
  return (MC.selectedAtoms || []).map(function (sel) {
    const a = molCurrentAtom(sel);
    if (!a) return null;
    const k = molSelKey(sel.model, sel.index);
    return { model: sel.model, index: sel.index,
             before: MC.atomEdits[k] ? Object.assign({}, MC.atomEdits[k]) : null };
  }).filter(Boolean);
}
function molPushTransformHistory(snapshots) {
  if (!snapshots || !snapshots.length) return;
  const atoms = [];
  snapshots.forEach(function (s) {
    const k = molSelKey(s.model, s.index);
    const after = MC.atomEdits[k] ? Object.assign({}, MC.atomEdits[k]) : null;
    if (JSON.stringify(s.before) === JSON.stringify(after)) return;
    atoms.push({ model: s.model, index: s.index, before: s.before, after: after });
  });
  if (atoms.length) molPushAtomHistory({ type: "transform", atoms: atoms });
}
function molAtomDeleteSnapshot(sel) {
  if (!sel) return null;
  const k = molSelKey(sel.model, sel.index);
  const a = molCurrentAtom(sel);
  if (!a) return null;
  return {
    model: sel.model, index: sel.index,
    elem: String(a.elem || a.atom || ""),
    edit: MC.atomEdits[k] ? Object.assign({}, MC.atomEdits[k]) : null,
    change: MC.atomElementChanges[k] || null
  };
}
function molSetAtomElementRaw(sel, sym, change) {
  const a = molCurrentAtom(sel);
  if (!a) return false;
  const k = molSelKey(sel.model, sel.index);
  if (MC.atomDeleted[k]) return false;
  molClearSelectionShapes();
  a.elem = sym;
  if (a.element !== undefined) a.element = sym;
  if (MC.viewer) {
    try {
      MC.viewer.addStyle(molSelectorAllFrames(a), {
        sphere: { color: molDefaultColor(sym), radius: molDefaultRadius(sym) }
      });
      MC.viewer.addStyle({}, {});
    } catch (err) { /* 忽略 */ }
  }
  delete MC.atomStyles[k];
  delete MC.selectStyles[k];
  if (change === undefined || change === null) delete MC.atomElementChanges[k];
  else MC.atomElementChanges[k] = change;
  molRedrawSelection();
  molFillAtomPanel(true);
  if (MC.viewer) MC.viewer.render();
  molMarkViewDirty();
  return true;
}
function molApplyAtomHistoryEntry(entry, undo) {
  if (!entry || !Array.isArray(entry.atoms)) return false;
  if (entry.type === "add") {
    let ok = false;
    if (undo) {
      entry.atoms.slice().sort(function (a, b) { return b.index - a.index; }).forEach(function (item) {
        if (molRemoveAddedAtom(item.index)) ok = true;
      });
    } else {
      entry.atoms.forEach(function (item) {
        if (molAddAtomToModel(item.elem, [item.fx, item.fy, item.fz], true)) ok = true;
      });
    }
    return ok;
  }
  if (entry.type === "delete") {
    const keys = entry.atoms.map(function (item) { return molSelKey(item.model, item.index); });
    if (undo) {
      const restored = [];
      entry.atoms.forEach(function (item) {
        const k = molSelKey(item.model, item.index);
        delete MC.atomDeleted[k];
        if (item.edit) MC.atomEdits[k] = Object.assign({}, item.edit);
        if (item.change) MC.atomElementChanges[k] = item.change;
        restored.push({ model: item.model, index: item.index, elem: item.elem });
      });
      molApplyHiddenAtoms();
      if (restored.length) {
        molOpenAtomPanel(restored, null, false);
        MC.selectedAtoms = restored.slice();
        molRedrawSelection();
      }
      if (MC.viewer) MC.viewer.render();
      molMarkViewDirty();
      return true;
    }
    entry.atoms.forEach(function (item) {
      const k = molSelKey(item.model, item.index);
      MC.atomDeleted[k] = true;
      delete MC.atomEdits[k];
      delete MC.atomElementChanges[k];
      molCloseAtomPanel({ model: item.model, index: item.index });
    });
    MC.selectedAtoms = (MC.selectedAtoms || []).filter(function (sel) {
      return keys.indexOf(molSelKey(sel.model, sel.index)) < 0;
    });
    molClearSelectionShapes();
    molApplyHiddenAtoms();
    if (MC.viewer) MC.viewer.render();
    molMarkViewDirty();
    return true;
  }
  if (entry.type === "transform") {
    let ok = false;
    entry.atoms.forEach(function (item) {
      const k = molSelKey(item.model, item.index);
      const target = undo ? item.before : item.after;
      if (target && typeof target === "object") MC.atomEdits[k] = Object.assign({}, target);
      else delete MC.atomEdits[k];
      ok = true;
    });
    if (!ok) return false;
    molRedrawSelection();
    molFillAtomPanel(true);
    if (MC.viewer) MC.viewer.render();
    molMarkViewDirty();
    return true;
  }
  if (entry.type === "element") {
    let ok = false;
    entry.atoms.forEach(function (item) {
      const sel = { model: item.model, index: item.index };
      const sym = undo ? item.from : item.to;
      const change = undo ? item.prevChange : item.to;
      if (molSetAtomElementRaw(sel, sym, change)) ok = true;
    });
    return ok;
  }
  return false;
}
function molUndoAtomEdit() {
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const h = molAtomHistoryStack();
  if (!h.undo.length) return false;
  const entry = h.undo.pop();
  MC.historySuspend = true;
  let ok = false;
  try { ok = molApplyAtomHistoryEntry(entry, true); }
  finally { MC.historySuspend = false; }
  if (ok) h.redo.push(entry);
  molSyncAtomEditButtons();
  return ok;
}
function molRedoAtomEdit() {
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const h = molAtomHistoryStack();
  if (!h.redo.length) return false;
  const entry = h.redo.pop();
  MC.historySuspend = true;
  let ok = false;
  try { ok = molApplyAtomHistoryEntry(entry, false); }
  finally { MC.historySuspend = false; }
  if (ok) h.undo.push(entry);
  molSyncAtomEditButtons();
  return ok;
}
function molSelKey(model, index) { return String(model) + ":" + String(index); }
function molAtomVisible(a) { return !!a && !MC.atomDeleted[molSelKey(a.model, a.index)]; }
// 多帧模型下 selectedAtoms() 应返回当前帧，但旧版 3Dmol/自定义模型未必可靠；
// 统一保留从 model.atoms（setFrame 会切换它）直接取当前帧的兜底路径。
function molModelAtoms(model) {
  const models = molViewerModels();
  for (let i = 0; i < models.length; i++) {
    const m = models[i];
    const id = m.getID ? m.getID() : m.id;
    if (model !== undefined && id !== model && String(id) !== String(model)) continue;
    if (m.frames && m.frames.length && m.frames[MC.index || 0]) return m.frames[MC.index || 0];
    return m.atoms || [];
  }
  return [];
}
function molCurrentAtom(sel) {
  if (!MC.viewer || !sel) return null;
  try {
    if (MC.viewer.selectedAtoms) {
      const spec = { index: sel.index };
      if (sel.model !== undefined) spec.model = sel.model;
      const hits = MC.viewer.selectedAtoms(spec);
      if (hits && hits.length) return hits[0];
    }
  } catch (err) { /* 走模型兜底 */ }
  const atoms = molModelAtoms(sel.model);
  for (let i = 0; i < atoms.length; i++) if (atoms[i].index === sel.index) return atoms[i];
  return null;
}
function molAllCurrentAtoms() {
  if (MC.viewer && MC.viewer.selectedAtoms) {
    try {
      const hits = MC.viewer.selectedAtoms({}) || [];
      if (hits.length) return hits;
    } catch (err) { /* 走模型兜底 */ }
  }
  return molModelAtoms(undefined);
}
function molAtomDisplayPos(a) {
  const edit = MC.atomEdits[molSelKey(a.model, a.index)];
  return edit ? { x: edit.x, y: edit.y, z: edit.z } : { x: a.x, y: a.y, z: a.z };
}
function molCellInverse(m) {
  if (!m || m.length < 3) return null;
  const d = m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
          - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
          + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
  if (Math.abs(d) < 1e-12) return null;
  const a=m[0][0],b=m[0][1],c=m[0][2],e=m[1][0],f=m[1][1],g=m[1][2],h=m[2][0],i=m[2][1],j=m[2][2];
  return [[(f*j-g*i)/d,(c*i-b*j)/d,(b*g-c*f)/d],
          [(g*h-e*j)/d,(a*j-c*h)/d,(c*e-a*g)/d],
          [(e*i-f*h)/d,(b*h-a*i)/d,(a*f-b*e)/d]];
}
function molCellOffset() {
  const o = MC.cellOrigin;
  if (!o || !isFinite(o.x) || !isFinite(o.y) || !isFinite(o.z)) return { x: 0, y: 0, z: 0 };
  return o;
}
function molCartToFrac(p, cell) {
  const inv = molCellInverse(cell);
  if (!inv) return null;
  const o = molCellOffset();
  const dx = p.x - o.x, dy = p.y - o.y, dz = p.z - o.z;
  return [0,1,2].map(function (k) { return inv[0][k]*dx + inv[1][k]*dy + inv[2][k]*dz; });
}
function molFracToCart(f, cell) {
  const o = molCellOffset();
  return { x: o.x + f[0]*cell[0][0]+f[1]*cell[1][0]+f[2]*cell[2][0],
           y: o.y + f[0]*cell[0][1]+f[1]*cell[1][1]+f[2]*cell[2][1],
           z: o.z + f[0]*cell[0][2]+f[1]*cell[1][2]+f[2]*cell[2][2] };
}
function molSyncSelectButton() {
  const b = $("molSelectAtoms");
  if (!b) return;
  b.classList.toggle("active", !!MC.selectMode);
  b.setAttribute("aria-pressed", MC.selectMode ? "true" : "false");
  const label = MC.selectMode ? "取消选中原子"
    : "选中原子（Shift+框选 / Ctrl+点击；按钮模式弹坐标，未进入时只高亮；Shift+方向键旋转原子，Shift+Alt+方向键移动原子）";
  b.title = tx(label);
  b.setAttribute("aria-label", b.title);
}
function molAtomStyleSnapshot(a) {
  const sph = (a && a.style && a.style.sphere) || {};
  return {
    color: sph.color || molDefaultColor(a && a.elem),
    radius: typeof sph.radius === "number" ? sph.radius : molDefaultRadius(a && a.elem)
  };
}
function molRestoreSelectionStyles() {
  if (!MC.viewer || !MC.selectStyles) { MC.selectStyles = {}; return; }
  Object.keys(MC.selectStyles).forEach(function (k) {
    const parts = k.split(":");
    const a = molCurrentAtom({ model: Number(parts[0]), index: Number(parts[1]) });
    const orig = MC.selectStyles[k];
    if (a && orig) {
      try { MC.viewer.addStyle(molSelector(a), { sphere: { color: orig.color, radius: orig.radius } }); }
      catch (err) { /* 忽略 */ }
    }
  });
  MC.selectStyles = {};
}
function molClearSelectionShapes() {
  // 先恢复上一次选中原子的原生样式，再清掉标记形状。
  molRestoreSelectionStyles();
  if (!MC.viewer) { MC.selectShapes = []; return; }
  (MC.selectShapes || []).forEach(function (sh) {
    try { MC.viewer.removeShape(sh); } catch (err) { /* 忽略 */ }
  });
  MC.selectShapes = [];
}
function molHideAtom(a) {
  if (!MC.viewer || !a) return;
  try {
    MC.viewer.setStyle(molSelector(a),
      { sphere: { hidden: true }, stick: { hidden: true }, line: { hidden: true } });
  } catch (err) { /* 忽略 */ }
}
function molApplyHiddenAtoms() {
  if (!MC.viewer) return;
  molAllCurrentAtoms().forEach(function (a) {
    if (!molAtomVisible(a)) molHideAtom(a);
  });
}
// 把编辑后的坐标直接写回 3Dmol 原子对象；setStyle/addStyle 会清空 molObj，
// 之后 render 会按新坐标重建球和键，因此浮窗能实时看到结构变化。
function molApplyAtomEdits() {
  if (!MC.viewer) return;
  Object.keys(MC.atomEdits || {}).forEach(function (k) {
    if (MC.atomDeleted[k]) return;
    const parts = k.split(":");
    const a = molCurrentAtom({ model: Number(parts[0]), index: Number(parts[1]) });
    if (!a) return;
    const p = MC.atomEdits[k];
    a.x = p.x; a.y = p.y; a.z = p.z;
  });
}
function molChangeAtomElement(sel, text, record, noHistory) {
  if (!sel) return false;
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const sym = molResolveElement(text);
  if (!sym) { toast(tx("元素名或符号无效"), true); return false; }
  const a = molCurrentAtom(sel);
  if (!a) return false;
  const k = molSelKey(sel.model, sel.index);
  if (MC.atomDeleted[k]) return false;
  const from = String(a.elem || a.atom || "");
  const prevChange = MC.atomElementChanges[k] || null;
  if (!molSetAtomElementRaw(sel, sym, record === false ? prevChange : sym)) return false;
  if (!noHistory) molPushAtomHistory({ type: "element", atoms: [
    { model: sel.model, index: sel.index, from: from, to: sym, prevChange: prevChange }
  ] });
  return true;
}
function molAtomPanelSelections() {
  // 坐标弹窗存在时，一律按弹窗中列出的原子操作，不依赖当前高亮状态。
  const state = MC.atomPanel;
  if (state && state.items) {
    return (state.order || []).map(function (k) { return state.items[k]; })
      .filter(function (item) { return item && item.sel; })
      .map(function (item) { return item.sel; });
  }
  return (MC.selectedAtoms || []).slice();
}
function molChangeSelectedElement(text) {
  // 直接按弹窗中列出的原子修改，不要求它们仍处于选中状态。
  const list = molAtomPanelSelections();
  if (!list.length) { toast(tx("请先选择原子"), true); return false; }
  const entries = [];
  const to = molResolveElement(text);
  MC.historySuspend = true;
  try {
    list.forEach(function (sel) {
      const a = molCurrentAtom(sel);
      if (!a) return;
      const k = molSelKey(sel.model, sel.index);
      const from = String(a.elem || a.atom || "");
      const prevChange = MC.atomElementChanges[k] || null;
      if (molChangeAtomElement(sel, text, true, true)) {
        entries.push({ model: sel.model, index: sel.index, from: from,
                       to: to || text, prevChange: prevChange });
      }
    });
  } finally { MC.historySuspend = false; }
  if (entries.length) molPushAtomHistory({ type: "element", atoms: entries });
  return entries.length > 0;
}
function molRedrawSelection() {
  molClearSelectionShapes();
  if (!MC.viewer) return;
  const baseStyles = {};
  (MC.selectedAtoms || []).forEach(function (sel) {
    if (MC.atomDeleted[molSelKey(sel.model, sel.index)]) return;
    const a = molCurrentAtom(sel);
    if (!a) return;
    const k = molSelKey(sel.model, sel.index);
    baseStyles[k] = MC.selectStyles[k] || molAtomStyleSnapshot(a);
    MC.selectStyles[k] = baseStyles[k];
  });
  // 先把编辑后的坐标写回原子，再隐藏删除项；随后用空 addStyle 强制重建几何。
  molApplyAtomEdits();
  molApplyHiddenAtoms();
  if (Object.keys(MC.atomEdits || {}).length) MC.viewer.addStyle({}, {});
  (MC.selectedAtoms || []).forEach(function (sel) {
    if (MC.atomDeleted[molSelKey(sel.model, sel.index)]) return;
    const a = molCurrentAtom(sel);
    if (!a) return;
    const k = molSelKey(sel.model, sel.index);
    const orig = baseStyles[k] || molAtomStyleSnapshot(a);
    try {
      MC.viewer.addStyle(molSelector(a), { sphere: {
        color: "#ffcc00", radius: Math.max(0.38, orig.radius * 1.3)
      }});
    } catch (err) { /* 忽略 */ }
  });
  MC.viewer.render();
}
function molAtomPanelKey(sel) { return molSelKey(sel && sel.model, sel && sel.index); }
// 只有一个“原子坐标”弹窗：所有选中原子按行放在其中。
// 弹窗本身只在显式关闭（关闭按钮 / Esc / 退出选择模式）时移除；
// 单个原子被取消选中或删除时只移除对应行。
function molHideAtomPanel() {
  const state = MC.atomPanel;
  if (state) {
    if (state.boundsObserver) { try { state.boundsObserver.disconnect(); } catch (err) {} state.boundsObserver = null; }
    if (state.onBoundsResize) { window.removeEventListener("resize", state.onBoundsResize); state.onBoundsResize = null; }
    if (state.panel && state.panel.parentNode) state.panel.parentNode.removeChild(state.panel);
  }
  MC.atomPanel = null;
  MC.atomPanelSel = null;
}
function molCloseAtomPanel(sel) {
  // 不传 sel 表示关闭整个弹窗。
  if (!sel) { molHideAtomPanel(); return; }
  const state = MC.atomPanel;
  if (!state || !state.items) return;
  const key = molAtomPanelKey(sel);
  const item = state.items[key];
  if (!item) return;
  if (item.row && item.row.parentNode) item.row.parentNode.removeChild(item.row);
  delete state.items[key];
  state.order = (state.order || []).filter(function (k) { return k !== key; });
  // Keep the panel even when no rows remain; close it only via close icon / Esc / closeStructure.
  if (!state.order.length) { MC.atomPanelSel = null; return; }
  if (MC.atomPanelSel && molAtomPanelKey(MC.atomPanelSel) === key) {
    const last = state.order[state.order.length - 1];
    MC.atomPanelSel = state.items[last] ? state.items[last].sel : null;
  }
}
function molHideAddPanel() {
  const panel = $("molAddPanel");
  if (panel) panel.classList.add("hidden");
  molHidePeriodicPanel();
}
let molPeriodicTarget = null;
function molHidePeriodicPanel() {
  const panel = $("molPeriodicPanel");
  if (panel) panel.classList.add("hidden");
}
function molOpenPeriodicPanel(ev, target) {
  const add = $("molAddPanel");
  if ((!add || add.classList.contains("hidden")) && !(MC.atomPanel && MC.atomPanel.panel)) return;
  molPeriodicTarget = target || $("molAddElem");
  molBuildPeriodicTable();
  const panel = $("molPeriodicPanel");
  if (!panel) return;
  panel.classList.remove("hidden");
  // 从坐标弹窗打开时，周期表必须盖在坐标弹窗之上。
  if (MC.atomPanel && MC.atomPanel.panel) {
    const atomZ = parseInt(MC.atomPanel.panel.style.zIndex, 10) || 30;
    panel.style.zIndex = String(Math.max(30, atomZ + 10));
  } else {
    panel.style.zIndex = "";
  }
  molPositionPickPanel(ev, panel);
}
function molBuildPeriodicTable() {
  const box = $("molAddTable");
  if (!box || box.childElementCount) return;
  MOL_PERIODIC_ROWS.forEach(function (row) {
    for (let col = 0; col < 18; col++) {
      const sym = row[col] || "";
      if (!sym) {
        const blank = document.createElement("span");
        blank.className = "mol-add-cell blank";
        box.appendChild(blank);
        continue;
      }
      const info = molElementInfo(sym) || [sym, "", ""];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mol-add-cell";
      btn.textContent = sym;
      btn.title = info[1] ? info[1] + " / " + info[2] : sym;
      btn.onclick = function (ev) {
        ev.stopPropagation();
        const input = molPeriodicTarget || $("molAddElem");
        if (input && document.contains(input)) input.value = sym;
        molHidePeriodicPanel();
      };
      box.appendChild(btn);
    }
  });
}
function molOpenAddPanel(ev) {
  const reason = molAtomEditBlockReason(true);
  if (reason) { toast(reason, true); return; }
  if (!MC.cell) { toast(tx("需要晶格信息才能按分数坐标新增原子"), true); return; }
  molBuildPeriodicTable();
  molHidePeriodicPanel();
  const panel = $("molAddPanel");
  if (!panel) return;
  panel.classList.remove("hidden");
  molPositionPickPanel(ev, panel);
  const input = $("molAddElem");
  if (input) input.focus();
}
function molSubmitAddAtom() {
  const reason = molAtomEditBlockReason(true);
  if (reason) { toast(reason, true); return false; }
  if (!MC.cell) { toast(tx("需要晶格信息才能按分数坐标新增原子"), true); return false; }
  const input = $("molAddElem");
  const sym = input ? molResolveElement(input.value) : null;
  if (!sym) { toast(tx("元素名或符号无效"), true); return false; }
  const frac = ["Fx", "Fy", "Fz"].map(function (axis) {
    const el = $("molAdd" + axis);
    return el ? Number(el.value) || 0 : 0;
  });
  if (!molAddAtomToModel(sym, frac, true)) { toast(tx("新增原子失败"), true); return false; }
  toast(tx("已新增原子") + " " + sym, false, $("molAddAtom"));
  molHideAddPanel();
  return true;
}
function molAtomInput(row, prefix, axis) {
  return row && row.querySelector('[data-atom-axis="' + prefix + axis + '"]');
}
function molPanelNums(row, prefix) {
  return ["x", "y", "z"].map(function (axis) {
    const el = molAtomInput(row, prefix, axis);
    return el ? Number(el.value) || 0 : 0;
  });
}
function molSetAtomPanelSource(item, prefix) {
  const next = prefix === "F" ? "frac" : "cart";
  if (item.source === next) return;
  item.source = next;
  molFillAtomPanel(false, item);
}
function molSetPanelNums(row, prefix, vals, force) {
  ["x", "y", "z"].forEach(function (axis, i) {
    const el = molAtomInput(row, prefix, axis);
    if (el && (force || document.activeElement !== el)) el.value = Number(vals[i]).toFixed(4);
  });
}
function molFillAtomPanel(force, only) {
  const state = MC.atomPanel;
  if (!state || !state.panel) return;
  const panel = state.panel;
  const items = only
    ? [only]
    : (state.order || []).map(function (k) { return state.items[k]; }).filter(Boolean);
  const viewOnly = !!molAtomEditBlockReason(false);
  panel.classList.toggle("mol-atom-viewonly", viewOnly);
  items.forEach(function (item) {
    if (!item || !item.row) return;
    const row = item.row, sel = item.sel;
    const a = molCurrentAtom(sel);
    // 模型重建/切帧瞬间可能取不到原子；保留该行，等下一次刷新即可。
    if (!a) {
      const meta0 = row.querySelector(".mol-atom-meta");
      if (meta0) meta0.textContent = "#" + sel.index + "  " + String(sel.elem || "") + "  ·  暂不可用";
      return;
    }
    const p = molAtomDisplayPos(a);
    const many = MC.frames > 1;
    const frac = MC.cell ? molCartToFrac(p, MC.cell) : null;
    const elem = String(a.elem || a.atom || "");
    const meta = row.querySelector(".mol-atom-meta");
    const modeLabel = MC.volume ? "  ·  等值面" : (many ? "  ·  多帧轨迹" : "");
    if (meta) meta.textContent = "#" + sel.index + "  " + elem + modeLabel;
    ["Fx", "Fy", "Fz"].forEach(function (axis, i) {
      const el = molAtomInput(row, "F", axis.slice(1));
      if (!el) return;
      // 分数与笛卡尔坐标互斥编辑；等值面/轨迹下只读，仅用于查看坐标。
      el.readOnly = viewOnly || !frac || item.source !== "frac";
      if (!frac) el.value = "";
      else if (force || document.activeElement !== el) el.value = Number(frac[i]).toFixed(4);
    });
    molSetPanelNums(row, "C", [p.x, p.y, p.z], force);
    ["Cx", "Cy", "Cz"].forEach(function (axis) {
      const el = molAtomInput(row, "C", axis.slice(1));
      if (el) el.readOnly = viewOnly || item.source !== "cart";
    });
    const del = row.querySelector(".mol-atom-del");
    if (del) {
      del.disabled = viewOnly;
      del.classList.toggle("hidden", viewOnly);
      del.title = tx(viewOnly ? "当前模式不可删除原子" : "删除原子");
    }
  });
  molClampAtomPanel(panel);
}
function molAtomPanelArea(panel) {
  const win = (panel && panel.closest && panel.closest(".mol-win")) ||
    ($("molView") && $("molView").querySelector(".mol-win"));
  if (!win) return null;
  const canvas = win.querySelector(".mol-canvas") || win;
  const wr = win.getBoundingClientRect();
  const cr = canvas.getBoundingClientRect();
  return { left: cr.left - wr.left, top: cr.top - wr.top,
           right: cr.right - wr.left, bottom: cr.bottom - wr.top,
           width: cr.width, height: cr.height,
           clientLeft: wr.left, clientTop: wr.top };
}
// 把弹窗限制在结构显示区内（不覆盖浮窗标题栏/工具栏），并在空间不足时让内容区滚动。
function molClampAtomPanel(panel) {
  if (!panel) return;
  const area = molAtomPanelArea(panel);
  if (!area) return;
  const margin = 6;
  const maxW = Math.max(80, area.width - margin * 2);
  const maxH = Math.max(60, area.height - margin * 2);
  panel.style.maxWidth = maxW + "px";
  panel.style.maxHeight = maxH + "px";
  const w = panel.offsetWidth || 320;
  const h = panel.offsetHeight || 220;
  const minLeft = area.left + margin;
  const minTop = area.top + margin;
  const maxLeft = Math.max(minLeft, area.right - margin - w);
  const maxTop = Math.max(minTop, area.bottom - margin - h);
  let left = parseFloat(panel.style.left);
  let top = parseFloat(panel.style.top);
  if (!Number.isFinite(left)) left = area.left + (area.width - w) / 2;
  if (!Number.isFinite(top)) top = area.top + (area.height - h) / 2;
  panel.style.left = Math.max(minLeft, Math.min(left, maxLeft)) + "px";
  panel.style.top = Math.max(minTop, Math.min(top, maxTop)) + "px";
}
// 浮窗/显示区变化后，若弹窗已不完整落在结构显示区内，则复位到右上角。
function molAtomPanelNeedsReposition(panel) {
  const area = molAtomPanelArea(panel);
  if (!area) return false;
  const margin = 6;
  const w = panel.offsetWidth || 320;
  const h = panel.offsetHeight || 220;
  const left = parseFloat(panel.style.left);
  const top = parseFloat(panel.style.top);
  if (!Number.isFinite(left) || !Number.isFinite(top)) return true;
  const minLeft = area.left + margin;
  const minTop = area.top + margin;
  const maxLeft = Math.max(minLeft, area.right - margin - w);
  const maxTop = Math.max(minTop, area.bottom - margin - h);
  return left < minLeft - 0.5 || left > maxLeft + 0.5 ||
         top < minTop - 0.5 || top > maxTop + 0.5;
}
function molWatchAtomPanelBounds(state, panel) {
  const win = panel && panel.closest && panel.closest(".mol-win");
  const canvas = win && win.querySelector(".mol-canvas");
  state.onBoundsResize = function () {
    if (state.panel !== panel || !panel.parentNode) return;
    if (molAtomPanelNeedsReposition(panel)) molPositionAtomPanel(null, panel);
    else molClampAtomPanel(panel);
  };
  window.addEventListener("resize", state.onBoundsResize);
  if (typeof ResizeObserver !== "undefined" && canvas) {
    state.boundsObserver = new ResizeObserver(state.onBoundsResize);
    state.boundsObserver.observe(canvas);
    state.boundsObserver.observe(panel);
  }
}
function molPositionAtomPanel(ev, panel) {
  const area = molAtomPanelArea(panel);
  if (!area) return;
  // 先按当前可用空间收紧最大尺寸，再贴紧右上角，避免缩放后尺寸变化导致偏左。
  molClampAtomPanel(panel);
  // 默认贴紧结构显示区右上角，不跟随右键/点击位置。
  panel.style.left = (area.right - 6 - (panel.offsetWidth || 320)) + "px";
  panel.style.top = (area.top + 6) + "px";
  molClampAtomPanel(panel);
}
function molBindAtomPanelDrag(panel) {
  const head = panel.querySelector(".mol-pick-head");
  if (!head) return;
  let drag = null;
  head.addEventListener("pointerdown", function (ev) {
    if (ev.button !== 0 || (ev.target && ev.target.closest && ev.target.closest("button, input, select, textarea"))) return;
    ev.preventDefault(); ev.stopPropagation();
    drag = { x: ev.clientX, y: ev.clientY,
             left: parseFloat(panel.style.left) || 0, top: parseFloat(panel.style.top) || 0 };
    panel.style.zIndex = String(++MC.atomPanelZ);
    try { head.setPointerCapture(ev.pointerId); } catch (err) {}
  });
  head.addEventListener("pointermove", function (ev) {
    if (!drag) return;
    ev.preventDefault(); ev.stopPropagation();
    panel.style.left = (drag.left + ev.clientX - drag.x) + "px";
    panel.style.top = (drag.top + ev.clientY - drag.y) + "px";
    molClampAtomPanel(panel);
  });
  ["pointerup", "pointercancel"].forEach(function (name) {
    head.addEventListener(name, function () { drag = null; });
  });
  head.addEventListener("click", function (ev) { ev.stopPropagation(); });
}
function molBindAtomPanelChrome(panel) {
  panel.addEventListener("click", function (ev) { ev.stopPropagation(); });
  const elemInput = panel.querySelector(".mol-atom-elem-input");
  const elemApply = panel.querySelector(".mol-atom-elem-apply");
  if (elemApply) elemApply.onclick = function (ev) {
    ev.stopPropagation();
    if (elemInput) molChangeSelectedElement(elemInput.value);
  };
  if (elemInput) elemInput.onkeydown = function (ev) {
    if (ev.key !== "Enter") return;
    ev.preventDefault(); ev.stopPropagation();
    if (elemApply) elemApply.click();
  };
  const tableBtn = panel.querySelector(".mol-atom-elem-table");
  if (tableBtn) tableBtn.onclick = function (ev) {
    ev.stopPropagation();
    molOpenPeriodicPanel(ev, elemInput);
  };
  const delAll = panel.querySelector(".mol-atom-del-all");
  if (delAll) delAll.onclick = function (ev) { ev.stopPropagation(); molDeleteSelectedWithConfirm(); };
  const close = panel.querySelector(".mol-atom-close");
  if (close) close.onclick = function (ev) { ev.stopPropagation(); molHideAtomPanel(); };
}
function molBindAtomRow(row, item) {
  const del = row.querySelector(".mol-atom-del");
  if (del) del.onclick = function (ev) { ev.stopPropagation(); molDeleteAtom(item.sel); };
  const elemInput = row.querySelector(".mol-atom-row-elem-input");
  const elemApply = row.querySelector(".mol-atom-row-elem-apply");
  const elemTable = row.querySelector(".mol-atom-row-elem-table");
  if (elemTable) elemTable.onclick = function (ev) {
    ev.stopPropagation();
    molOpenPeriodicPanel(ev, elemInput);
  };
  if (elemApply) elemApply.onclick = function (ev) {
    ev.stopPropagation();
    molChangeAtomElement(item.sel, elemInput && elemInput.value, true);
  };
  if (elemInput) elemInput.onkeydown = function (ev) {
    if (ev.key !== "Enter") return;
    ev.preventDefault(); ev.stopPropagation();
    if (elemApply) elemApply.click();
  };
  ["F", "C"].forEach(function (prefix) {
    ["x", "y", "z"].forEach(function (axis) {
      const el = molAtomInput(row, prefix, axis);
      if (!el) return;
      el.addEventListener("focus", function () { molSetAtomPanelSource(item, prefix); });
      el.oninput = function () {
        const sel = item.sel;
        if (!sel || molAtomEditBlockReason(false)) return;
        molSetAtomPanelSource(item, prefix);
        const a = molCurrentAtom(sel);
        if (!a) return;
        let pos = null;
        if (prefix === "F" && MC.cell) {
          const f = molPanelNums(row, "F");
          pos = molFracToCart(f, MC.cell);
          molSetPanelNums(row, "C", [pos.x, pos.y, pos.z]);
        } else if (prefix === "C") {
          const v = molPanelNums(row, "C");
          pos = { x: v[0], y: v[1], z: v[2] };
          if (MC.cell) {
            const frac = molCartToFrac(pos, MC.cell);
            if (frac) molSetPanelNums(row, "F", frac);
          }
        }
        if (!pos) return;
        MC.atomEdits[molSelKey(sel.model, sel.index)] = pos;
        molRedrawSelection();
        molMarkViewDirty();
      };
    });
  });
}
// sels 可传单个原子或数组；replace=true 时让行严格等于当前传入的原子集合。
function molOpenAtomPanel(sels, ev, replace) {
  const list = (Array.isArray(sels) ? sels : [sels]).filter(Boolean);
  if (!list.length) return;
  const template = $("molAtomPanel"), rowTemplate = $("molAtomRow");
  if (!template || !rowTemplate) return;
  // 浮窗内始终只保留一个坐标弹窗；清掉非当前状态持有的旧克隆。
  document.querySelectorAll(".mol-atom-panel:not([data-atom-template])").forEach(function (el) {
    if (MC.atomPanel && MC.atomPanel.panel === el) return;
    if (el.parentNode) el.parentNode.removeChild(el);
  });
  let state = MC.atomPanel;
  if (!state || !state.panel || !state.panel.parentNode) {
    const win = $("molView") && $("molView").querySelector(".mol-win");
    if (!win) return;
    const panel = template.cloneNode(true);
    panel.removeAttribute("id");
    panel.removeAttribute("data-atom-template");
    panel.classList.remove("hidden");
    state = { panel: panel, items: {}, order: [] };
    MC.atomPanel = state;
    win.appendChild(panel);
    panel.style.zIndex = String(++MC.atomPanelZ);
    molPositionAtomPanel(ev, panel);
    molBindAtomPanelDrag(panel);
    molBindAtomPanelChrome(panel);
    molWatchAtomPanelBounds(state, panel);
  } else {
    state.panel.style.zIndex = String(++MC.atomPanelZ);
  }
  if (replace) {
    const keep = {};
    list.forEach(function (sel) { keep[molAtomPanelKey(sel)] = true; });
    (state.order || []).slice().forEach(function (key) {
      if (keep[key]) return;
      const old = state.items[key];
      if (old && old.row && old.row.parentNode) old.row.parentNode.removeChild(old.row);
      delete state.items[key];
    });
    state.order = state.order.filter(function (key) { return !!state.items[key]; });
  }
  const rows = state.panel.querySelector(".mol-atom-rows");
  if (!rows) return;
  list.forEach(function (sel) {
    const key = molAtomPanelKey(sel);
    let item = state.items[key];
    if (!item) {
      const row = rowTemplate.cloneNode(true);
      row.removeAttribute("id");
      row.removeAttribute("data-atom-row-template");
      row.classList.remove("hidden");
      row.dataset.atomKey = key;
      item = { sel: { model: sel.model, index: sel.index, elem: sel.elem },
               source: "cart", row: row };
      state.items[key] = item;
      state.order.push(key);
      rows.appendChild(row);
      molBindAtomRow(row, item);
    } else if (sel.elem) {
      item.sel.elem = sel.elem;
    }
  });
  const last = state.items[molAtomPanelKey(list[list.length - 1])];
  MC.atomPanelSel = last ? last.sel : null;
  molFillAtomPanel(false);
  molClampAtomPanel(state.panel);
}
// opts.silent：未进入按钮模式时，快捷键选中（Shift+框选 / Ctrl+点击）只高亮，不新建“原子坐标”弹窗。
// 按钮模式内的快捷键选中照常弹坐标；已有弹窗始终保留到显式关闭，其余操作与按钮模式一致。
function molAfterSelectionChange(ev, opts) {
  molRedrawSelection();
  molSyncSelectButton();
  if ((MC.selectedAtoms || []).length && !(opts && opts.silent)) {
    // 所有选中原子共用一个弹窗；空选择时保留已有弹窗，等用户显式关闭。
    molOpenAtomPanel(MC.selectedAtoms, ev, true);
  }
  molMarkViewDirty();
}
function molSelectAtom(desc, additive, ev, opts) {
  if (!desc) return;
  const k = molSelKey(desc.model, desc.index);
  const at = MC.selectedAtoms.findIndex(function (x) { return molSelKey(x.model, x.index) === k; });
  if (additive) {
    if (at >= 0) { MC.selectedAtoms.splice(at, 1); molCloseAtomPanel(desc); }
    else MC.selectedAtoms.push(desc);
  } else {
    // 普通点击只选一个；此前选中的原子取消高亮，但坐标弹窗保留到手动关闭。
    MC.selectedAtoms = [desc];
  }
  molAfterSelectionChange(ev, opts);
}
function molDeleteAtom(sel) {
  if (!sel) return false;
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const snap = molAtomDeleteSnapshot(sel);
  if (!snap) return false;
  const k = molSelKey(sel.model, sel.index);
  MC.atomDeleted[k] = true;
  delete MC.atomEdits[k];
  delete MC.atomElementChanges[k];
  MC.selectedAtoms = MC.selectedAtoms.filter(function (x) { return molSelKey(x.model, x.index) !== k; });
  molCloseAtomPanel(sel);
  molClearSelectionShapes();
  molRedrawSelection();
  molApplyHiddenAtoms();
  if (MC.viewer) MC.viewer.render();
  molMarkViewDirty();
  molPushAtomHistory({ type: "delete", atoms: [snap] });
  return true;
}
function molDeleteSelected(victims) {
  const targets = (victims || MC.selectedAtoms || []).slice();
  if (!targets.length) return false;
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const snapshots = targets.map(molAtomDeleteSnapshot).filter(Boolean);
  const victimKeys = targets.map(function (sel) { return molSelKey(sel.model, sel.index); });
  targets.forEach(function (sel) {
    const k = molSelKey(sel.model, sel.index);
    MC.atomDeleted[k] = true;
    delete MC.atomEdits[k];
    delete MC.atomElementChanges[k];
    molCloseAtomPanel(sel);
  });
  MC.selectedAtoms = (MC.selectedAtoms || []).filter(function (sel) {
    return victimKeys.indexOf(molSelKey(sel.model, sel.index)) < 0;
  });
  molClearSelectionShapes();
  molApplyHiddenAtoms();
  if (MC.viewer) MC.viewer.render();
  molMarkViewDirty();
  if (snapshots.length) molPushAtomHistory({ type: "delete", atoms: snapshots });
  return true;
}
async function molDeleteSelectedWithConfirm() {
  const list = molAtomPanelSelections().filter(function (sel) {
    return !MC.atomDeleted[molSelKey(sel.model, sel.index)];
  });
  if (!list.length) { toast(tx("请先选择原子"), true); return false; }
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const ok = await openConfirm(tx("删除原子"),
    tx("确定删除选中的 ") + list.length + tx(" 个原子吗？此操作不可恢复。"),
    { danger: true, okText: "删除" });
  if (!ok) return false;
  return molDeleteSelected(list);
}
// 世界坐标中沿某个屏幕方向移动 1 Å 对应多少像素；用于把屏幕操作换算成模型位移。
function molScreenUnitsPerPixel(direction) {
  const sel = (MC.selectedAtoms || [])[0];
  let a = sel && molCurrentAtom(sel);
  // 未选中原子时也从当前模型取一个原子标定屏幕比例，供按像素换算的辅助逻辑使用。
  if (!a) {
    const atoms = molAllCurrentAtoms();
    a = atoms && atoms[0];
  }
  if (!a || !MC.viewer || !MC.viewer.modelToScreen || !direction) return 0.001;
  const p = molAtomDisplayPos(a);
  const q = { x: p.x + direction.x, y: p.y + direction.y, z: p.z + direction.z };
  let pts;
  try { pts = MC.viewer.modelToScreen([p, q]); } catch (err) { return 0.001; }
  if (!pts || pts.length < 2) return 0.001;
  const dx = pts[1].x - pts[0].x;
  const dy = pts[1].y - pts[0].y;
  const px = Math.sqrt(dx * dx + dy * dy);
  if (!isFinite(px) || px <= 1e-6) return 0.001;
  return 1 / px;
}
function molViewMoveStep(screenAxis) {
  const host = $("molCanvas");
  const span = screenAxis === "x"
    ? ((host && host.clientWidth) || window.innerWidth || 800)
    : ((host && host.clientHeight) || window.innerHeight || 600);
  const axes = molScreenAxes();
  const dir = screenAxis === "x" ? axes.right : axes.up;
  return span * 0.05 * molScreenUnitsPerPixel(dir);
}
// 绕任意单位轴旋转向量（Rodrigues 公式）。旋转轴来自 molScreenAxes()。
function molRotateVec(v, axis, angle) {
  if (!v || !axis || !isFinite(angle)) return v;
  const a = { x: axis.x || 0, y: axis.y || 0, z: axis.z || 0 };
  const n = Math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z);
  if (n <= 1e-12 || Math.abs(angle) < 1e-12) return v;
  a.x /= n; a.y /= n; a.z /= n;
  const c = Math.cos(angle), s = Math.sin(angle);
  const dot = a.x * v.x + a.y * v.y + a.z * v.z;
  const cx = a.y * v.z - a.z * v.y;
  const cy = a.z * v.x - a.x * v.z;
  const cz = a.x * v.y - a.y * v.x;
  const k = 1 - c;
  return {
    x: v.x * c + cx * s + a.x * dot * k,
    y: v.y * c + cy * s + a.y * dot * k,
    z: v.z * c + cz * s + a.z * dot * k
  };
}
function molQuatRotate(q, v) {
  const x = q.x, y = q.y, z = q.z, w = q.w;
  const ix = w * v.x + y * v.z - z * v.y;
  const iy = w * v.y + z * v.x - x * v.z;
  const iz = w * v.z + x * v.y - y * v.x;
  const iw = -x * v.x - y * v.y - z * v.z;
  return {
    x: ix * w + iw * -x + iy * -z - iz * -y,
    y: iy * w + iw * -y + iz * -x - ix * -z,
    z: iz * w + iw * -z + ix * -y - iy * -x
  };
}
function molScreenAxes() {
  const v = MC.viewer;
  const q = v && v.rotationGroup && v.rotationGroup.quaternion;
  const inv = q ? { x: -q.x, y: -q.y, z: -q.z, w: q.w } : { x: 0, y: 0, z: 0, w: 1 };
  const unit = function (x, y, z) {
    const r = molQuatRotate(inv, { x: x, y: y, z: z });
    const n = Math.sqrt(r.x*r.x + r.y*r.y + r.z*r.z) || 1;
    return { x: r.x / n, y: r.y / n, z: r.z / n };
  };
  return { right: unit(1, 0, 0), up: unit(0, 1, 0), normal: unit(0, 0, 1) };
}
function molSelectedCenter() {
  let n = 0, x = 0, y = 0, z = 0;
  (MC.selectedAtoms || []).forEach(function (sel) {
    const a = molCurrentAtom(sel);
    if (!a) return;
    const p = molAtomDisplayPos(a);
    x += p.x; y += p.y; z += p.z; n++;
  });
  return n ? { x: x / n, y: y / n, z: z / n } : null;
}
function molRotateSelectedBy(axis, angle, noHistory) {
  if (!MC.viewer || !(MC.selectedAtoms || []).length) return false;
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  // 单选一个原子时以原胞中心为轴，绕自身旋转不会改变坐标；多选仍绕选区中心。
  const center = (MC.selectedAtoms.length === 1 && MC.cell)
    ? molFracToCart([0.5, 0.5, 0.5], MC.cell) : molSelectedCenter();
  if (!center || !axis || !isFinite(angle) || Math.abs(angle) < 1e-9) return false;
  const snapshots = noHistory ? null : molAtomCoordSnapshots();
  MC.selectedAtoms.forEach(function (sel) {
    const a = molCurrentAtom(sel);
    if (!a) return;
    const p = molAtomDisplayPos(a);
    const r = molRotateVec({ x: p.x - center.x, y: p.y - center.y, z: p.z - center.z }, axis, angle);
    MC.atomEdits[molSelKey(sel.model, sel.index)] = {
      x: center.x + r.x, y: center.y + r.y, z: center.z + r.z
    };
  });
  molRedrawSelection();
  molFillAtomPanel(true);
  molMarkViewDirty();
  if (!noHistory) molPushTransformHistory(snapshots);
  return true;
}
// 屏幕坐标系：x 向右、y 向上、z 指向观察者。旋转只允许绕屏幕 X/Y 轴。
function molRotateSelectedScreenX(angle) {
  return molRotateSelectedBy(molScreenAxes().right, angle);
}
function molRotateSelectedScreenY(angle) {
  return molRotateSelectedBy(molScreenAxes().up, angle);
}
function molMoveSelected(dx, dy, dz, noHistory) {
  if (!MC.selectedAtoms.length) return false;
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const snapshots = noHistory ? null : molAtomCoordSnapshots();
  MC.selectedAtoms.forEach(function (sel) {
    const a = molCurrentAtom(sel);
    if (!a) return;
    const p = molAtomDisplayPos(a);
    MC.atomEdits[molSelKey(sel.model, sel.index)] = { x: p.x + dx, y: p.y + dy, z: p.z + dz };
  });
  molRedrawSelection();
  molFillAtomPanel();
  molMarkViewDirty();
  if (!noHistory) molPushTransformHistory(snapshots);
  return true;
}
// 以屏幕横/纵方向的位移量移动原子，结果换算成世界坐标增量。
function molMoveSelectedOnScreen(screenX, screenY, noHistory) {
  const axes = molScreenAxes();
  return molMoveSelected(
    screenX * axes.right.x + screenY * axes.up.x,
    screenX * axes.right.y + screenY * axes.up.y,
    screenX * axes.right.z + screenY * axes.up.z, noHistory);
}
function molMoveSelectedByPixels(dxPx, dyPx, noHistory) {
  const axes = molScreenAxes();
  return molMoveSelectedOnScreen(
    dxPx * molScreenUnitsPerPixel(axes.right),
    -dyPx * molScreenUnitsPerPixel(axes.up), noHistory);
}
// 晶胞整体变换辅助函数：当前不绑定快捷键（方向键调整视角或选中的原子），结构写回仍可保存 cell。
// 轴向、角度与屏幕位移比例与原子变换一致；原子与晶格框一起变换。
function molCellCenter() {
  if (!MC.cell || MC.cell.length < 3) return null;
  return molFracToCart([0.5, 0.5, 0.5], MC.cell);
}
function molSourceAtomRefs() {
  const out = [], seen = Object.create(null);
  function add(a, fallback) {
    if (!a) return;
    const index = Number.isInteger(a.index) ? a.index : fallback;
    const model = a.model === undefined ? 0 : a.model;
    const key = molSelKey(model, index);
    if (seen[key]) return;
    seen[key] = true;
    out.push({ model: model, index: index, a: a });
  }
  (MC.sourceFrames || []).forEach(function (frame) {
    (frame || []).forEach(function (a, i) { add(a, i); });
  });
  if (!out.length) molAllCurrentAtoms().forEach(function (a, i) { add(a, i); });
  return out;
}
function molTransformCellPoint(p, center, axis, angle, shift) {
  let q = { x: p.x, y: p.y, z: p.z };
  if (center && axis && isFinite(angle) && Math.abs(angle) > 1e-12) {
    const r = molRotateVec(
      { x: p.x - center.x, y: p.y - center.y, z: p.z - center.z }, axis, angle);
    q = { x: center.x + r.x, y: center.y + r.y, z: center.z + r.z };
  }
  if (shift) { q.x += shift.x; q.y += shift.y; q.z += shift.z; }
  return q;
}
function molApplyCellTransform(axis, angle, shift) {
  if (!MC.viewer || !MC.cell || MC.cell.length < 3) return false;
  const reason = molAtomEditBlockReason(false);
  if (reason) { toast(reason, true); return false; }
  const center = (axis && isFinite(angle) && Math.abs(angle) > 1e-12)
    ? molCellCenter() : null;
  const transform = function (p) { return molTransformCellPoint(p, center, axis, angle, shift); };
  // 先变换已有逐原子编辑，再同步原胞坐标，避免丢失用户先前的调整。
  Object.keys(MC.atomEdits || {}).forEach(function (k) {
    MC.atomEdits[k] = transform(MC.atomEdits[k]);
  });
  molSourceAtomRefs().forEach(function (ref) {
    const k = molSelKey(ref.model, ref.index);
    const p = MC.atomEdits[k] || {
      x: Number(ref.a.x) || 0, y: Number(ref.a.y) || 0, z: Number(ref.a.z) || 0
    };
    const q = transform(p);
    ref.a.x = q.x; ref.a.y = q.y; ref.a.z = q.z;
    MC.atomEdits[k] = { x: q.x, y: q.y, z: q.z };
  });
  MC.cellOrigin = transform(molCellOffset());
  if (axis && isFinite(angle) && Math.abs(angle) > 1e-12) {
    MC.cell = MC.cell.map(function (v) {
      const r = molRotateVec({ x: v[0], y: v[1], z: v[2] }, axis, angle);
      return [r.x, r.y, r.z];
    });
  }
  molApplySupercellModel();
  molRedrawCell();
  molApplyHiddenAtoms();
  molApplyAtomEdits();
  MC.viewer.render();
  molMarkViewDirty();
  return true;
}
function molRotateCellBy(axis, angle) { return molApplyCellTransform(axis, angle, null); }
function molRotateCellScreenX(angle) { return molRotateCellBy(molScreenAxes().right, angle); }
function molRotateCellScreenY(angle) { return molRotateCellBy(molScreenAxes().up, angle); }
function molMoveCell(dx, dy, dz) {
  return molApplyCellTransform(null, 0, { x: dx, y: dy, z: dz });
}
function molMoveCellOnScreen(screenX, screenY) {
  const axes = molScreenAxes();
  return molMoveCell(
    screenX * axes.right.x + screenY * axes.up.x,
    screenX * axes.right.y + screenY * axes.up.y,
    screenX * axes.right.z + screenY * axes.up.z);
}
function molElemSymbol(a) {
  const raw = String((a && (a.elem || a.atom)) || "").trim();
  return molResolveElement(raw) || raw;
}
// VASP 的元素计数按连续元素块排列；新原子插到同元素块末尾，避免
// “Si O … Si” 这种顺序导致 VASP 把末尾 Si 当成 O 读取。
function molInsertIndexForElement(base, sym) {
  let last = -1;
  (base || []).forEach(function (a, i) { if (molElemSymbol(a) === sym) last = i; });
  return last >= 0 ? last + 1 : (base || []).length;
}
function molShiftNumKey(key, ins, count) {
  const parts = String(key).split(":");
  for (let i = 1; i <= count && i < parts.length; i++) {
    const n = Number(parts[i]);
    if (Number.isFinite(n) && n >= ins) parts[i] = String(n + 1);
  }
  return parts.join(":");
}
function molShiftMapKeys(obj, ins, count, visit) {
  const out = {};
  Object.keys(obj || {}).forEach(function (key) {
    const value = obj[key];
    if (visit) visit(value);
    out[molShiftNumKey(key, ins, count)] = value;
  });
  return out;
}
// 在原胞序列中间插入原子后，同步所有按原子序号记录的编辑/样式/拾取引用。
function molShiftIndicesAfterInsert(ins) {
  MC.atomEdits = molShiftMapKeys(MC.atomEdits, ins, 1);
  MC.atomDeleted = molShiftMapKeys(MC.atomDeleted, ins, 1);
  MC.atomElementChanges = molShiftMapKeys(MC.atomElementChanges, ins, 1);
  MC.atomStyles = molShiftMapKeys(MC.atomStyles, ins, 1, function (v) {
    if (v && typeof v === "object" && Number.isInteger(v.index) && v.index >= ins) v.index++;
  });
  MC.bondStyles = molShiftMapKeys(MC.bondStyles, ins, 2, function (v) {
    if (!v) return;
    if (Number.isInteger(v.a) && v.a >= ins) v.a++;
    if (Number.isInteger(v.b) && v.b >= ins) v.b++;
  });
  MC.bondBaseOrders = molShiftMapKeys(MC.bondBaseOrders, ins, 2);
  (MC.sourceFrames || []).forEach(function (frame) {
    (frame || []).forEach(function (a) {
      if (Array.isArray(a.bonds)) {
        a.bonds = a.bonds.map(function (j) { return Number(j) >= ins ? Number(j) + 1 : j; });
      }
    });
  });
  (MC.selectedAtoms || []).forEach(function (sel) {
    if (Number.isInteger(sel.index) && sel.index >= ins) sel.index++;
  });
  (MC.atomAdditions || []).forEach(function (a) {
    if (Number.isInteger(a.index) && a.index >= ins) a.index++;
  });
  (MC.pickAtoms || []).forEach(function (a) {
    if (Number.isInteger(a.index) && a.index >= ins) a.index++;
  });
  (MC.pickBonds || []).concat((MC.bondPickShapes || []).map(function (e) { return e.bond; }))
    .forEach(function (b) {
      if (!b) return;
      if (Number.isInteger(b.a) && b.a >= ins) b.a++;
      if (Number.isInteger(b.b) && b.b >= ins) b.b++;
    });
  if (MC.styleAtom && Number.isInteger(MC.styleAtom.index) && MC.styleAtom.index >= ins) MC.styleAtom.index++;
  if (MC.styleBond) {
    if (Number.isInteger(MC.styleBond.a) && MC.styleBond.a >= ins) MC.styleBond.a++;
    if (Number.isInteger(MC.styleBond.b) && MC.styleBond.b >= ins) MC.styleBond.b++;
  }
  // 坐标弹窗按原子序号索引，插入位置之后的行要同步迁移。
  if (MC.atomPanel && MC.atomPanel.items) {
    const state = MC.atomPanel;
    const moved = {}, order = [];
    (state.order || []).forEach(function (key) {
      const item = state.items[key];
      if (!item) return;
      if (item.sel && Number.isInteger(item.sel.index) && item.sel.index >= ins) item.sel.index++;
      const next = molAtomPanelKey(item.sel);
      if (item.row) item.row.dataset.atomKey = next;
      moved[next] = item;
      order.push(next);
    });
    state.items = moved;
    state.order = order;
  }
  if (MC.atomPanelSel && Number.isInteger(MC.atomPanelSel.index) && MC.atomPanelSel.index >= ins) {
    MC.atomPanelSel.index++;
  }
}
function molUnshiftMapKeys(obj, ins, count, visit) {
  const out = {};
  Object.keys(obj || {}).forEach(function (key) {
    const parts = String(key).split(":");
    let drop = false;
    for (let i = 1; i <= count && i < parts.length; i++) {
      const n = Number(parts[i]);
      if (!Number.isFinite(n)) continue;
      if (n === ins) { drop = true; break; }
      if (n > ins) parts[i] = String(n - 1);
    }
    if (drop) return;
    const value = obj[key];
    if (visit && visit(value) === false) return;
    out[parts.join(":")] = value;
  });
  return out;
}
// 撤销新增原子：所有按序号记录的引用同步前移，并丢弃指向被移除原子的记录。
function molShiftIndicesAfterRemove(ins) {
  MC.atomEdits = molUnshiftMapKeys(MC.atomEdits, ins, 1);
  MC.atomDeleted = molUnshiftMapKeys(MC.atomDeleted, ins, 1);
  MC.atomElementChanges = molUnshiftMapKeys(MC.atomElementChanges, ins, 1);
  MC.selectStyles = molUnshiftMapKeys(MC.selectStyles, ins, 1);
  MC.atomStyles = molUnshiftMapKeys(MC.atomStyles, ins, 1, function (v) {
    if (!v || typeof v !== "object") return;
    if (Number.isInteger(v.index) && v.index === ins) return false;
    if (Number.isInteger(v.index) && v.index > ins) v.index--;
  });
  MC.bondStyles = molUnshiftMapKeys(MC.bondStyles, ins, 2, function (v) {
    if (!v) return;
    if ((Number.isInteger(v.a) && v.a === ins) || (Number.isInteger(v.b) && v.b === ins)) return false;
    if (Number.isInteger(v.a) && v.a > ins) v.a--;
    if (Number.isInteger(v.b) && v.b > ins) v.b--;
  });
  MC.bondBaseOrders = molUnshiftMapKeys(MC.bondBaseOrders, ins, 2);
  (MC.sourceFrames || []).forEach(function (frame) {
    (frame || []).forEach(function (a) {
      if (Array.isArray(a.bonds)) {
        a.bonds = a.bonds.map(function (j) { return Number(j); })
          .filter(function (j) { return j !== ins; })
          .map(function (j) { return j > ins ? j - 1 : j; });
      }
    });
  });
  MC.selectedAtoms = (MC.selectedAtoms || []).filter(function (sel) {
    return !(Number.isInteger(sel.index) && sel.index === ins);
  }).map(function (sel) {
    if (Number.isInteger(sel.index) && sel.index > ins) sel.index--;
    return sel;
  });
  MC.atomAdditions = (MC.atomAdditions || []).filter(function (a) {
    return !(a.model === 0 && a.index === ins);
  }).map(function (a) {
    if (a.model === 0 && a.index > ins) a.index--;
    return a;
  });
  MC.pickAtoms = (MC.pickAtoms || []).filter(function (a) {
    return !(Number.isInteger(a.index) && a.index === ins);
  }).map(function (a) {
    if (Number.isInteger(a.index) && a.index > ins) a.index--;
    return a;
  });
  const dropBond = function (b) {
    return (Number.isInteger(b.a) && b.a === ins) || (Number.isInteger(b.b) && b.b === ins);
  };
  const shiftBond = function (b) {
    if (Number.isInteger(b.a) && b.a > ins) b.a--;
    if (Number.isInteger(b.b) && b.b > ins) b.b--;
    return b;
  };
  MC.pickBonds = (MC.pickBonds || []).filter(function (b) { return !b || !dropBond(b); }).map(shiftBond);
  MC.bondPickShapes = (MC.bondPickShapes || []).filter(function (e) {
    return !e || !e.bond || !dropBond(e.bond);
  }).map(function (e) { if (e && e.bond) shiftBond(e.bond); return e; });
  if (MC.styleAtom && Number.isInteger(MC.styleAtom.index)) {
    if (MC.styleAtom.index === ins) MC.styleAtom = null;
    else if (MC.styleAtom.index > ins) MC.styleAtom.index--;
  }
  if (MC.styleBond) {
    if ((Number.isInteger(MC.styleBond.a) && MC.styleBond.a === ins) ||
        (Number.isInteger(MC.styleBond.b) && MC.styleBond.b === ins)) MC.styleBond = null;
    else shiftBond(MC.styleBond);
  }
  if (MC.atomPanel && MC.atomPanel.items) {
    const state = MC.atomPanel, moved = {}, order = [];
    (state.order || []).forEach(function (key) {
      const item = state.items[key];
      if (!item) return;
      if (item.sel && Number.isInteger(item.sel.index) && item.sel.index === ins) {
        if (item.row && item.row.parentNode) item.row.parentNode.removeChild(item.row);
        return;
      }
      if (item.sel && Number.isInteger(item.sel.index) && item.sel.index > ins) item.sel.index--;
      const next = molAtomPanelKey(item.sel);
      if (item.row) item.row.dataset.atomKey = next;
      moved[next] = item;
      order.push(next);
    });
    state.items = moved;
    state.order = order;
  }
  if (MC.atomPanelSel && Number.isInteger(MC.atomPanelSel.index)) {
    if (MC.atomPanelSel.index === ins) MC.atomPanelSel = null;
    else if (MC.atomPanelSel.index > ins) MC.atomPanelSel.index--;
  }
}
function molRemoveAddedAtom(ins) {
  const base = MC.sourceFrames && MC.sourceFrames[0];
  if (!base || !Number.isInteger(ins) || ins < 0 || ins >= base.length) return false;
  base.splice(ins, 1);
  base.forEach(function (a, i) { a.index = i; a.serial = i; });
  molShiftIndicesAfterRemove(ins);
  molApplySupercellModel();
  if (MC.selectMode && (MC.selectedAtoms || []).length) molRedrawSelection();
  if (MC.viewer) MC.viewer.render();
  molMarkViewDirty();
  return true;
}
// 分数坐标输入 → 笛卡尔 Å 模型坐标；record 记录分数坐标，供写回与存档复用。
function molAddAtomToModel(symbol, frac, record) {
  const sym = molResolveElement(symbol) || String(symbol || "").trim();
  if (!sym || !MC.viewer || !MC.cell || !MC.sourceFrames || !MC.sourceFrames[0]) return false;
  const f = [Number(frac[0]) || 0, Number(frac[1]) || 0, Number(frac[2]) || 0];
  const cart = molFracToCart(f, MC.cell);
  if (!cart) return false;
  const base = MC.sourceFrames[0];
  const ins = molInsertIndexForElement(base, sym);
  molShiftIndicesAfterInsert(ins);
  base.splice(ins, 0, { index: ins, serial: ins, elem: sym, atom: sym,
                        x: cart.x, y: cart.y, z: cart.z, bonds: [], bondOrder: [], style: {} });
  base.forEach(function (a, i) { a.index = i; a.serial = i; });
  if (record !== false) {
    MC.atomAdditions.push({
      model: 0, index: ins, elem: sym, fx: f[0], fy: f[1], fz: f[2], coord: "frac"
    });
    molPushAtomHistory({ type: "add", atoms: [
      { model: 0, index: ins, elem: sym, fx: f[0], fy: f[1], fz: f[2] }
    ] });
  }
  molApplySupercellModel();
  if (MC.selectMode && (MC.selectedAtoms || []).length) molRedrawSelection();
  if (MC.atomPanelSel) molFillAtomPanel(true);
  MC.viewer.render();
  molMarkViewDirty();
  return true;
}
function molSelectionBox(host, d, ev) {
  let box = host.querySelector(".mol-sel-box");
  if (!box) {
    box = document.createElement("div");
    box.className = "mol-sel-box";
    const hr = host.getBoundingClientRect();
    const wr = ($("molView") && $("molView").querySelector(".mol-win")) ?
      $("molView").querySelector(".mol-win").getBoundingClientRect() : hr;
    box.style.left = (hr.left - wr.left) + "px";
    box.style.top = (hr.top - wr.top) + "px";
    host.appendChild(box);
  }
  const hr = host.getBoundingClientRect();
  box.style.width = Math.abs(ev.clientX - d.cx) + "px";
  box.style.height = Math.abs(ev.clientY - d.cy) + "px";
  box.style.left = Math.min(ev.clientX, d.cx) - hr.left + "px";
  box.style.top = Math.min(ev.clientY, d.cy) - hr.top + "px";
}
function molRemoveSelectionBox(host) {
  const box = host && host.querySelector(".mol-sel-box");
  if (box && box.parentNode) box.parentNode.removeChild(box);
}
function molBoxSelect(d, ev, opts) {
  if (!MC.viewer || !MC.viewer.modelToScreen) return;
  const x0 = Math.min(d.x, ev.pageX), x1 = Math.max(d.x, ev.pageX);
  const y0 = Math.min(d.y, ev.pageY), y1 = Math.max(d.y, ev.pageY);
  const atoms = molAllCurrentAtoms().filter(molAtomVisible);
  if (!atoms.length) return;
  let pts = [];
  try { pts = MC.viewer.modelToScreen(atoms); } catch (err) { return; }
  if (pts && !Array.isArray(pts)) pts = [pts];
  const picked = [];
  atoms.forEach(function (a, i) {
    const pt = pts[i];
    if (!pt) return;
    if (pt.x >= x0 && pt.x <= x1 && pt.y >= y0 && pt.y <= y1)
      picked.push({ model: a.model, index: a.index, elem: a.elem });
  });
  MC.selectedAtoms = picked;
  molAfterSelectionChange(ev, opts);
}
function molClickSelect(ev, opts) {
  if (!MC.viewer) return;
  let picked = null;
  try {
    const xy = MC.viewer.mouseXY(ev.pageX, ev.pageY);
    const hits = MC.viewer.targetedObjects(xy.x, xy.y, MC.viewer.clickables || []) || [];
    const target = molNearestTarget(hits, molResolveAtom);
    if (target && target.obj) picked = target.obj;
  } catch (err) { /* 拾取失败时用屏幕坐标兜底 */ }
  // 多帧轨迹里命中对象偶尔未随 setFrame 更新；按当前帧原子的屏幕坐标补一次最近点拾取。
  if (!picked && MC.viewer.modelToScreen) {
    try {
      const atoms = molAllCurrentAtoms().filter(molAtomVisible);
      let pts = MC.viewer.modelToScreen(atoms);
      if (pts && !Array.isArray(pts)) pts = [pts];
      let best = null, bestD = 14 * 14;
      atoms.forEach(function (a, i) {
        const pt = pts[i];
        if (!pt) return;
        const d = (pt.x - ev.pageX) * (pt.x - ev.pageX) + (pt.y - ev.pageY) * (pt.y - ev.pageY);
        if (d < bestD) { bestD = d; best = a; }
      });
      picked = best;
    } catch (err) { /* 兜底失败按空白处理 */ }
  }
  if (picked) {
    const additive = opts && typeof opts.additive === "boolean"
      ? opts.additive : !!(ev && (ev.ctrlKey || ev.metaKey));
    molSelectAtom({ model: picked.model, index: picked.index, elem: picked.elem },
      additive, ev, opts);
    return;
  }
  MC.selectedAtoms = [];
  molAfterSelectionChange(ev, opts);
}


function molAngleDeg(a, b, c) {
  const ba = molWrapVec(molVecSub(a, b));
  const bc = molWrapVec(molVecSub(c, b));
  const la = molVecLen(ba), lc = molVecLen(bc);
  if (la < 1e-9 || lc < 1e-9) return 0;
  const dot = (ba.x*bc.x + ba.y*bc.y + ba.z*bc.z) / (la*lc);
  return Math.acos(Math.max(-1, Math.min(1, dot))) * 180 / Math.PI;
}

function molSelector(atom) {
  const sel = { index: atom.index };
  if (atom.model !== undefined) sel.model = atom.model;
  if (MC.frames > 0) sel.frame = MC.index;
  return sel;
}
function molSelectorAllFrames(atom) {
  const sel = { index: atom.index };
  if (atom.model !== undefined) sel.model = atom.model;
  return sel;  // 不传 frame：3Dmol 的 setStyle 会应用到当前帧及 frames 中的同一原子。
}

function molClearGraphics() {
  if (MC.viewer) {
    for (let i = MC.measureLabels.length-1; i >= 0; i--) {
      try { MC.viewer.removeLabel(MC.measureLabels[i]); } catch (err) { /* 忽略 */ }
    }
    for (let i = MC.measureShapes.length-1; i >= 0; i--) {
      try { MC.viewer.removeShape(MC.measureShapes[i]); } catch (err) { /* 忽略 */ }
    }
  }
  MC.measureLabels = [];
  MC.measureShapes = [];
}

function molHasPicks() {
  // 清除按钮只看是否已有标注/选中项，与测量模式开关无关。
  return !!((MC.pickAtoms || []).length || (MC.pickBonds || []).length);
}

// 测量模式开关：只控制左键是否能新增测量拾取；关闭时保留已显示的标注与选中项。
function molSyncMeasureButton() {
  const btn = $("molMeasureToggle");
  if (!btn) return;
  MC.measureMode = !!MC.measureMode;
  const on = MC.measureMode;
  btn.classList.toggle("active", on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  const label = on ? "测量模式（已开启）" : "测量模式";
  btn.title = tx(label);
  btn.setAttribute("aria-label", btn.title);
}

function molClearMeasure(skipRender) {
  molClearGraphics();
  MC.pickAtoms = [];
  MC.pickBonds = [];
  molSyncClearButton();
  if (!skipRender && MC.viewer) MC.viewer.render();
  if (!skipRender) molMarkViewDirty();
}

function molAddPickLabel(pos, text) {
  if (!MC.viewer) return;
  try {
    const label = MC.viewer.addLabel(text, {
      position: pos, inFront: true, showBackground: false,
      fontColor: molMeasureStyle.fontColor, fontSize: molMeasureStyle.fontSize,
      font: molMeasureStyle.fontFamily || MOL_FONT_FAMILIES[0].value,
      borderThickness: 0
    });
    if (label) MC.measureLabels.push(label);
  } catch (err) { /* 忽略标签失败 */ }
}

function molAddPickLine(start, end) {
  if (!MC.viewer) return;
  try {
    const shape = MC.viewer.addCylinder({
      start: start, end: end, radius: molMeasureStyle.lineRadius,
      color: molMeasureStyle.lineColor,
      dashed: molMeasureStyle.lineDashed,
      dashLength: molMeasureStyle.lineDashLength, gapLength: molMeasureStyle.lineGapLength
    });
    if (shape) MC.measureShapes.push(shape);
  } catch (err) { /* 忽略连线失败 */ }
}

// 测量样式改动后即时重绘（保留选中原子，不清空）。
function molRedrawMeasure() {
  molDrawMeasure();
}

function molSyncClearButton() {
  const clear = $("molPickClear");
  if (clear) clear.disabled = !molHasPicks();
}

function molDrawMeasure() {
  molClearGraphics();
  const atoms = MC.pickAtoms || [];
  const bonds = MC.pickBonds || [];
  // 测量模式只限制新的左键拾取；已有标注在关闭模式后仍继续显示与重绘。
  if (!MC.viewer || (!atoms.length && !bonds.length)) { molSyncClearButton(); return; }
  // 元素名标在原子上方；选中的原子持续累加，直到点“清除选中”才全部消失。
  atoms.forEach(function (atom) {
    const p = molAtomPos(atom);
    const elem = String((atom && (atom.elem || atom.atom)) || "");
    molAddPickLabel({ x: p.x, y: p.y + 0.18, z: p.z }, elem);
  });
  // 相邻选中原子之间画细虚线并标距离。
  for (let i = 0; i + 1 < atoms.length; i++) {
    const start = molAtomPos(atoms[i]);
    const vec = molWrapVec(molVecSub(atoms[i+1], atoms[i]));
    const end = molVecAdd(start, vec);
    molAddPickLine(start, end);
    molAddPickLabel(molVecMid(start, end), molVecLen(vec).toFixed(3) + " Å");
  }
  // 每三个相邻选中原子以中间原子为顶点标角度。
  for (let i = 0; i + 2 < atoms.length; i++) {
    const b = molAtomPos(atoms[i+1]);
    const ba = molWrapVec(molVecSub(atoms[i], atoms[i+1]));
    const bc = molWrapVec(molVecSub(atoms[i+2], atoms[i+1]));
    const la = molVecLen(ba), lc = molVecLen(bc);
    const bis = { x: ba.x/la + bc.x/lc, y: ba.y/la + bc.y/lc, z: ba.z/la + bc.z/lc };
    const lb = molVecLen(bis);
    if (lb < 1e-6) { bis.x = 0; bis.y = 1; bis.z = 0; }
    else { bis.x /= lb; bis.y /= lb; bis.z /= lb; }
    molAddPickLabel(molVecAdd(b, { x: bis.x*0.55, y: bis.y*0.55, z: bis.z*0.55 }),
      molAngleDeg(atoms[i], atoms[i+1], atoms[i+2]).toFixed(1) + "°");
  }
  // 左键选中的键：每条都标出键长，可同时显示多条；重复点同一键才取消该条。
  // 用 model/index 取当前帧原子，轨迹切帧后 molRefreshPicksForFrame 重绘时长度会跟着更新。
  bonds.forEach(function (b) {
    const low = molFindAtomByIndex(b.model, b.a);
    const other = molFindAtomByIndex(b.model, b.b);
    if (low && other) {
      const start = molAtomPos(low);
      const vec = molWrapVec(molVecSub(other, low));
      const end = molVecAdd(start, vec);
      molAddPickLine(start, end);
      molAddPickLabel(molVecMid(start, end), molVecLen(vec).toFixed(3) + " Å");
    }
  });
  molSyncClearButton();
  MC.viewer.render();
}

function molColorHex(atom) {
  const sphere = atom && atom.style && atom.style.sphere;
  const color = sphere && sphere.color;
  if (typeof color === "number") return "#" + ("000000" + color.toString(16)).slice(-6);
  if (typeof color === "string" && color.charAt(0) === "#") return color.slice(0, 7);
  return molDefaultColor(atom && atom.elem);
}

function molClosePickPops() {
  const panel = $("molPickPanel");
  if (!panel) return;
  panel.querySelectorAll(".mol-pick-pop.show").forEach(function (p) { p.classList.remove("show"); });
  panel.querySelectorAll(".mol-pick-num-btn.active").forEach(function (b) { b.classList.remove("active"); });
}

// 3Dmol 的 targetedObjects 返回的是射线命中对象，真正的原子在 .clickable 上；
// 回调与测试夹具里传入的则直接是原子本身，这里统一取出可用原子。
function molResolveAtom(hit) {
  if (!hit) return null;
  const inner = hit.clickable;
  if (inner && typeof inner === "object" && typeof inner.index === "number") return inner;
  return typeof hit.index === "number" ? hit : null;
}

function molHidePickPanel() {
  const panel = $("molPickPanel");
  if (panel) panel.classList.add("hidden");
  document.querySelectorAll(".mol-color-panel").forEach(function (p) { p.classList.add("hidden"); });
  molClosePickPops();
  MC.styleAtom = null;
  MC.styleBond = null;
  MC.pickMode = "atom";
}

function molNumValue(id, fallback, lo, hi) {
  const el = $(id);
  const v = Number(el && el.value);
  return isFinite(v) ? Math.min(hi, Math.max(lo, v)) : fallback;
}

function molSyncNumButton(id, value) {
  const range = $(id + "Range");
  if (range) range.value = String(value);
}

function molSetNumInputs(id, value) {
  const num = $(id);
  if (num) num.value = String(value);
  molSyncNumButton(id, value);
}

function molToggleNumPop(id, btn) {
  const pop = $(id + "Pop");
  const wasOpen = !!pop && pop.classList.contains("show");
  molClosePickPops();
  if (pop && !wasOpen) {
    pop.classList.add("show");
    if (btn) btn.classList.add("active");
  }
}

function molPositionPickPanel(ev, panel) {
  const win = $("molView") && $("molView").querySelector(".mol-win");
  if (!win) return;
  const rect = win.getBoundingClientRect();
  const cx = ev && typeof ev.clientX === "number" ? ev.clientX : rect.left + rect.width/2;
  const cy = ev && typeof ev.clientY === "number" ? ev.clientY : rect.top + rect.height/2;
  const w = panel.offsetWidth || 248;
  const h = panel.offsetHeight || 210;
  panel.style.left = Math.max(8, Math.min(cx - rect.left + 8, rect.width - w - 8)) + "px";
  // 顶部预留 132px，保证第一行数字框的小三角滑杆能在按钮上方完整弹出。
  panel.style.top = Math.max(132, Math.min(cy - rect.top + 8, rect.height - h - 8)) + "px";
}

// 颜色控件增强：在原色块下方加一排常用色板，色块数量随弹窗宽度调整。
const MOL_COMMON_COLORS = [
  "#e0553d", "#f2a33c", "#f2d649", "#17a06b", "#00a1d6", "#3b57d1",
  "#8a45b5", "#e45a9a", "#8b5a2b", "#9aa5b1", "#000000", "#ffffff"
];
const MOL_SWATCH_SIZE = 15;
const MOL_SWATCH_GAP = 4;
function molLayoutColorSwatches() {
  const panel = $("molPickPanel");
  if (!panel) return;
  const inner = Math.max(0, (panel.clientWidth || 248) - 24);
  const count = Math.max(2, Math.min(MOL_COMMON_COLORS.length,
    Math.floor((inner + MOL_SWATCH_GAP) / (MOL_SWATCH_SIZE + MOL_SWATCH_GAP))));
  const last = MOL_COMMON_COLORS.length - 1;
  panel.querySelectorAll(".mol-color-swatches").forEach(function (box) {
    const all = Array.from(box.querySelectorAll(".mol-color-swatch"));
    const visible = [];
    for (let i = 0; i < count; i++) visible.push(all[Math.round(i * last / Math.max(1, count - 1))]);
    all.forEach(function (b) { b.classList.add("hidden"); });
    visible.forEach(function (b) { if (b) b.classList.remove("hidden"); });
  });
}
// 颜色格式互转：自定义取色面板用 RGB / HSL / HEX 三种紧凑输入。
function molHexToRgb(hex) {
  const h = molHexColor(hex).replace("#", "");
  return {
    r: parseInt(h.slice(0, 2), 16) || 0,
    g: parseInt(h.slice(2, 4), 16) || 0,
    b: parseInt(h.slice(4, 6), 16) || 0
  };
}
function molRgbToHex(r, g, b) {
  const part = function (v) {
    return ("0" + Math.max(0, Math.min(255, Math.round(Number(v) || 0))).toString(16)).slice(-2);
  };
  return "#" + part(r) + part(g) + part(b);
}
function molRgbToHsl(r, g, b) {
  r = (Number(r) || 0) / 255; g = (Number(g) || 0) / 255; b = (Number(b) || 0) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0, s = 0;
  const l = (mx + mn) / 2;
  if (d > 0) {
    s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    if (mx === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  // 内部保留小数精度（显示时再取整），避免低亮度颜色在 RGB→HSL→RGB 往返时明显偏色。
  return { h: h, s: s * 100, l: l * 100 };
}
function molHslToRgb(h, s, l) {
  h = (((Number(h) || 0) % 360) + 360) % 360 / 360;
  s = Math.max(0, Math.min(100, Number(s) || 0)) / 100;
  l = Math.max(0, Math.min(100, Number(l) || 0)) / 100;
  if (!s) { const v = Math.round(l * 255); return { r: v, g: v, b: v }; }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = function (t) {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return {
    r: Math.round(channel(h + 1 / 3) * 255),
    g: Math.round(channel(h) * 255),
    b: Math.round(channel(h - 1 / 3) * 255)
  };
}

// 用页面内自定义取色面板替换浏览器原生取色器：
// 保留隐藏的 input[type=color] 作为颜色值载体，外部读写 .value 的方式完全不变；
// 点击色块按钮打开面板，“更多设置”里用下拉切换 RGB / HSL / HEX，输入框仅比字符略高。
function molAttachColorEditor(input, apply) {
  if (!input || input.dataset.colorEditor) return;
  input.dataset.colorEditor = "1";
  const row = input.closest(".mol-pick-row");
  if (row) {
    row.classList.add("mol-color-row");
    const main = document.createElement("div");
    main.className = "mol-color-main";
    while (row.firstChild) main.appendChild(row.firstChild);
    row.appendChild(main);
  }

  const open = document.createElement("button");
  open.type = "button";
  open.className = "mol-color-open";
  open.title = tx("选择颜色");
  open.setAttribute("aria-label", tx("选择颜色"));
  if (input.parentNode) input.parentNode.insertBefore(open, input);
  input.type = "hidden";

  const extra = document.createElement("div");
  extra.className = "mol-color-extra";
  const swatchBox = document.createElement("div");
  swatchBox.className = "mol-color-swatches";
  const swatches = MOL_COMMON_COLORS.map(function (hex) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mol-color-swatch";
    b.style.background = hex;
    b.title = hex.toUpperCase();
    b.setAttribute("aria-label", hex.toUpperCase());
    b.onclick = function () {
      const h = molHexColor(hex);
      input.value = h;
      apply(h);
      sync(h);
    };
    swatchBox.appendChild(b);
    return b;
  });
  extra.appendChild(swatchBox);
  if (row) row.appendChild(extra);

  const panel = document.createElement("div");
  panel.className = "mol-color-panel hidden";

  // 主体：左侧 RGB 色环（按角度调色相），右侧 RGB/HSL/HEX 下拉与数值输入框。
  const body = document.createElement("div");
  body.className = "mol-color-body";
  const wheel = document.createElement("div");
  wheel.className = "mol-color-wheel";
  wheel.title = tx("色相环");
  wheel.setAttribute("role", "slider");
  wheel.setAttribute("aria-label", tx("色相环"));
  wheel.setAttribute("aria-valuemin", "0");
  wheel.setAttribute("aria-valuemax", "360");
  const wheelDot = document.createElement("span");
  wheelDot.className = "mol-color-wheel-dot";
  wheel.appendChild(wheelDot);

  // 屏幕取色按钮：吸管图标，放在面板左上角；直接挂在 body 上，避免色环的指针捕获吞掉 click。
  const picker = document.createElement("button");
  picker.type = "button";
  picker.className = "mol-color-picker";
  picker.innerHTML = "<svg viewBox='0 0 24 24' fill='currentColor' aria-hidden='true'><path d='M20.71 5.63l-2.34-2.34a1 1 0 0 0-1.41 0l-3.12 3.12-1.93-1.91-1.41 1.41 1.42 1.42L3 16.25V21h4.75l8.92-8.92 1.42 1.42 1.41-1.41-1.92-1.93 3.12-3.12a1 1 0 0 0 0-1.41zM6.92 19L5 17.08l8.06-8.06 1.92 1.92L6.92 19z'/></svg>";
  picker.title = tx("屏幕取色");
  picker.setAttribute("aria-label", tx("屏幕取色"));
  picker.addEventListener("pointerdown", function (ev) { ev.stopPropagation(); });
  picker.onclick = function (ev) {
    ev.stopPropagation();
    const EyeDropperCtor = typeof window !== "undefined" ? window.EyeDropper : null;
    if (typeof EyeDropperCtor === "function") {
      const ed = new EyeDropperCtor();
      ed.open().then(function (res) {
        if (!res || !res.sRGBHex) return;
        const h = molHexColor(res.sRGBHex);
        input.value = h;
        apply(h);
        sync(h);
      }).catch(function () { /* 用户取消取色，保持原色 */ });
      return;
    }
    // 浏览器不支持 EyeDropper 时回退到原生取色器（同样带屏幕吸管入口）。
    const native = document.createElement("input");
    native.type = "color";
    native.value = molHexColor(input.value);
    native.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
    const cleanup = function () { if (native.parentNode) native.parentNode.removeChild(native); };
    native.addEventListener("change", function () {
      const h = molHexColor(this.value);
      input.value = h;
      apply(h);
      sync(h);
      cleanup();
    });
    native.addEventListener("blur", cleanup);
    if (document.body) document.body.appendChild(native);
    native.click();
  };
  body.appendChild(picker);
  body.appendChild(wheel);

  const fields = document.createElement("div");
  fields.className = "mol-color-fields";
  const modeSel = document.createElement("select");
  modeSel.setAttribute("aria-label", tx("颜色模式"));
  [{ key: "rgb", label: "RGB" }, { key: "hsl", label: "HSL" }, { key: "hex", label: "HEX" }].forEach(function (o) {
    const opt = document.createElement("option");
    opt.value = o.key;
    opt.textContent = o.label;
    modeSel.appendChild(opt);
  });
  fields.appendChild(modeSel);
  const values = document.createElement("div");
  values.className = "mol-color-values";
  fields.appendChild(values);
  body.appendChild(fields);
  panel.appendChild(body);
  if (row) row.appendChild(panel);

  let mode = "rgb";
  let inputs = [];
  let hue = 0;

  function refreshFields(hex) {
    const h = molHexColor(hex);
    if (mode === "rgb") {
      const rgb = molHexToRgb(h);
      ["r", "g", "b"].forEach(function (k, i) {
        if (inputs[i] && document.activeElement !== inputs[i]) inputs[i].value = String(rgb[k]);
      });
    } else if (mode === "hsl") {
      const rgb = molHexToRgb(h);
      const hsl = molRgbToHsl(rgb.r, rgb.g, rgb.b);
      ["h", "s", "l"].forEach(function (k, i) {
        if (inputs[i] && document.activeElement !== inputs[i]) inputs[i].value = String(Math.round(hsl[k]));
      });
    } else if (inputs[0] && document.activeElement !== inputs[0]) {
      inputs[0].value = h;
    }
  }
  function buildFields(hex) {
    while (values.firstChild) values.removeChild(values.firstChild);
    inputs = [];
    const rgb = molHexToRgb(hex);
    const hsl = molRgbToHsl(rgb.r, rgb.g, rgb.b);
    const defs = mode === "rgb"
      ? [{ k: "r", v: rgb.r, min: 0, max: 255, step: 1 },
         { k: "g", v: rgb.g, min: 0, max: 255, step: 1 },
         { k: "b", v: rgb.b, min: 0, max: 255, step: 1 }]
        : mode === "hsl"
          ? [{ k: "h", v: Math.round(hsl.h), min: 0, max: 360, step: 1 },
             { k: "s", v: Math.round(hsl.s), min: 0, max: 100, step: 1 },
             { k: "l", v: Math.round(hsl.l), min: 0, max: 100, step: 1 }]
        : [{ k: "hex", v: molHexColor(hex) }];
    defs.forEach(function (d) {
      const row = document.createElement("div");
      row.className = "mol-color-value-row";
      const label = document.createElement("span");
      label.className = "mol-color-value-label";
      label.textContent = d.k.toUpperCase() + ":";
      const el = document.createElement("input");
      el.type = d.k === "hex" ? "text" : "number";
      if (d.min !== undefined) { el.min = String(d.min); el.max = String(d.max); el.step = String(d.step); }
      if (d.k === "hex") el.className = "mol-color-hex";
      el.value = String(d.v);
      el.setAttribute("aria-label", d.k.toUpperCase());
      el.oninput = function () {
        let next = input.value;
        if (mode === "rgb") {
          const cur = molHexToRgb(input.value);
          cur[d.k] = Math.max(0, Math.min(255, Number(this.value) || 0));
          next = molRgbToHex(cur.r, cur.g, cur.b);
        } else if (mode === "hsl") {
          const rgbNow = molHexToRgb(input.value);
          const cur = molRgbToHsl(rgbNow.r, rgbNow.g, rgbNow.b);
          cur[d.k] = Number(this.value) || 0;
          const out = molHslToRgb(cur.h, cur.s, cur.l);
          next = molRgbToHex(out.r, out.g, out.b);
        } else {
          const raw = String(this.value).trim();
          const candidate = raw.charAt(0) === "#" ? raw : "#" + raw;
          if (!/^#[0-9a-f]{6}$/i.test(candidate)) return;
          next = molHexColor(candidate);
        }
        input.value = next;
        apply(next);
        sync(next);
      };
      row.appendChild(label);
      row.appendChild(el);
      values.appendChild(row);
      inputs.push(el);
    });
  }
  // 色环指示点跟随当前色相；hue 为数值（不再有滑杆 DOM），360 与 0 都是红色。
  function syncHueVisual() {
    const hv = Math.round(hue) || 0;
    wheel.setAttribute("aria-valuenow", String(hv));
    const rad = (hv - 90) * Math.PI / 180;
    const rect = wheel.getBoundingClientRect ? wheel.getBoundingClientRect() : null;
    const size = (rect && rect.width) || wheel.clientWidth || 64;
    const r = size * 0.36;  // 环带中点：外半径 0.5、内半径 0.22（inset 28%）
    wheelDot.style.transform = "translate(" + (r * Math.cos(rad)).toFixed(2) + "px," + (r * Math.sin(rad)).toFixed(2) + "px)";
  }
  function sync(hex, keepHue) {
    const h = molHexColor(hex);
    swatches.forEach(function (b, i) {
      b.classList.toggle("active", MOL_COMMON_COLORS[i].toLowerCase() === h.toLowerCase());
    });
    open.style.background = h;
    open.disabled = !!input.disabled;
    const rgb = molHexToRgb(h);
    const hsl = molRgbToHsl(rgb.r, rgb.g, rgb.b);
    if (!keepHue) hue = Math.round(hsl.h);
    syncHueVisual();
    refreshFields(h);
  }
  function setMode(next) {
    mode = next;
    modeSel.value = next;
    fields.classList.toggle("mol-color-hex-mode", next === "hex");
    buildFields(input.value);
  }
  modeSel.onchange = function () { setMode(this.value); };
  function applyHue(deg) {
    hue = deg;
    const rgb = molHexToRgb(input.value);
    const hsl = molRgbToHsl(rgb.r, rgb.g, rgb.b);
    hsl.h = deg;
    const out = molHslToRgb(hsl.h, hsl.s, hsl.l);
    const next = molRgbToHex(out.r, out.g, out.b);
    input.value = next;
    apply(next);
    sync(next, true);
  }
  // 色环：指针在环上的角度即色相（12 点方向为 0°，顺时针递增），点击与拖动均生效。
  function wheelHueAt(ev) {
    const rect = wheel.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    let deg = Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI + 90;
    deg = ((deg % 360) + 360) % 360;
    const val = Math.round(deg) % 360;
    applyHue(val);
  }
  wheel.addEventListener("pointerdown", function (ev) {
    ev.preventDefault(); ev.stopPropagation();
    if (wheel.setPointerCapture) { try { wheel.setPointerCapture(ev.pointerId); } catch (e) {} }
    wheelHueAt(ev);
  });
  wheel.addEventListener("pointermove", function (ev) {
    if (!(ev.buttons & 1)) return;
    ev.preventDefault(); ev.stopPropagation();
    wheelHueAt(ev);
  });
  wheel.addEventListener("pointerup", function (ev) { ev.stopPropagation(); });
  open.onclick = function (ev) {
    ev.stopPropagation();
    if (open.disabled) return;
    const wasOpen = !panel.classList.contains("hidden");
    document.querySelectorAll(".mol-color-panel").forEach(function (p) { p.classList.add("hidden"); });
    if (!wasOpen) {
      setMode(modeSel.value);
      panel.classList.remove("hidden");
    }
  };
  input._molColorSync = sync;
  buildFields(input.value);
  sync(input.value);
  molLayoutColorSwatches();
}

// 虚线段长/间隙只在“晶格样式 = 虚线”时显示。
function molSyncDashRow() {
  const row = $("molStCellDashRow");
  if (row) row.classList.toggle("hidden", !molCellStyle.visible || !molCellStyle.dashed);
}

// 晶格内联行：repeat=范围下一行 A/B/C；dash=虚线段长与间隙同一行。
function molMakeInlineNumberRow(fields, kind) {
  const wrap = document.createElement("div");
  wrap.className = kind === "dash" ? "mol-cell-dash" : "mol-cell-repeat";
  if (kind === "dash") wrap.id = "molStCellDashRow";
  if (kind !== "dash") {
    const title = document.createElement("div");
    title.className = "mol-cell-repeat-title";
    title.textContent = tx("范围");
    wrap.appendChild(title);
  }
  const row = document.createElement("div");
  row.className = "mol-pick-row mol-cell-repeat-row";
  fields.forEach(function (f, i) {
    const item = document.createElement("label");
    item.className = "mol-cell-repeat-item";
    item.textContent = (kind === "dash"
      ? [tx("虚线段长"), tx("间隙")][i] : "ABC".charAt(i)) + " ";
    const input = document.createElement("input");
    input.type = "number";
    input.id = f.id;
    input.min = String(f.min);
    input.max = String(f.max);
    input.step = String(f.step);
    input.value = String(f.get());
    input.setAttribute("aria-label", tx(f.label));
    input.oninput = function () { molApplyStyleNumber(f, this.value, false); };
    item.appendChild(input);
    row.appendChild(item);
  });
  wrap.appendChild(row);
  if (kind === "dash") molSyncDashRow();
  return wrap;
}

// 按字段类型生成一行控件；数值框右侧的小三角按钮上方弹出滑杆。
function molMakeStyleRow(f) {
  const row = document.createElement("div");
  row.className = "mol-pick-row";
  const label = document.createElement("span");
  label.textContent = tx(f.label);
  row.appendChild(label);
  const input = document.createElement("input");
  input.id = f.id;
  input.setAttribute("aria-label", tx(f.label));
  if (f.type === "bool") {
    input.type = "checkbox";
    input.checked = !!f.get();
    input.onchange = function () { f.set(this.checked); molMarkViewDirty(); };
    row.appendChild(input);
    return row;
  }
  if (f.type === "color") {
    input.type = "color";
    input.value = molHexColor(f.get());
    input.oninput = function () { f.set(this.value); molMarkViewDirty(); };
    row.appendChild(input);
    molAttachColorEditor(input, function (v) { f.set(v); molMarkViewDirty(); });
    return row;
  }
  if (f.type === "select") {
    const sel = document.createElement("select");
    sel.id = f.id;
    sel.setAttribute("aria-label", tx(f.label));
    (f.options || []).forEach(function (o) {
      const opt = document.createElement("option");
      opt.value = o.value !== undefined ? o.value : o.key;
      opt.textContent = tx(o.label);
      sel.appendChild(opt);
    });
    sel.value = String(f.get());
    sel.onchange = function () { f.set(this.value); molMarkViewDirty(); };
    row.appendChild(sel);
    return row;
  }
  if (f.type === "font") {
    const sel = document.createElement("select");
    sel.id = f.id;
    sel.setAttribute("aria-label", tx(f.label));
    (f.options || MOL_LABEL_FONTS).forEach(function (o) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = tx(o.label);
      sel.appendChild(opt);
    });
    sel.value = f.get();
    sel.onchange = function () { f.set(this.value); molMarkViewDirty(); };
    row.appendChild(sel);
    return row;
  }
  input.type = "number";
  input.min = String(f.min);
  input.max = String(f.max);
  input.step = String(f.step);
  input.value = String(f.get());
  input.oninput = function () { molApplyStyleNumber(f, this.value, false); };
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "mol-pick-num-btn";
  btn.id = f.id + "Btn";
  btn.textContent = "▼";
  btn.title = tx("调节") + tx(f.label);
  btn.setAttribute("aria-haspopup", "true");
  btn.onclick = function () { molToggleNumPop(f.id, this); };
  const pop = document.createElement("div");
  pop.className = "mol-pick-pop";
  pop.id = f.id + "Pop";
  const range = document.createElement("input");
  range.type = "range";
  range.id = f.id + "Range";
  range.min = String(f.min);
  range.max = String(f.max);
  range.step = String(f.step);
  range.value = String(f.get());
  range.setAttribute("aria-label", tx(f.label) + tx("滑杆"));
  range.oninput = function () { molApplyStyleNumber(f, this.value, true); };
  pop.appendChild(range);
  row.appendChild(input);
  row.appendChild(btn);
  row.appendChild(pop);
  return row;
}

function molApplyStyleNumber(f, raw, fromRange) {
  let v = Number(raw);
  if (!isFinite(v)) v = f.get();
  v = Math.min(f.max, Math.max(f.min, v));
  const num = $(f.id);
  if (fromRange && num) num.value = String(v);
  molSyncNumButton(f.id, v);
  f.set(v);
  molMarkViewDirty();
}

function molBuildStylePanel(mode) {
  mode = mode === "axis" ? "axis" : (mode === "iso" ? "iso" : "global");
  const box = $("molPickStyleBox");
  if (!box || box.dataset.mode === mode) return;
  box.dataset.mode = mode;
  box.innerHTML = "";
  // 空白右键：外观 + 键 + 晶格 + 测量；坐标轴区域右键：坐标轴 + 轴颜色；
  // 等值面右键/长按：透明度 + 正值（输入框/滑杆）+ 正值颜色 + 负值（输入框/滑杆）+ 负值颜色。
  const groups = MOL_STYLE_GROUPS.filter(function (g) {
    if (mode === "axis") return g.key === "axis" || g.key === "axisColor";
    if (mode === "iso") return g.key === "iso";
    return g.key === "bond" || g.key === "bonds" || g.key === "cell" || g.key === "measure";
  });
  // 只有一个分组时标签按钮没有切换作用（如“等值面设置”），直接不渲染整条标签栏。
  if (groups.length > 1) {
    const tabs = document.createElement("div");
    tabs.className = "mol-pick-tabs";
    groups.forEach(function (g, gi) {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.textContent = tx(g.label);
      if (gi === 0) tab.classList.add("active");
      tab.onclick = function () {
        tabs.querySelectorAll("button").forEach(function (b) { b.classList.remove("active"); });
        tab.classList.add("active");
        groups.forEach(function (gg) {
          const el = $("molPickGroup-" + gg.key);
          if (el) el.classList.toggle("hidden", gg.key !== g.key);
        });
      };
      tabs.appendChild(tab);
    });
    box.appendChild(tabs);
  }
  groups.forEach(function (g, gi) {
    const group = document.createElement("div");
    group.className = "mol-pick-group" + (gi ? " hidden" : "");
    group.id = "molPickGroup-" + g.key;
    // 按字段声明顺序插入控件；每组内联行在该组第一个 inline 字段的位置插入一次。
    const doneInline = {};
    g.fields.forEach(function (f) {
      if (f.inline) {
        if (!doneInline[f.inline]) {
          doneInline[f.inline] = true;
          group.appendChild(molMakeInlineNumberRow(g.fields.filter(function (x) {
            return x.inline === f.inline;
          }), f.inline));
        }
        return;
      }
      group.appendChild(molMakeStyleRow(f));
    });
    box.appendChild(group);
  });
  molSyncDashRow();
}

// 密度切换会改变正/负等值面的量程；弹窗复用同一 DOM，需同步刷新 number/range 的 min/max/step。
// 放在 molSyncStyleFields 开头，保证每次打开“等值面设置”时量程都是当前密度数据的范围。
function molSyncIsoRanges() {
  const iso = MOL_STYLE_GROUPS.find(function (g) { return g.key === "iso"; });
  if (!iso) return;
  iso.fields.forEach(function (f) {
    if (f.min === undefined) return;
    ["", "Range"].forEach(function (suffix) {
      const el = $(f.id + suffix);
      if (!el) return;
      el.min = String(f.min);
      el.max = String(f.max);
      el.step = String(f.step);
    });
  });
}
function molSyncStyleFields() {
  molSyncIsoRanges();
  MOL_STYLE_FIELDS.forEach(function (f) {
    const el = $(f.id);
    if (!el) return;
    const v = f.get();
    if (f.type === "bool") el.checked = !!v;
    else if (f.type === "color") {
      el.value = molHexColor(v);
      if (f.key === "BondColor") {
        el.disabled = !molBondColor;
        const row = el.closest(".mol-pick-row");
        if (row) row.classList.toggle("hidden", !molBondColor);
        const sw = row && row.querySelector(".mol-color-swatches");
        if (sw) sw.classList.toggle("hidden", !molBondColor);
      }
      if (el._molColorSync) el._molColorSync(el.value);
    }
    else if (f.type === "select" || f.type === "font") el.value = String(v);
    else molSetNumInputs(f.id, v);
  });
  molSyncDashRow();
}

function molOpenPickPanel(atom, ev) {
  atom = molResolveAtom(atom);
  if (!atom) { molOpenStylePanel(ev); return; }
  MC.styleAtom = atom;
  MC.styleBond = null;
  MC.pickMode = "atom";
  const panel = $("molPickPanel");
  if (!panel) return;
  const title = $("molPickTitle");
  if (title) title.textContent = tx("原子样式");
  panel.setAttribute("aria-label", tx("原子样式"));
  const colorRow = $("molPickColorRow"), sizeRow = $("molPickSizeRow"), styleBox = $("molPickStyleBox");
  if (colorRow) colorRow.classList.remove("hidden");
  if (sizeRow) sizeRow.classList.remove("hidden");
  if (styleBox) styleBox.classList.add("hidden");
  const color = $("molPickColor");
  const sphere = atom && atom.style && atom.style.sphere;
  const sizeValue = sphere && typeof sphere.radius === "number" ? sphere.radius : (sphere && sphere.scale);
  if (color) { color.value = molColorHex(atom); if (color._molColorSync) color._molColorSync(color.value); }
  molSetNumInputs("molPickSize",
    Math.min(0.8, Math.max(0.05, Number(sizeValue) || molDefaultRadius(atom && atom.elem))));
  panel.classList.remove("hidden");
  molPositionPickPanel(ev, panel);
  molLayoutColorSwatches();
}

function molOpenStylePanel(ev, mode) {
  MC.styleAtom = null;
  MC.styleBond = null;
  MC.pickMode = mode === "iso" ? "iso" : "global";
  const isAxis = mode === "axis";
  const isIso = mode === "iso";
  const panelTitle = isAxis ? "坐标轴设置" : (isIso ? "等值面设置" : "样式设置");
  const panel = $("molPickPanel");
  if (!panel) return;
  const title = $("molPickTitle");
  if (title) title.textContent = tx(panelTitle);
  panel.setAttribute("aria-label", tx(panelTitle));
  const colorRow = $("molPickColorRow"), sizeRow = $("molPickSizeRow"), styleBox = $("molPickStyleBox");
  if (colorRow) colorRow.classList.add("hidden");
  if (sizeRow) sizeRow.classList.add("hidden");
  if (styleBox) styleBox.classList.remove("hidden");
  molBuildStylePanel(isAxis ? "axis" : (isIso ? "iso" : "global"));
  molSyncStyleFields();
  panel.classList.remove("hidden");
  molPositionPickPanel(ev, panel);
  molLayoutColorSwatches();
}

function molApplyAtomStyle() {
  const atom = molResolveAtom(MC.styleAtom);
  if (!atom || !MC.viewer) return;
  const colorEl = $("molPickColor");
  const radius = molNumValue("molPickSize", molDefaultRadius(atom.elem), 0.05, 0.8);
  const color = colorEl ? colorEl.value : molDefaultColor(atom.elem);
  molSyncNumButton("molPickSize", radius);
  MC.viewer.addStyle(molSelectorAllFrames(atom), { sphere: { color: color, radius: radius } });
  molRedrawSupercell();
  MC.viewer.render();
  MC.atomStyles[molAtomKey(atom)] = { model: atom.model, index: atom.index, elem: atom.elem, color: color, radius: radius };
  molMarkViewDirty();
}

function molResetAtomStyle() {
  const atom = molResolveAtom(MC.styleAtom);
  if (!atom || !MC.viewer) return;
  const color = molDefaultColor(atom.elem);
  const radius = molDefaultRadius(atom.elem);
  MC.viewer.addStyle(molSelectorAllFrames(atom), {
    sphere: { color: color, radius: radius }
  });
  const colorEl = $("molPickColor");
  if (colorEl) { colorEl.value = color; if (colorEl._molColorSync) colorEl._molColorSync(color); }
  molSetNumInputs("molPickSize", radius);
  delete MC.atomStyles[molAtomKey(atom)];
  molRedrawSupercell();
  MC.viewer.render();
  molMarkViewDirty();
}

// 键样式：全局“键”设置优先；改动全局键粗/颜色/样式会清掉逐键覆盖。
// 3Dmol 在 addStyle 时会清空 molObj，仅改 atom.bondStyles 后 render 不会重建键几何，
// 所以每次样式变化都重新 addStyle 一次，确保实时生效。
function molApplyBondRadius() {
  molApplyBondStyles();
}
// 全局键设置优先：改动“键”里的键粗/颜色/样式时清掉所有逐键覆盖。
// 拾取圆柱半径也随全局键粗重建，之后全局设置自然作用于每条键。
function molClearBondOverrides() {
  if (!MC.bondStyles || !Object.keys(MC.bondStyles).length) return;
  MC.bondStyles = {};
  molRebuildBondPickShapes();
}

// 「外观」的显示开关：用 addStyle 给全部原子叠加 hidden，3Dmol 的 setStyle
// 用 Object.assign 合并，单独设置过的原子颜色/半径会被保留，只切换 hidden 位。
function molApplyVisibility() {
  if (!MC.viewer) return;
  MC.viewer.addStyle({}, {
    sphere: { hidden: !molAtomsVisible },
    stick: { hidden: !molBondsVisible }
  });
  molRedrawSupercell();
  MC.viewer.render();
}

// ---- 单键样式：右键键拾取 + 键粗/颜色/实线虚线 ----
function molBondKey(bond) {
  return String(bond && bond.model) + ":" + String(bond && bond.a) + ":" + String(bond && bond.b);
}
function molViewerModels() {
  if (!MC.viewer) return [];
  if (Array.isArray(MC.viewer.models)) return MC.viewer.models;
  if (MC.viewer.getModels) {
    try { const list = MC.viewer.getModels(); if (Array.isArray(list)) return list; } catch (err) { /* 忽略 */ }
  }
  const m = MC.viewer.models;
  if (m && Array.isArray(m.atoms)) return [m];
  if (m && Array.isArray(m.models)) return m.models;
  return [];
}
function molFindAtomByIndex(model, index) {
  if (!MC.viewer) return null;
  if (MC.viewer.selectedAtoms) {
    try {
      const sel = { index: index };
      if (model !== undefined) sel.model = model;
      const hits = MC.viewer.selectedAtoms(sel);
      if (hits && hits.length) return hits[0];
    } catch (err) { /* 回退到 models 遍历 */ }
  }
  const models = molViewerModels();
  for (let i = 0; i < models.length; i++) {
    const m = models[i];
    const id = m.getID ? m.getID() : m.id;
    if (model !== undefined && id !== model) continue;
    const atoms = m.atoms || [];
    for (let j = 0; j < atoms.length; j++) if (atoms[j].index === index) return atoms[j];
  }
  return null;
}
function molBondStyle(bond) {
  const key = molBondKey(bond);
  if (!MC.bondStyles[key]) {
    MC.bondStyles[key] = { model: bond.model, a: bond.a, b: bond.b };
  }
  return MC.bondStyles[key];
}
// 遍历当前模型中所有键（低索引端 → 高索引端）。
function molEachBond(cb, allFrames) {
  molViewerModels().forEach(function (m) {
    const modelId = m.getID ? m.getID() : m.id;
    const groups = (allFrames && m.frames && m.frames.length) ? m.frames : [m.atoms || []];
    groups.forEach(function (atoms) {
      atoms.forEach(function (atom) {
        (atom.bonds || []).forEach(function (j, pos) {
          if (!Number.isInteger(j) || atom.index >= j) return;
          const other = atoms[j] || molFindAtomByIndex(modelId, j);
          if (!other) return;
          cb({ model: modelId, a: atom.index, b: j, pos: pos }, atom, other);
        });
      });
    });
  });
}
// 记录每条键的原始键级，供实线恢复与虚线切换使用（1.5 只是渲染用的非整数键级）。
function molBondBaseOrder(bond, low) {
  const key = molBondKey(bond);
  if (typeof MC.bondBaseOrders[key] === "number") return MC.bondBaseOrders[key];
  const order = low.bondOrder && typeof low.bondOrder[bond.pos] === "number" ? low.bondOrder[bond.pos] : 1;
  MC.bondBaseOrders[key] = order;
  return order;
}
function molCaptureBondBaseOrders() {
  if (!MC.bondBaseOrders) MC.bondBaseOrders = {};
  molEachBond(function (bond, low) { molBondBaseOrder(bond, low); });
}
function molBondStyleMode(st) {
  if (molBondHidden) return "none";
  if (st && (st.style === "none" || st.style === "solid" || st.style === "dashed")) return st.style;
  const dashed = st && typeof st.dashed === "boolean" ? st.dashed : molBondDashed;
  return dashed ? "dashed" : "solid";
}
function molBondRenderSpec(bond, baseOrder) {
  const st = MC.bondStyles[molBondKey(bond)];
  const mode = molBondStyleMode(st);
  const hidden = mode === "none";
  // 3Dmol 的 bondStyles 不支持逐键 hidden；用极小半径让该键实际不可见，
  // 同时保留拾取圆柱，仍可左键选中/右键把它改回实线或虚线。
  const radius = hidden ? 1e-5
    : (st && typeof st.radius === "number" ? st.radius : molBondRadius);
  const color = st && st.color ? st.color : molBondColor;
  const dashed = mode === "dashed";
  const bs = { radius: radius };
  if (color) { bs.color1 = color; bs.color2 = color; }
  if (dashed) {
    const cfg = { dashLength: MOL_BOND_DASH_LENGTH, gapLength: MOL_BOND_GAP_LENGTH };
    if (color) { cfg.solidColor = color; cfg.dashedColor = color; }
    bs.dashedBondConfig = cfg;
  }
  return { bs: bs, dashed: dashed, baseOrder: baseOrder };
}
function molSetBondRender(bond, low, other, spec) {
  // 没有覆盖（默认半径/按元素/实线）时不留 per-bond 样式，让 3Dmol 走原生默认渲染。
  const needOverride = !!spec.bs.color1 || !!spec.bs.dashedBondConfig || spec.bs.radius !== molBondRadius;
  [low, other].forEach(function (atom, i) {
    if (!atom || !Array.isArray(atom.bonds)) return;
    const pos = atom.bonds.indexOf(i ? bond.a : bond.b);
    if (pos < 0) return;
    if (!needOverride) {
      if (Array.isArray(atom.bondStyles)) delete atom.bondStyles[pos];
    } else {
      if (!Array.isArray(atom.bondStyles)) atom.bondStyles = new Array(atom.bonds.length);
      atom.bondStyles[pos] = spec.bs;
    }
    if (Array.isArray(atom.bondOrder)) atom.bondOrder[pos] = spec.dashed ? 1.5 : spec.baseOrder;
  });
}
// 把所有键（含单键覆盖）的渲染样式刷到模型，并强制 3Dmol 重建键几何。
function molApplyBondStyles() {
  if (!MC.viewer) return;
  molCaptureBondBaseOrders();
  // 逐键渲染参数写进每个帧的原子对象，保证多帧轨迹中同一键样式一致。
  molEachBond(function (bond, low, other) {
    molSetBondRender(bond, low, other,
      molBondRenderSpec(bond, molBondBaseOrder(bond, low)));
  }, true);
  // 关键：addStyle 是 merge（3Dmol setStyle 内部 Object.assign），若“按元素”时
  // 不带 color 键，上次“自定义”写入的 atom.style.stick.color 会残留，键无法恢复按元素着色。
  // 这里始终显式给出 color（无自定义色时为 undefined）以覆盖旧值；
  // dashedBondConfig 每次都是新对象，solidColor/dashedColor 随之被整体替换。
  const stick = { radius: molBondRadius, color: molBondColor || undefined,
    dashedBondConfig: { dashLength: MOL_BOND_DASH_LENGTH, gapLength: MOL_BOND_GAP_LENGTH } };
  if (molBondColor) {
    stick.dashedBondConfig.solidColor = molBondColor;
    stick.dashedBondConfig.dashedColor = molBondColor;
  }
  MC.viewer.addStyle({}, { stick: stick });
  molRedrawSupercell();
  MC.viewer.render();
  molMarkViewDirty();
}
function molSetBondOrder(model, a, b, order) {
  [a, b].forEach(function (idx, i) {
    const other = i ? a : b;
    const atom = molFindAtomByIndex(model, idx);
    if (!atom || !Array.isArray(atom.bonds) || !Array.isArray(atom.bondOrder)) return;
    const pos = atom.bonds.indexOf(other);
    if (pos >= 0) atom.bondOrder[pos] = order;
  });
}
function molApplyBondStyle(bond) {
  if (!bond) return;
  molApplyBondStyles();
}
function molResetBondStyle(bond) {
  if (!bond) return;
  delete MC.bondStyles[molBondKey(bond)];
  molApplyBondStyles();
}
function molResetAllBondStyles() {
  MC.bondStyles = {};
  molApplyBondStyles();
}
function molClearBondPickShapes() {
  if (MC.viewer && MC.viewer.removeShape) {
    (MC.bondPickShapes || []).forEach(function (entry) {
      try { MC.viewer.removeShape(entry.shape); } catch (err) { /* 忽略 */ }
    });
  }
  MC.bondPickShapes = [];
}
function molRebuildBondPickShapes() {
  molClearBondPickShapes();
  if (!MC.viewer || !MC.viewer.addCylinder) return;
  // 扩胞后原子数成倍增长；拾取圆柱只给原胞（前 baseLen 个原子）建，
  // 否则大超晶胞会额外产生几万个透明圆柱，又变卡。
  const baseLen = MC.sourceFrames && MC.sourceFrames[0] ? MC.sourceFrames[0].length : 0;
  const models = molViewerModels();
  models.forEach(function (m) {
    const modelId = m.getID ? m.getID() : m.id;
    const atoms = m.atoms || [];
    atoms.forEach(function (atom) {
      if (baseLen && atom.index >= baseLen) return;
      (atom.bonds || []).forEach(function (j, pos) {
        if (!Number.isInteger(j) || atom.index >= j) return;
        const other = atoms[j] || molFindAtomByIndex(modelId, j);
        if (!other) return;
        const bond = { model: modelId, a: atom.index, b: j, pos: pos };
        const st = MC.bondStyles[molBondKey(bond)] || {};
        const shape = MC.viewer.addCylinder({
          start: molAtomPos(atom), end: molAtomPos(other),
          radius: Math.max(0.14, (typeof st.radius === "number" ? st.radius : molBondRadius) * 2.2),
          color: "#ffffff", opacity: 0.01, contextMenuEnabled: true,
          clickable: true, callback: molOnBondClick
        });
        if (shape) MC.bondPickShapes.push({ shape: shape, bond: bond });
      });
    });
  });
  if (MC.bondPickShapes.length && MC.viewer.render) MC.viewer.render();
}
function molBondFromPickShape(shape) {
  const list = MC.bondPickShapes || [];
  // 3Dmol 回调首参是 shape 本身（其 clickable 为布尔 true），命中列表里则是
  // {clickable: shape}；两种形式都接受，避免左键点键时取不到 bond。
  const shapes = [shape, shape && shape.clickable && typeof shape.clickable === "object"
    ? shape.clickable : null];
  for (let s = 0; s < shapes.length; s++) {
    if (!shapes[s]) continue;
    for (let i = 0; i < list.length; i++) if (list[i].shape === shapes[s]) return list[i].bond;
  }
  return null;
}
function molIsoFromPickShape(shape) {
  const list = [MC.isoShape, MC.isoNegShape].filter(Boolean);
  const shapes = [shape, shape && shape.clickable && typeof shape.clickable === "object"
    ? shape.clickable : null];
  for (let s = 0; s < shapes.length; s++) {
    if (shapes[s] && list.indexOf(shapes[s]) >= 0) return shapes[s];
  }
  return null;
}
// 左键点在键的透明拾取圆柱上：切换该键键长；可同时选多条键，重复点同一条才取消。
// 与原子测量互斥。3Dmol 调用签名是 (clickable, viewer, event)；右键由 host 的 contextmenu 处理，这里只认左键。
function molOnBondClick(shape, viewer, ev, container, hits) {
  if (MC.longPressHandled) return;
  const button = ev && typeof ev.button === "number" ? ev.button : 0;
  if (button !== 0) return;
  if (!MC.measureMode) { molHidePickPanel(); return; }
  // 3Dmol 把 shape 本体作为第一个参数（shape.clickable 是布尔 true，不是 shape），
  // 不能直接取 shape.clickable；命中的是圆柱时它本身就在 bondPickShapes 里。
  const target = shape;
  const bond = molBondFromPickShape(target);
  if (!bond) return;
  // 键拾取圆柱较粗，可能与原子拾取球重叠；若射线更近命中原子，交回原子点击处理。
  if (viewer && viewer.mouseXY && viewer.targetedObjects && ev) {
    try {
      const xy = viewer.mouseXY(ev.pageX, ev.pageY);
      const atomHits = viewer.targetedObjects(xy.x, xy.y, viewer.clickables || []) || [];
      const atomTarget = molNearestTarget(atomHits, function (h) { return molResolveAtom(h.clickable || h); });
      let bondDist = null;
      (hits || []).some(function (h) {
        if ((h.clickable || h) === target) {
          bondDist = typeof h.distance === "number" && isFinite(h.distance) ? h.distance : 0;
          return true;
        }
        return false;
      });
      if (atomTarget && (bondDist === null || atomTarget.distance < bondDist)) {
        molOnAtomClick(atomTarget.obj, viewer, ev);
        return;
      }
    } catch (err) { /* 比较失败时按键处理 */ }
  }
  molHidePickPanel();
  if (!Array.isArray(MC.pickBonds)) MC.pickBonds = [];
  const key = molBondKey(bond);
  const at = MC.pickBonds.findIndex(function (b) { return molBondKey(b) === key; });
  if (at >= 0) MC.pickBonds.splice(at, 1);
  else MC.pickBonds.push(bond);
  MC.pickAtoms = [];
  molDrawMeasure();
  molMarkViewDirty();
}
function molBondDefaults(bond) {
  const st = MC.bondStyles[molBondKey(bond)] || {};
  const low = molFindAtomByIndex(bond.model, bond.a);
  return {
    color: st.color || molBondColor || molDefaultColor(low && low.elem),
    radius: typeof st.radius === "number" ? st.radius : molBondRadius,
    mode: molBondStyleMode(st)
  };
}
function molBuildBondPanel(bond) {
  const box = $("molPickStyleBox");
  if (!box) return;
  // 键面板复用同一个容器：改标记，切回空白/原子右键时才能重建“样式设置”。
  box.dataset.mode = "bond";
  box.innerHTML = "";
  const d = molBondDefaults(bond);
  const key = molBondKey(bond);
  const group = document.createElement("div");
  group.className = "mol-pick-group";
  // 顺序：键样式、键粗、键颜色模式、键颜色（仅“自定义”时显示）。
  group.appendChild(molMakeStyleRow({ id: "molBondPickStyle", label: "键样式", type: "select",
    options: MOL_BOND_STYLE_MODES,
    get: function () { return d.mode; },
    set: function (v) {
      molBondStyle(bond).style = v;
      molBondStyle(bond).dashed = v === "dashed";
      molApplyBondStyle(bond);
    } }));
  group.appendChild(molMakeStyleRow({ id: "molBondPickRadius", label: "键粗",
    min: 0.02, max: 0.30, step: 0.01,
    get: function () { return d.radius; },
    set: function (v) { molBondStyle(bond).radius = v; molApplyBondStyle(bond); } }));
  group.appendChild(molMakeStyleRow({ id: "molBondPickColorMode", label: "键颜色模式", type: "select",
    options: [{ key: "element", label: "按元素" }, { key: "custom", label: "自定义" }],
    get: function () { return d.color && (MC.bondStyles[key] || {}).color ? "custom" : "element"; },
    set: function (v) {
      if (v === "custom") {
        molBondStyle(bond).color = d.color;
      } else if (MC.bondStyles[key]) {
        delete MC.bondStyles[key].color;
        if (!Object.keys(MC.bondStyles[key]).some(k => k !== "model" && k !== "a" && k !== "b")) {
          delete MC.bondStyles[key];
        }
      }
      molApplyBondStyle(bond);
      molBuildBondPanel(bond);
    } }));
  const colorRow = molMakeStyleRow({ id: "molBondPickColor", label: "键颜色", type: "color",
    get: function () { return d.color; },
    set: function (v) { molBondStyle(bond).color = v; molApplyBondStyle(bond); } });
  colorRow.id = "molBondPickColorRow";
  const colorInput = colorRow.querySelector('input[type="color"]');
  const custom = !!(MC.bondStyles[key] || {}).color;
  if (colorInput) colorInput.disabled = !custom;
  colorRow.classList.toggle("hidden", !custom);
  group.appendChild(colorRow);
  box.appendChild(group);
}
function molOpenBondPanel(bond, ev) {
  if (!bond) { molOpenStylePanel(ev); return; }
  MC.styleAtom = null;
  MC.styleBond = bond;
  MC.pickMode = "bond";
  const panel = $("molPickPanel");
  if (!panel) return;
  const title = $("molPickTitle");
  if (title) title.textContent = tx("键样式");
  panel.setAttribute("aria-label", tx("键样式"));
  const colorRow = $("molPickColorRow"), sizeRow = $("molPickSizeRow"), styleBox = $("molPickStyleBox");
  if (colorRow) colorRow.classList.add("hidden");
  if (sizeRow) sizeRow.classList.add("hidden");
  if (styleBox) styleBox.classList.remove("hidden");
  molBuildBondPanel(bond);
  panel.classList.remove("hidden");
  molPositionPickPanel(ev, panel);
  molLayoutColorSwatches();
}

function molResetPickSettings() {
  if (MC.pickMode === "bond") {
    if (MC.styleBond) molResetBondStyle(MC.styleBond);
    if (MC.styleBond) molBuildBondPanel(MC.styleBond);
    return;
  }
  if (MC.pickMode === "iso") {
    // 等值面设置弹窗的“恢复默认”只重置等值面字段，不影响键、坐标轴等其他外观。
    const iso = MOL_STYLE_GROUPS.find(function (g) { return g.key === "iso"; });
    if (iso) iso.fields.forEach(function (f) { f.set(f.def); });
    molSyncStyleFields();
    return;
  }
  if (MC.pickMode === "global") {
    MOL_STYLE_FIELDS.forEach(function (f) { f.set(f.def); });
    molSyncStyleFields();
    return;
  }
  molResetAtomStyle();
}

// 取命中列表里最近的一个有效对象及其射线距离。3Dmol 的 targetedObjects 结果按距离升序，
// distance 可直接比较；测试桩若不给 distance 则用数组顺序（下标）作为回退排序依据。
function molNearestTarget(hits, resolve) {
  const list = hits || [];
  for (let i = 0; i < list.length; i++) {
    const obj = resolve(list[i]);
    if (!obj) continue;
    const d = typeof list[i].distance === "number" && isFinite(list[i].distance)
      ? list[i].distance : i;
    return { obj: obj, distance: d };
  }
  return null;
}

// 坐标轴 / 原子 / 键 / 空白处共用的弹窗入口：右键与长按都走这里。
function molOpenContextHere(ev) {
  if (!ev) return;
  if (typeof ev.preventDefault === "function") ev.preventDefault();
  if (ev.target && ev.target.closest && ev.target.closest(".mol-axis-gizmo")) {
    molOpenStylePanel(ev, "axis");
    return;
  }
  molOnContextMenu(ev);
}

function molOnContextMenu(ev) {
  ev.preventDefault();
  if (!MC.viewer) return;
  let atom = null, bond = null, iso = null;
  try {
    const xy = MC.viewer.mouseXY(ev.pageX, ev.pageY);
    // 原子、键拾取圆柱与等值面可能同时命中；取射线距离更近者，
    // 从而准确区分“点在原子上 / 键上 / 等值面上 / 空白处”。
    const atomHits = MC.viewer.targetedObjects(xy.x, xy.y, MC.viewer.clickables || []) || [];
    const menuObjects = MC.viewer.contextMenuEnabledObjects || [];
    const menuHits = menuObjects.length
      ? (MC.viewer.targetedObjects(xy.x, xy.y, menuObjects) || []) : [];
    const bondHits = menuHits.filter(function (h) { return !!molBondFromPickShape(h.clickable); });
    const isoHits = menuHits.filter(function (h) { return !!molIsoFromPickShape(h.clickable); });
    const atomTarget = molNearestTarget(atomHits, molResolveAtom);
    const bondTarget = molNearestTarget(bondHits, function (h) { return molBondFromPickShape(h.clickable); });
    const isoTarget = molNearestTarget(isoHits, function (h) { return molIsoFromPickShape(h.clickable); });
    const candidates = [];
    if (atomTarget) candidates.push({ d: atomTarget.distance, kind: "atom", obj: atomTarget.obj });
    if (bondTarget) candidates.push({ d: bondTarget.distance, kind: "bond", obj: bondTarget.obj });
    if (isoTarget) candidates.push({ d: isoTarget.distance, kind: "iso", obj: isoTarget.obj });
    candidates.sort(function (a, b) { return a.d - b.d; });
    const hit = candidates[0];
    if (hit && hit.kind === "atom") atom = hit.obj;
    else if (hit && hit.kind === "bond") bond = hit.obj;
    else if (hit && hit.kind === "iso") iso = hit.obj;
  } catch (err) { /* 拾取失败时按空白处处理 */ }
  if (iso) molOpenStylePanel(ev, "iso");
  else if (atom && MC.selectMode) {
    molOpenAtomPanel({ model: atom.model, index: atom.index, elem: atom.elem }, ev);
  }
  else if (atom) molOpenPickPanel(atom, ev);
  else if (bond) molOpenBondPanel(bond, ev);
  else molOpenStylePanel(ev);
}

function molOnAtomClick(atom, viewer, ev) {
  if (MC.selectMode) return;  // 选择模式由画布的 pointer 流程统一处理
  if (MC.longPressHandled) return;
  const button = ev && typeof ev.button === "number" ? ev.button : 1;
  if (button === 2) { molOpenPickPanel(atom, ev); return; }
  if (button !== 0) return;
  if (!MC.measureMode) { molHidePickPanel(); return; }
  molHidePickPanel();
  MC.pickBonds = [];  // 原子测量与键长互斥
  const key = molAtomKey(atom);
  const at = MC.pickAtoms.findIndex(function (a) { return molAtomKey(a) === key; });
  if (at >= 0) MC.pickAtoms.splice(at, 1);
  else MC.pickAtoms.push(atom);
  molDrawMeasure();
  molMarkViewDirty();
}

function getDDValue(menuId) {
  const menu = $(menuId);
  const sel = menu && menu.querySelector('li[aria-selected="true"]');
  return sel ? sel.getAttribute("data-value") : null;
}

function setDDItem(menuId, value) {
  const menu = $(menuId);
  if (!menu) return;
  menu.querySelectorAll("li").forEach(function (li) {
    li.setAttribute("aria-selected", li.getAttribute("data-value") === value ? "true" : "false");
  });
}

function bindDDElements(btn, menu, formatLabel, onChange) {
  if (!btn || !menu) return;
  btn.onclick = function (ev) {
    ev.stopPropagation();
    const wrapper = btn.closest(".mol-dd");
    const wasOpen = wrapper.classList.contains("open");
    document.querySelectorAll(".mol-dd.open").forEach(function (d) { d.classList.remove("open"); });
    if (!wasOpen) wrapper.classList.add("open");
  };
  menu.addEventListener("click", function (ev) {
    const li = ev.target.closest("li");
    if (!li) return;
    ev.stopPropagation();
    const wrapper = this.closest(".mol-dd");
    const btnEl = wrapper.querySelector(".mol-dd-btn");
    this.querySelectorAll("li").forEach(function (item) { item.setAttribute("aria-selected", "false"); });
    li.setAttribute("aria-selected", "true");
    if (formatLabel) btnEl.textContent = formatLabel(li);
    else btnEl.textContent = li.textContent + " ▲";
    wrapper.classList.remove("open");
    if (onChange) onChange(li.getAttribute("data-value"));
  });
}
function bindDD(btnId, menuId, formatLabel, onChange) {
  bindDDElements($(btnId), $(menuId), formatLabel, onChange);
}

// 旋转下拉：X/Y/Z 轴、角度
function getMolAxis() { return getDDValue("molAxisMenu") || "y"; }
let molCustomAngle = 30;
function getMolAngle() {
  const v = getDDValue("molAngleMenu");
  if (v === "custom") return Number(molCustomAngle) || 30;
  return Number(v) || 30;
}
function getMolZoomStep() { return Number(getDDValue("molZoomStepMenu")) || 1.25; }
function getMolSpeed() { return Number(getDDValue("molSpeedMenu")) || 1; }
function setMolDensityKindItems(items, currentIndex) {
  const menu = document.getElementById("molDensityKindMenu");
  const btn = document.getElementById("molDensityKindBtn");
  if (!menu || !btn) return;
  menu.innerHTML = "";
  btn.classList.toggle("hidden", items.length <= 1);
  items.forEach(function (g, i) {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.setAttribute("data-value", String(i));
    li.textContent = g.label;
    if (i === currentIndex) li.setAttribute("aria-selected", "true");
    menu.appendChild(li);
  });
  const cur = menu.querySelector('li[aria-selected="true"]');
  btn.textContent = cur ? cur.textContent + " ▲" : "";
}
function getMolDensityKind() {
  return Number(getDDValue("molDensityKindMenu")) || 0;
}

// 正对 X/Y/Z 按钮移入左下角控件后，仍沿用原按钮 ID 与点击行为。
["X", "Y", "Z"].forEach(function (axis) {
  const btn = document.getElementById("molFace" + axis);
  if (btn) btn.onclick = function () { molFaceAxis(axis.toLowerCase()); };
});
bindDD("molZoomStepBtn", "molZoomStepMenu", function (li) { return li.textContent + " ▲"; });
bindDD("molAxisBtn", "molAxisMenu", function (li) {
  if (IS_EN) return li.textContent.replace(" axis", "") + " axis ▲";
  return li.textContent.replace(" 轴", "") + "轴 ▲";
});
bindDD("molAngleBtn", "molAngleMenu", function (li) {
  if (li.getAttribute("data-value") === "custom") {
    return String(molCustomAngle) + "° ▲";
  }
  return li.textContent + " ▲";
});
(function bindMolAngleCustomInput() {
  const menu = $("molAngleMenu");
  const li = menu && menu.querySelector('li[data-value="custom"]');
  const text = li && li.querySelector(".mol-angle-custom-text");
  const edit = li && li.querySelector(".mol-angle-custom-edit");
  const input = $("molAngleCustomInput");
  const ok = $("molAngleCustomOk");
  if (!li || !text || !edit || !input || !ok) return;
  function closeEdit() { edit.classList.add("hidden"); }
  function apply() {
    const raw = String(input.value || "").trim();
    const n = Number(raw);
    if (!raw || !isFinite(n) || n < 1 || n > 360) {
      toast(tx("旋转角度须为 1-360 度"), true);
      try { input.focus(); } catch (e) {}
      return;
    }
    molCustomAngle = n;
    const label = tx("自定义") + "(" + n + "°)";
    text.textContent = label;
    const btn = $("molAngleBtn");
    if (btn) btn.textContent = n + "° ▲";
    setDDItem("molAngleMenu", "custom");
    closeEdit();
    const wrapper = li.closest(".mol-dd");
    if (wrapper) wrapper.classList.remove("open");
  }
  // 整行都可展开输入框；编辑框内部有自己的处理器，不会被这里重复触发。
  li.addEventListener("click", function (ev) {
    if (ev.target.closest && ev.target.closest(".mol-angle-custom-edit")) return;
    ev.preventDefault(); ev.stopPropagation();
    if (edit.classList.contains("hidden")) {
      input.value = String(molCustomAngle);
      edit.classList.remove("hidden");
    }
    try { input.focus(); input.select(); } catch (e) {}
  });
  ok.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); apply(); });
  input.addEventListener("keydown", function (ev) {
    ev.stopPropagation();
    if (ev.key === "Enter") { ev.preventDefault(); apply(); }
    else if (ev.key === "Escape") {
      ev.preventDefault(); closeEdit();
      const wrapper = li.closest(".mol-dd");
      if (wrapper) wrapper.classList.remove("open");
    }
  });
  edit.addEventListener("click", function (ev) { ev.stopPropagation(); });
  menu.addEventListener("click", function (ev) {
    if (!ev.target.closest('li[data-value="custom"]')) closeEdit();
  });
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest(".mol-dd")) closeEdit();
  });
})();
bindDD("molSpeedBtn", "molSpeedMenu", function (li) { return li.textContent + " ▲"; }, function () {
  if (MC.timer) startMolPlay();
});
bindDD("molDensityKindBtn", "molDensityKindMenu", null, function (val) {
  switchMolDensityGroup(Number(val) || 0);
});
bindDD("mediaSpeedBtn", "mediaSpeedMenu", function (li) { return li.textContent + " ▲"; }, function (val) {
  if (quickMedia) quickMedia.playbackRate = Number(val) || 1;
});
$("mediaPlay").onclick = function () {
  if (!quickMedia) return;
  if (quickMedia.paused) {
    const p = quickMedia.play();
    if (p && p.catch) p.catch(function () {});
  } else quickMedia.pause();
};
$("mediaRange").oninput = function () {
  if (!quickMedia) return;
  const d = isFinite(quickMedia.duration) ? quickMedia.duration : 0;
  quickMedia.currentTime = Math.max(0, Math.min(d, Number(this.value) || 0));
};
$("mediaMute").onclick = function () {
  if (!quickMedia) return;
  quickMedia.muted = !quickMedia.muted;
  setMediaMuteIcon(quickMedia.muted);
};

// 左下角控件闲置淡出：与图片查看器一致，任何交互都重新显示，2.6s 后淡出。
let molZoomIdleTimer = null;
let molViewPointerHeld = false;
const MOL_ZOOM_IDLE_MS = 2600;
function molRevealZoomCtl() {
  const host = $("molCanvas");
  const ctls = host ? Array.prototype.slice.call(host.querySelectorAll(".zoom-ctl")) : [];
  if (!ctls.length) return;
  ctls.forEach(function (ctl) { ctl.classList.remove("idle"); });
  clearTimeout(molZoomIdleTimer);
  // 拖动旋转/平移期间保持显示，松开鼠标后才开始计时淡出。
  if (molViewPointerHeld) return;
  molZoomIdleTimer = setTimeout(function () {
    ctls.forEach(function (ctl) { ctl.classList.add("idle"); });
  }, MOL_ZOOM_IDLE_MS);
}
// 密度类型与帧播放按各自数据显隐；二者都出现时触发浮层显示（等值面/透明度在设置弹窗中）。
function molSyncExtraCtl() {
  const density = $("molDensityGroup"), player = $("molPlayer");
  const visible = !!(density && !density.classList.contains("hidden")) ||
                  !!(player && !player.classList.contains("hidden"));
  if (visible) molRevealZoomCtl();
}
function molBeginViewInteraction() {
  molViewPointerHeld = true;
  molRevealZoomCtl();
}
function molEndViewInteraction() {
  molViewPointerHeld = false;
  molRevealZoomCtl();
}

function molZoom(inward) {
  if (!MC.viewer) return;
  const step = Number(getMolZoomStep()) || 1.25;
  MC.viewer.zoom(inward ? step : 1 / step, 0);
  MC.viewer.render();
  molSyncZoomCtl();
  molRevealZoomCtl();
  molMarkViewDirty();
}

// 3D 结构窗左下角控件：“恢复初始视图”按钮 + 缩放滑杆 + 视角/正对按钮。
// 滑杆值表示相对打开结构时初始视图的缩放倍数（0.2–8×）。
function molZoomFactor() {
  const v = MC.viewer;
  if (!v || !MC.home || !Array.isArray(MC.home.view) || typeof v.getView !== "function") return 1;
  const camZ = Number(v.CAMERA_Z) || 20;
  const homeD = camZ - MC.home.view[3];
  const curD = camZ - v.getView()[3];
  if (!(homeD > 0) || !(curD > 0)) return 1;
  return Math.min(8, Math.max(0.2, homeD / curD));
}
function molSyncZoomCtl() {
  const slider = $("molZoomRange");
  if (slider) slider.value = String(molZoomFactor());
}
function molSetZoomFactor(factor) {
  const v = MC.viewer;
  if (!v || !MC.home || !Array.isArray(MC.home.view) || typeof v.getView !== "function") return;
  const next = Math.min(8, Math.max(0.2, Number(factor) || 1));
  const camZ = Number(v.CAMERA_Z) || 20;
  const homeD = camZ - MC.home.view[3];
  let z = camZ - homeD / next;
  if (typeof v.adjustZoomToLimits === "function") z = v.adjustZoomToLimits(z);
  const view = v.getView().slice();
  view[3] = z;
  v.setView(view);
  v.render();
  molDrawAxisGizmo();
  molSyncZoomCtl();
  molRevealZoomCtl();
  molMarkViewDirty();
}
// 清空 3D 画布时保留浮层控件：视角/正对按钮、密度类型与帧播放控件
// 都是从工具栏移动进来的，若随 innerHTML 一起清除，后续无法重建。
function molClearMolCanvas(host) {
  if (!host) return;
  Array.prototype.slice.call(host.children).forEach(function (child) {
    if (!child.classList || !child.classList.contains("zoom-ctl")) host.removeChild(child);
  });
}
function molEnsureZoomCtl() {
  const host = $("molCanvas");
  if (!host || $("molZoomRange")) return;
  const ctl = document.createElement("div");
  ctl.className = "zoom-ctl mol-zoom-ctl";
  ctl.setAttribute("role", "group");
  ctl.setAttribute("aria-label", tx("结构缩放"));

  // 视角正交/透视与正对 X/Y/Z 按钮从工具栏源码容器移入左下角，
  // 位于缩放滑杆右侧；原按钮的事件绑定保持不变。
  const view = document.createElement("div");
  view.className = "mol-view-group";
  view.setAttribute("role", "group");
  ["molProj", "molFaceX", "molFaceY", "molFaceZ"].forEach(function (id) {
    const btn = document.getElementById(id);
    if (btn) view.appendChild(btn);
  });

  const reset = document.createElement("button");
  reset.type = "button";
  reset.id = "molViewReset";
  reset.title = tx("恢复初始视图");
  reset.setAttribute("aria-label", reset.title);
  reset.innerHTML = '<span class="tool-glyph" aria-hidden="true">↫</span>';
  const slider = document.createElement("input");
  slider.type = "range";
  slider.id = "molZoomRange";
  slider.min = "0.2";
  slider.max = "8";
  slider.step = "0.05";
  slider.value = "1";
  slider.title = tx("结构缩放");
  slider.setAttribute("aria-label", slider.title);
  // “恢复初始视图”在缩放滑杆左边，视角/正对按钮在右边；打成一个整体避免换行时被拆散。
  const zoomRow = document.createElement("div");
  zoomRow.className = "mol-zoom-row";
  zoomRow.appendChild(reset);
  zoomRow.appendChild(slider);
  zoomRow.appendChild(view);
  ctl.appendChild(zoomRow);

  // 密度类型、帧播放依次跟在缩放滑杆后面；空间不足时由容器换行到上一行。
  ["molDensityGroup", "molPlayer"].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) ctl.appendChild(el);
  });
  host.appendChild(ctl);
  molSyncExtraCtl();
  reset.addEventListener("click", function (ev) { ev.stopPropagation(); molResetHomeView(); });
  slider.addEventListener("input", function () { molSetZoomFactor(Number(this.value) || 1); });
  if (!host._mctaZoomRevealBound) {
    host._mctaZoomRevealBound = true;
    host.addEventListener("pointerdown", molBeginViewInteraction, true);
    host.addEventListener("click", molRevealZoomCtl, true);
    host.addEventListener("wheel", molRevealZoomCtl, { passive: true, capture: true });
    if (!window._mctaZoomPointerRelease) {
      window._mctaZoomPointerRelease = true;
      ["pointerup", "pointercancel"].forEach(function (name) {
        document.addEventListener(name, function () {
          if (molViewPointerHeld) molEndViewInteraction();
        }, true);
      });
    }
  }
  ctl.addEventListener("pointerenter", molRevealZoomCtl);
  ctl.addEventListener("pointermove", molRevealZoomCtl);
  molRevealZoomCtl();
}
function molResetHomeView() {
  const v = MC.viewer;
  if (!v || !MC.home || !Array.isArray(MC.home.view)) return;
  v.setView(MC.home.view);
  if (MC.home.look && v.lookingAt) {
    if (typeof v.lookingAt.copy === "function") v.lookingAt.copy(MC.home.look);
    else { v.lookingAt.x = MC.home.look.x; v.lookingAt.y = MC.home.look.y; v.lookingAt.z = MC.home.look.z; }
    if (v.camera && typeof v.camera.lookAt === "function") v.camera.lookAt(v.lookingAt);
  }
  v.render();
  molDrawAxisGizmo();
  molSyncZoomCtl();
  molRevealZoomCtl();
  molMarkViewDirty();
}

// 原子取景点：圆心 + 半径在三个轴向的端点。只按圆心取景时，大半径原子（尤其是
// 晶格隐藏、只剩原子的情况）会把球面留在窗口外。
function molPushAtomFitPoints(atom, pts) {
  const sphere = atom.style && atom.style.sphere;
  if (sphere && sphere.hidden) return;
  const p = molAtomPos(atom);
  pts.push(p);
  const r = Math.abs(Number(sphere && sphere.radius) || 0);
  if (r > 0) {
    pts.push({ x: p.x + r, y: p.y, z: p.z });
    pts.push({ x: p.x - r, y: p.y, z: p.z });
    pts.push({ x: p.x, y: p.y + r, z: p.z });
    pts.push({ x: p.x, y: p.y - r, z: p.z });
    pts.push({ x: p.x, y: p.y, z: p.z + r });
    pts.push({ x: p.x, y: p.y, z: p.z - r });
  }
}

// 当前显示内容的模型坐标点：可见原子（含半径） + 晶格外框 8 个角点（超晶胞外边界）。
function molFitPoints() {
  const pts = [];
  if (molAtomsVisible !== false && MC.viewer) {
    let atoms = [];
    // selectedAtoms 直接给出当前帧真正显示的原子，避免旧模型或额外模型混进取景范围。
    if (typeof MC.viewer.selectedAtoms === "function") {
      try { atoms = MC.viewer.selectedAtoms({}) || []; } catch (err) { atoms = []; }
    }
    if (atoms.length) atoms.forEach(function (atom) { molPushAtomFitPoints(atom, pts); });
    else molViewerModels().forEach(function (m) {
      (m.atoms || []).forEach(function (atom) { molPushAtomFitPoints(atom, pts); });
    });
  }
  if (MC.cell && MC.cell.length >= 3 && molCellStyle.visible !== false) {
    const n = molCellRepeat();
    for (let a = 0; a <= 1; a++) for (let b = 0; b <= 1; b++) for (let c = 0; c <= 1; c++) {
      pts.push(molCellCorner(MC.cell, a * n[0], b * n[1], c * n[2]));
    }
  }
  return pts;
}

// modelToScreen 返回的是文档坐标，取景时要先把画布页内偏移换算回来。
function molFitCanvasOffset(v, host) {
  if (v && typeof v.canvasOffset === "function") {
    try {
      const off = v.canvasOffset() || {};
      if (isFinite(off.left) && isFinite(off.top)) return { x: off.left, y: off.top };
    } catch (err) { /* 退回画布位置计算 */ }
  }
  if (host && typeof host.getBoundingClientRect === "function") {
    try {
      const r = host.getBoundingClientRect();
      return { x: r.left + (window.pageXOffset || 0), y: r.top + (window.pageYOffset || 0) };
    } catch (err) { /* 使用原点 */ }
  }
  return { x: 0, y: 0 };
}

// 相机 lookAt 在场景坐标，modelToScreen 会额外套一层 modelGroup 变换；
// 这里直接投影 lookAt 得到屏幕中心，兼容存档恢复后的非零平移。
function molFitScreenCenter(v, host, off) {
  const W = host && host.clientWidth, H = host && host.clientHeight;
  try {
    if (v && v.projector && v.camera && v.lookingAt && typeof v.projector.projectVector === "function") {
      const look = v.lookingAt;
      const p = typeof look.clone === "function" ? look.clone() : { x: look.x, y: look.y, z: look.z };
      v.projector.projectVector(p, v.camera);
      if (isFinite(p.x) && isFinite(p.y)) {
        const xr = v.renderer && typeof v.renderer.getXRatio === "function" ? v.renderer.getXRatio() : 1;
        const yr = v.renderer && typeof v.renderer.getYRatio === "function" ? v.renderer.getYRatio() : 1;
        const col = v.col || 0, row = v.row || 0;
        const vw = v.WIDTH || W, vh = v.HEIGHT || H;
        return {
          x: off.x + col * vw / xr + vw / xr * (p.x + 1) / 2,
          y: off.y + (yr - row - 1) * vh / yr - vh / yr * (p.y - 1) / 2
        };
      }
    }
  } catch (err) { /* 不能投影时按画布正中处理 */ }
  return { x: off.x + W / 2, y: off.y + H / 2 };
}

// 当前可见内容在屏幕上的包围盒，以及镜头中心在屏幕上的位置。
function molFitScreenBounds(v, host, pts) {
  if (!v || typeof v.modelToScreen !== "function" || !pts || !pts.length) return null;
  const scr = v.modelToScreen(pts) || [];
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  scr.forEach(function (p) {
    if (!p || !isFinite(p.x) || !isFinite(p.y)) return;
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  });
  if (!isFinite(minX) || !isFinite(minY)) return null;
  const off = molFitCanvasOffset(v, host);
  const center = molFitScreenCenter(v, host, off);
  return {
    w: maxX - minX, h: maxY - minY,
    midX: (minX + maxX) / 2, midY: (minY + maxY) / 2,
    centerX: center.x, centerY: center.y
  };
}

// 把当前显示内容完整放进窗口。范围由 molFitPoints 决定：晶胞可见时包含晶胞/超晶胞
// 外框，晶胞隐藏时只包含可见原子。zoomTo 只按包围球定镜头，对不对称晶胞或已平移过的
// 视图仍可能把角点留在窗口外；因此按最终屏幕包围盒迭代校正平移与缩放。
function molFitToView() {
  if (!MC.viewer) return;
  try { MC.viewer.zoomTo(); } catch (err) { /* 视图不支持时保持原样 */ }
  try {
    const v = MC.viewer, host = $("molCanvas");
    const W = host && host.clientWidth, H = host && host.clientHeight;
    const pts = molFitPoints();
    if (W && H && pts.length && typeof v.zoom === "function") {
      const fill = 0.84;
      for (let i = 0; i < 3; i++) {
        const b = molFitScreenBounds(v, host, pts);
        if (!b) break;
        let moved = false;
        const dx = b.centerX - b.midX, dy = b.centerY - b.midY;
        if ((Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) && typeof v.translateScene === "function") {
          v.translateScene(dx, dy);
          moved = true;
        }
        const b2 = molFitScreenBounds(v, host, pts);
        if (!b2 || !(b2.w > 0 && b2.h > 0)) break;
        const factor = Math.min(W * fill / b2.w, H * fill / b2.h);
        let scaled = false;
        // 允许缩小：晶胞可见但超出原子范围时必须退远，才能把晶胞完整放进来。
        if (isFinite(factor) && factor > 0.001 && factor < 20 && Math.abs(factor - 1) > 0.01) {
          v.zoom(factor, 0);
          scaled = true;
        }
        if (!moved && !scaled) break;
      }
    }
  } catch (err) { /* 投影不可用时保留 zoomTo 的结果 */ }
  MC.viewer.render();
  molDrawAxisGizmo();
  molSyncZoomCtl();
  molRevealZoomCtl();
  molMarkViewDirty();
}

// 四元数乘法（[x,y,z,w]），与 3Dmol 的 quaternion.multiply 顺序一致：a * b 表示在 a 之后再施加 b 的本地旋转。
function molQuatMul(a, b) {
  return [
    a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]
  ];
}
function molQuatAxisAngle(axis, deg) {
  const half = deg * Math.PI / 360;
  const s = Math.sin(half);
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(half)];
}

// 视角正对某个坐标轴：3Dmol 默认从 +z 看向原点（旋转四元数为单位元），
// 正对 x/y 只需把模型转到对应轴朝向屏幕；保留平移与缩放，随后重新自适应。
function molFaceAxis(axis) {
  if (!MC.viewer || typeof MC.viewer.setView !== "function") return;
  const view = typeof MC.viewer.getView === "function" ? MC.viewer.getView() : null;
  if (!view || view.length < 8) return;
  const s = Math.SQRT1_2;
  let q = axis === "x" ? [0, -s, 0, s] : axis === "y" ? [s, 0, 0, s] : [0, 0, 0, 1];
  // 右手法则：拇指指向观察者时正角为逆时针。正对 X 还要再顺时针 90°（-90°），
  // 正对 Y 还要再逆时针 90°（+90°）；两者都绕各自正对的轴（屏幕法线）追加本地旋转。
  if (axis === "x") q = molQuatMul(q, molQuatAxisAngle([1, 0, 0], -90));
  else if (axis === "y") q = molQuatMul(q, molQuatAxisAngle([0, 1, 0], 90));
  MC.viewer.setView([view[0], view[1], view[2], view[3], q[0], q[1], q[2], q[3]]);
  molFitToView();
}

// “重置”回到未打开任何 _mcta.json 存档时的初始状态：
// 视图/相机、投影、帧、全局样式、逐原子样式、选中与测量、坐标轴指示器位置全部复位。
function resetMolView() {
  if (!MC.viewer) return;
  stopMolPlay();

  // 1) 全局样式字段恢复到页面初始值（MOL_STYLE_FIELDS 加载时已把 def 记为初始值）
  MOL_STYLE_FIELDS.forEach(function (f) { f.set(f.def); });
  molSyncStyleFields();

  // 2) 逐原子颜色/大小恢复默认
  MC.atomStyles = {};
  molApplyDefaultAtomStyle();
  // 2b) 逐键样式恢复默认（同时清掉被虚线改写的键级基准）
  MC.bondStyles = {};
  MC.bondBaseOrders = {};
  molApplyBondStyles();
  molApplyVisibility();
  molRebuildBondPickShapes();

  // 3) 清除选中与测量标注，并关闭测量模式
  MC.measureMode = false;
  molSyncMeasureButton();
  molClearMeasure(true);
  molHidePickPanel();

  // 4) 坐标轴指示器回到默认左上角贴边
  molGizmoPos = null;
  const host = $("molCanvas");
  if (host) {
    host._gizmoPos = null;
    const cv = host.querySelector(".mol-axis-gizmo");
    if (cv) {
      cv.style.left = "0px";
      cv.style.top = "0px";
      cv.style.bottom = "auto";
    }
  }

  // 5) 投影 / 帧 / 相机视图复位到无存档时的 home
  molSetProjection(true);
  if (MC.frames > 1) {
    MC.index = 0;
    MC.viewer.setFrame(0);
    $("molRange").value = "0";
  }
  if (MC.home) {
    MC.viewer.setView(MC.home.view);
    if (MC.home.look && MC.viewer.lookingAt) {
      MC.viewer.lookingAt.copy(MC.home.look);
      MC.viewer.camera.lookAt(MC.viewer.lookingAt);
    }
  }

  MC.archive = null;
  MC.viewer.render();
  molLabel();
  molDrawAxisGizmo();
}

// 把当前画面导出为图片：PNG 保留透明背景，JPEG/WebP 先垫白底。
// factor > 1 时先把渲染尺寸放大再取图，得到更高分辨率的图。
function saveMolImage(factor, format, filename) {
  if (!MC.viewer) return;
  const ext = format === "jpg" ? "jpg" : format;
  const mime = format === "jpg" ? "image/jpeg" : format === "webp" ? "image/webp" : "image/png";
  const finish = function (uri) {
    const img = new Image();
    img.onload = function () {
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext("2d");
      if (mime !== "image/png") {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }
      ctx.drawImage(img, 0, 0);
      // 坐标轴指示器是覆盖在画布上的独立 2D canvas，不属于 3Dmol 渲染结果，
      // 导出时需按其在画布中的位置与导出比例尺叠加进去。
      const host = $("molCanvas");
      const gizmo = host && host.querySelector(".mol-axis-gizmo");
      if (gizmo && gizmo.style.display !== "none" && gizmo.width && gizmo.height) {
        const cssSize = MOL_GIZMO_SIZE || parseFloat(gizmo.style.width) || gizmo.width;
        const left = parseFloat(gizmo.style.left) || 0;
        const top = parseFloat(gizmo.style.top) || 0;
        const sx = host.clientWidth ? canvas.width / host.clientWidth : 1;
        const sy = host.clientHeight ? canvas.height / host.clientHeight : 1;
        ctx.drawImage(gizmo, left * sx, top * sy, cssSize * sx, cssSize * sy);
      }
      const done = function (blob) {
        if (!blob || blob.type !== mime) {
          toast(tx("当前浏览器不支持导出 ") + ext.toUpperCase() + tx("，请改用 PNG"), true);
          return;
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        toast("已导出 " + filename);
      };
      if (canvas.toBlob) canvas.toBlob(done, mime, 0.95);
      else done(null);
    };
    img.onerror = function () { toast("导出图片失败", true); };
    img.src = uri;
  };
  MC.viewer.render();
  if (factor <= 1) {
    finish(MC.viewer.pngURI());
    return;
  }
  // 临时放大渲染尺寸取图，再恢复原尺寸；上限 4096 像素，避免超出显卡视口限制
  const width = MC.viewer.WIDTH;
  const height = MC.viewer.HEIGHT;
  const ratio = width > 0 ? (MC.viewer.getCanvas().width / width) || 1 : 1;
  const cap = 4096;
  const mul = Math.max(1, Math.min(factor, cap / (width * ratio), cap / (height * ratio)));
  MC.viewer.setWidth(Math.round(width * mul));
  MC.viewer.setHeight(Math.round(height * mul));
  MC.viewer.render();
  const uri = MC.viewer.pngURI();
  MC.viewer.setWidth(width);
  MC.viewer.setHeight(height);
  MC.viewer.resize();
  MC.viewer.render();
  finish(uri);
}

// 保存前在弹窗中选择格式、分辨率倍数并确认文件名

function molSaveOptions() {
  const format = $("molFormat").value;
  const ext = format === "jpg" ? "jpg" : format;
  const factor = Math.max(1, Number($("molScale").value) || 1);
  const base = (MC.baseName || "structure").replace(/\.[^.]+$/, "");
  const suffix = (MC.frames > 1 ? "-" + (MC.index + 1) : "") + "-" + factor + "x";
  return { factor: factor, format: format, ext: ext, filename: base + suffix + "." + ext };
}

function syncMolSaveName() {
  if (!MC.saveJob) return;
  MC.saveJob = molSaveOptions();
  $("molSaveName").value = MC.saveJob.filename;
}

function openMolSave() {
  if (!MC.viewer) return;
  MC.saveJob = molSaveOptions();
  $("molSaveName").value = MC.saveJob.filename;
  $("molSaveBox").classList.remove("hidden");
  $("molSaveName").focus();
  $("molSaveName").select();
}

function closeMolSave() {
  $("molSaveBox").classList.add("hidden");
  MC.saveJob = null;
  if (molSaveResolve) {
    const done = molSaveResolve;
    molSaveResolve = null;
    done(false);
  }
}

function confirmMolSave() {
  if (!MC.saveJob) { closeMolSave(); return; }
  const job = molSaveOptions();
  const typed = $("molSaveName").value.trim();
  const name = /\.[^.\/]+$/.test(typed) ? typed : (typed || "structure") + "." + job.ext;
  $("molSaveBox").classList.add("hidden");
  MC.saveJob = null;
  if (molSaveResolve) {
    const done = molSaveResolve;
    molSaveResolve = null;
    done(true);
  }
  saveMolImage(job.factor, job.format, name);
}

// ---- 3D 视图存档：旋转/平移/缩放、投影、帧、样式与原子标注 ----
// 存档文件名 = 完整结构文件名（保留扩展名）+ "_mcta.json"，与结构同目录；
// 例如 structure.cif -> structure.cif_mcta.json，避免不同扩展名的同名结构混淆。
function molArchivePath(structPath) {
  const cleaned = String(structPath || "").replace(/\\/g, "/");
  const slash = cleaned.lastIndexOf("/");
  const dir = slash >= 0 ? cleaned.slice(0, slash + 1) : "";
  const name = slash >= 0 ? cleaned.slice(slash + 1) : cleaned;
  return dir + name + "_mcta.json";
}

// 从当前 viewer 采集视图状态。getView() 为 [平移x,y,z, 缩放z, 四元数x,y,z,w]。
function molCaptureArchive() {
  const viewer = MC.viewer;
  if (!viewer) return null;
  const view = viewer.getView ? Array.prototype.slice.call(viewer.getView()) : null;
  const look = viewer.lookingAt
    ? [viewer.lookingAt.x, viewer.lookingAt.y, viewer.lookingAt.z] : null;
  const atoms = Object.keys(MC.atomStyles).map(function (key) {
    const s = MC.atomStyles[key];
    return { model: s.model, index: s.index, color: s.color, radius: s.radius };
  });
  const picks = (MC.pickAtoms || []).map(function (a) {
    return { model: a.model, index: a.index };
  });
  return {
    format: "mcta-view",
    version: 1,
    source: MC.baseName || "",
    saved: new Date().toISOString(),
    view: { matrix: view, lookingAt: look, ortho: !!MC.ortho, frame: MC.index || 0 },
    cellOrigin: Object.assign({}, molCellOffset()),
    style: {
      bondRadius: molBondRadius,
      bondColor: molBondColor,
      bondDashed: molBondDashed,
      bondHidden: molBondHidden,
      atomRadius: molAtomRadius,
      atomColor: molAtomColor,
      atomsVisible: molAtomsVisible,
      bondsVisible: molBondsVisible,
      depthCue: molDepthCue,
      cell: {
        radius: molCellStyle.radius, dashed: molCellStyle.dashed, visible: molCellStyle.visible,
        repeat: molCellStyle.repeat.slice(),
        wrapMode: molCellStyle.wrapMode,
        dashLength: molCellStyle.dashLength, gapLength: molCellStyle.gapLength,
        color: molCellStyle.color, labels: molCellStyle.labels,
        axesVisible: molAxisVisible
      },
      axis: {
        radius: molAxisStyle.radius, headRatio: molAxisStyle.headRatio,
        opacity: molAxisStyle.opacity,
        length: molAxisStyle.length, fontFamily: molAxisStyle.fontFamily,
        colors: molAxisStyle.colors.slice()
      },
      measure: {
        fontSize: molMeasureStyle.fontSize, fontColor: molMeasureStyle.fontColor,
        fontFamily: molMeasureStyle.fontFamily,
        lineRadius: molMeasureStyle.lineRadius, lineColor: molMeasureStyle.lineColor,
        lineDashed: molMeasureStyle.lineDashed,
        lineDashLength: molMeasureStyle.lineDashLength, lineGapLength: molMeasureStyle.lineGapLength
      },
      iso: {
        opacity: molIsoOpacity, posValue: molIsoPosValue, negValue: molIsoNegValue,
        posColor: molIsoPosColor, negColor: molIsoNegColor
      },
      gizmoPos: molGizmoPos ? { left: molGizmoPos.left, top: molGizmoPos.top } : null
    },
    atoms: atoms,
    bonds: Object.keys(MC.bondStyles || {}).map(function (key) {
      const s = MC.bondStyles[key];
      return { model: s.model, a: s.a, b: s.b, radius: s.radius,
               color: s.color, style: molBondStyleMode(s), dashed: !!s.dashed,
               baseOrder: s.baseOrder };
    }),
    atomChanges: {
      // 原子移动/删除/改元素在存档时也写回结构文件；structureWritten 标记写回结果。
      moves: Object.keys(MC.atomEdits || {}).map(function (k) {
        const parts = k.split(":"), p = MC.atomEdits[k];
        // MC.atomEdits 恒为笛卡尔坐标(Å)，coord 字段供外部存档/回放明确坐标系。
        return { model: Number(parts[0]), index: Number(parts[1]),
                 x: p.x, y: p.y, z: p.z, coord: "cart" };
      }),
      deletions: Object.keys(MC.atomDeleted || {}).map(function (k) {
        const parts = k.split(":");
        return { model: Number(parts[0]), index: Number(parts[1]) };
      }),
      elements: Object.keys(MC.atomElementChanges || {}).map(function (k) {
        const parts = k.split(":");
        return { model: Number(parts[0]), index: Number(parts[1]), elem: MC.atomElementChanges[k] };
      }),
      additions: (MC.atomAdditions || []).map(function (a) {
        // fx/fy/fz 恒为晶格分数坐标；index 为插入后的原胞序号，便于外部存档回放对齐。
        return { model: a.model || 0, index: a.index, elem: a.elem,
                 fx: a.fx, fy: a.fy, fz: a.fz, coord: "frac" };
      }),
      structureWritten: false
    },
    picks: picks,
    pickBonds: (MC.pickBonds || []).map(function (b) {
      return { model: b.model, a: b.a, b: b.b };
    }),
    measureMode: !!MC.measureMode
  };
}

async function molSaveArchive(anchor) {
  if (!MC.viewer) { toast(tx("尚未打开结构"), true, anchor); return false; }
  const path = molArchivePath(MC.sourcePath || state.viewing || MC.baseName || "structure");
  const stateObj = molCaptureArchive();
  try {
    const editKeys = Object.keys(MC.atomEdits || {});
    const delKeys = Object.keys(MC.atomDeleted || {});
    const addKeys = MC.atomAdditions || [];
    const elemKeys = Object.keys(MC.atomElementChanges || {});
    if ((editKeys.length || delKeys.length || addKeys.length || elemKeys.length) && MC.sourcePath) {
      const moves = editKeys.map(function (k) {
        const parts = k.split(":"); const p = MC.atomEdits[k];
        return { index: Number(parts[1]), x: p.x, y: p.y, z: p.z, coord: "cart" };
      });
      const deletions = delKeys.map(function (k) { return Number(k.split(":")[1]); });
      const elements = elemKeys.map(function (k) {
        const parts = k.split(":");
        return { index: Number(parts[1]), elem: MC.atomElementChanges[k] };
      });
      const additions = addKeys.map(function (a) {
        // 写回接口同样显式声明分数坐标，避免把 f 值当笛卡尔 Å 写进结构文件。
        return { elem: a.elem, index: a.index, fx: a.fx, fy: a.fy, fz: a.fz,
                 coord: "frac" };
      });
      await api("/api/structure/edit", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ path: MC.sourcePath, moves: moves, deletions: deletions,
                               elements: elements, additions: additions,
                               cell: MC.cell ? MC.cell.map(function (v) { return v.slice(); }) : null })
      });
      MC.atomEdits = {}; MC.atomDeleted = {}; MC.atomAdditions = []; MC.atomElementChanges = {};
    MC.atomHistory = { undo: [], redo: [] };
    molSyncAtomEditButtons();
      stateObj.atomChanges.structureWritten = true;
    }
    await api("/api/file", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: path, text: JSON.stringify(stateObj, null, 2)})
    });
    MC.archive = stateObj;
    const mask = maskOf("molView");
    if (mask) clearDirty(mask);
    setMolArchiveEnabled(false);
    toast(tx("已存档") + " " + path, false, anchor);
    return true;
  } catch (err) {
    toast(err.message, true, anchor);
    return false;
  }
}

// 读取存档（读取失败/不存在时静默按默认显示）。
async function molLoadArchive(path) {
  if (!path) return null;
  try {
    const data = await api("/api/file?path=" + q(path));
    if (data && data.kind === "text" && typeof data.text === "string") {
      const arc = JSON.parse(data.text);
      if (arc && arc.format === "mcta-view" && arc.view) return arc;
    }
  } catch (err) { /* 无存档或格式无效：忽略 */ }
  return null;
}

// 把存档中的操作应用到当前已加载的结构上。
function molApplyArchive(arc) {
  if (!arc || !MC.viewer) return;
  const style = arc.style || {};
  const atomChanges = arc.atomChanges || {};
  if (arc.cellOrigin && [arc.cellOrigin.x, arc.cellOrigin.y, arc.cellOrigin.z].every(function (n) {
    return typeof n === "number" && isFinite(n);
  })) MC.cellOrigin = {
    x: arc.cellOrigin.x, y: arc.cellOrigin.y, z: arc.cellOrigin.z
  };
  // 存档可能把键级改成 1.5；先清空基准键级，按当前模型重新记录原键级。
  MC.bondBaseOrders = {};
  if (typeof style.bondRadius === "number") molBondRadius = style.bondRadius;
  if (typeof style.bondColor === "string") molBondColor = style.bondColor;
  if (typeof style.bondDashed === "boolean") molBondDashed = style.bondDashed;
  if (typeof style.bondHidden === "boolean") molBondHidden = style.bondHidden;
  if (typeof style.atomRadius === "number") molAtomRadius = style.atomRadius;
  if (typeof style.atomColor === "string") molAtomColor = style.atomColor;
  if (typeof style.atomsVisible === "boolean") molAtomsVisible = style.atomsVisible;
  if (typeof style.bondsVisible === "boolean") molBondsVisible = style.bondsVisible;
  if (typeof style.depthCue === "number") molDepthCue = style.depthCue;
  const cell = style.cell || {};
  if (typeof cell.radius === "number") molCellStyle.radius = cell.radius;
  if (typeof cell.dashed === "boolean") molCellStyle.dashed = cell.dashed;
  if (typeof cell.visible === "boolean") molCellStyle.visible = cell.visible;
  if (Array.isArray(cell.repeat) && cell.repeat.length === 3) {
    molCellStyle.repeat = [0, 1, 2].map(function (i) {
      const n = Math.round(Number(cell.repeat[i]) || 1);
      return Math.max(1, Math.min(MOL_CELL_REPEAT_MAX, n));
    });
  }
  if (typeof cell.dashLength === "number") molCellStyle.dashLength = cell.dashLength;
  if (typeof cell.gapLength === "number") molCellStyle.gapLength = cell.gapLength;
  if (typeof cell.color === "string") molCellStyle.color = cell.color;
  if (typeof cell.labels === "boolean") molCellStyle.labels = cell.labels;
  if (cell.wrapMode === "inside" || cell.wrapMode === "as-is") molCellStyle.wrapMode = cell.wrapMode;
  if (typeof cell.axesVisible === "boolean") molAxisVisible = cell.axesVisible;
  const axis = style.axis || {};
  ["radius", "headRatio", "opacity", "length"].forEach(function (k) {
    if (typeof axis[k] === "number") molAxisStyle[k] = axis[k];
  });
  if (Array.isArray(axis.colors) && axis.colors.length === 3) molAxisStyle.colors = axis.colors.slice();
  if (typeof axis.fontFamily === "string") molAxisStyle.fontFamily = molNormalizeFontFamily(axis.fontFamily);
  const measure = style.measure || {};
  if (typeof measure.fontSize === "number") molMeasureStyle.fontSize = measure.fontSize;
  if (typeof measure.fontColor === "string") molMeasureStyle.fontColor = measure.fontColor;
  if (typeof measure.fontFamily === "string") molMeasureStyle.fontFamily = molNormalizeFontFamily(measure.fontFamily);
  if (typeof measure.lineRadius === "number") molMeasureStyle.lineRadius = measure.lineRadius;
  if (typeof measure.lineColor === "string") molMeasureStyle.lineColor = measure.lineColor;
  if (typeof measure.lineDashed === "boolean") molMeasureStyle.lineDashed = measure.lineDashed;
  if (typeof measure.lineDashLength === "number") molMeasureStyle.lineDashLength = measure.lineDashLength;
  if (typeof measure.lineGapLength === "number") molMeasureStyle.lineGapLength = measure.lineGapLength;
  const iso = style.iso || {};
  if (typeof iso.posColor === "string") molIsoPosColor = iso.posColor;
  if (typeof iso.negColor === "string") molIsoNegColor = iso.negColor;
  if (typeof iso.opacity === "number") {
    molIsoOpacity = Math.min(1, Math.max(0.05, iso.opacity));
  }
  if (typeof iso.posValue === "number") {
    const f = MOL_STYLE_FIELDS.find(function (x) { return x.key === "IsoPos"; });
    molIsoPosValue = Math.min(f ? f.max : Infinity, Math.max(f ? f.min : 0, iso.posValue));
  }
  if (typeof iso.negValue === "number") {
    const f = MOL_STYLE_FIELDS.find(function (x) { return x.key === "IsoNeg"; });
    molIsoNegValue = Math.min(f ? f.max : Infinity, Math.max(f ? f.min : 0, iso.negValue));
  }
  if (style.gizmoPos && typeof style.gizmoPos.left === "number") {
    molGizmoPos = { left: style.gizmoPos.left, top: style.gizmoPos.top };
  }
  // 恢复全局样式到 viewer（扩胞重建后需再叠加一次全局原子样式）
  molApplyDepthCue();
  molApplyBondRadius();
  molApplyVisibility();
  if (MC.cell) {
    molApplySupercellModel();
    molRedrawCell();
  }
  molApplyGlobalAtomStyle();
  molDrawAxisGizmo();
  molSyncStyleFields();
  if (MC.volume) updateMolIsosurface();
  // 恢复逐原子颜色/大小覆盖
  MC.atomStyles = {};
  (arc.atoms || []).forEach(function (o) {
    if (!Number.isInteger(o.index)) return;
    const sel = { index: o.index };
    if (o.model !== undefined) sel.model = o.model;
    const color = typeof o.color === "string" ? o.color : molDefaultColor("");
    const radius = typeof o.radius === "number" ? o.radius : molDefaultRadius("");
    MC.viewer.addStyle(sel, { sphere: { color: color, radius: radius } });  // sel 不含 frame，跨帧生效
    MC.atomStyles[molAtomKey(sel)] = {
      model: o.model, index: o.index, color: color, radius: radius
    };
  });
  // 恢复逐键颜色/键粗/线型覆盖
  MC.bondStyles = {};
  (arc.bonds || []).forEach(function (o) {
    if (!Number.isInteger(o.a) || !Number.isInteger(o.b)) return;
    const bond = { model: o.model, a: o.a, b: o.b };
    const st = molBondStyle(bond);
    if (typeof o.radius === "number") st.radius = o.radius;
    if (typeof o.color === "string") st.color = o.color;
    if (o.style === "none" || o.style === "solid" || o.style === "dashed") st.style = o.style;
    else st.style = o.dashed ? "dashed" : "solid";
    st.dashed = st.style === "dashed";
    if (typeof o.baseOrder === "number") st.baseOrder = o.baseOrder;
    molApplyBondStyle(bond);
  });
  molRebuildBondPickShapes();
  // 恢复投影与帧
  const view = arc.view || {};
  if (typeof view.ortho === "boolean") molSetProjection(view.ortho);
  if (MC.frames > 0 && Number.isInteger(view.frame)) {
    MC.index = Math.max(0, Math.min(MC.frames - 1, view.frame));
    MC.viewer.setFrame(MC.index);
    $("molRange").value = String(MC.index);
    molLabel();
  }
  // 恢复旋转/平移/缩放
  if (Array.isArray(view.matrix) && view.matrix.length === 8 && MC.viewer.setView) {
    MC.viewer.setView(view.matrix);
  }
  if (Array.isArray(view.lookingAt) && view.lookingAt.length === 3 && MC.viewer.lookingAt) {
    MC.viewer.lookingAt.x = view.lookingAt[0];
    MC.viewer.lookingAt.y = view.lookingAt[1];
    MC.viewer.lookingAt.z = view.lookingAt[2];
    if (MC.viewer.camera && MC.viewer.camera.lookAt) MC.viewer.camera.lookAt(MC.viewer.lookingAt);
  }
  // 恢复标注与测量模式；旧存档没有 measureMode 时按是否存在选中项回退为开启。
  const savedAtoms = Array.isArray(arc.picks) ? arc.picks : [];
  const savedBonds = Array.isArray(arc.pickBonds) ? arc.pickBonds : [];
  MC.measureMode = typeof arc.measureMode === "boolean"
    ? !!arc.measureMode : (savedAtoms.length > 0 || savedBonds.length > 0);
  molSyncMeasureButton();
  MC.pickAtoms = [];
  MC.pickBonds = [];
  if (MC.measureMode) {
    savedAtoms.forEach(function (p) {
      if (!Number.isInteger(p.index)) return;
      let sel = { index: p.index };
      if (p.model !== undefined) sel.model = p.model;
      let atoms = [];
      try { atoms = MC.viewer.selectedAtoms ? MC.viewer.selectedAtoms(sel) : []; } catch (err) { atoms = []; }
      if (atoms && atoms.length) MC.pickAtoms.push(atoms[0]);
    });
    savedBonds.forEach(function (b) {
      if (!Number.isInteger(b.a) || !Number.isInteger(b.b)) return;
      const low = molFindAtomByIndex(b.model, b.a);
      const other = molFindAtomByIndex(b.model, b.b);
      if (low && other) MC.pickBonds.push({ model: b.model, a: b.a, b: b.b });
    });
  }
  // 原子修改：正常存档已写回结构文件，无需重放；若存档来自外部且结构文件未改，则按记录重放。
  if (!atomChanges.structureWritten) {
    MC.historySuspend = true;
    (atomChanges.moves || []).forEach(function (o) {
      if (!Number.isInteger(o.index)) return;
      const pos = { x: Number(o.x) || 0, y: Number(o.y) || 0, z: Number(o.z) || 0 };
      // 旧存档缺省为笛卡尔；若声明分数坐标则按当前晶格换算成笛卡尔后再回放。
      const p = o.coord === "frac" && MC.cell ? molFracToCart([pos.x, pos.y, pos.z], MC.cell) : pos;
      if (!p) return;
      MC.atomEdits[molSelKey(o.model === undefined ? 0 : o.model, o.index)] = p;
    });
    (atomChanges.deletions || []).forEach(function (o) {
      if (!Number.isInteger(o.index)) return;
      MC.atomDeleted[molSelKey(o.model === undefined ? 0 : o.model, o.index)] = true;
    });
    (atomChanges.elements || []).forEach(function (o) {
      if (!o.elem || !Number.isInteger(o.index)) return;
      const sel = { model: o.model === undefined ? 0 : o.model, index: o.index };
      const k = molSelKey(sel.model, sel.index);
      if (MC.atomDeleted[k]) return;
      MC.atomElementChanges[k] = o.elem;
      const a = molCurrentAtom(sel);
      if (!a) return;
      a.elem = o.elem;
      if (a.element !== undefined) a.element = o.elem;
      try {
        MC.viewer.addStyle(molSelectorAllFrames(a), {
          sphere: { color: molDefaultColor(o.elem), radius: molDefaultRadius(o.elem) }
        });
      } catch (err) { /* 忽略 */ }
    });
    (atomChanges.additions || []).forEach(function (o) {
      if (!o.elem || !Number.isFinite(o.fx) || !Number.isFinite(o.fy) || !Number.isFinite(o.fz)) return;
      // 新增记录始终是分数坐标（coord:"frac"）；若将来出现笛卡尔记录则先换算。
      const frac = o.coord === "cart" && MC.cell
        ? molCartToFrac({ x: o.fx, y: o.fy, z: o.fz }, MC.cell) : [o.fx, o.fy, o.fz];
      if (!frac) return;
      molAddAtomToModel(o.elem, frac, true);
    });
    if (Object.keys(MC.atomEdits).length || Object.keys(MC.atomDeleted).length ||
        Object.keys(MC.atomElementChanges).length || (atomChanges.additions || []).length) {
      molRedrawSelection();
    }
    MC.historySuspend = false;
  }
  molDrawMeasure();
  MC.viewer.render();
  molDrawAxisGizmo();
}

function molVolumeHasThreshold(sign, threshold) {
  const data = MC.volume && MC.volume.data;
  if (!data || !data.length) return false;
  for (let i = 0; i < data.length; i++) {
    if (sign > 0 ? data[i] >= threshold : data[i] <= -threshold) return true;
  }
  return false;
}
function updateMolIsosurface() {
  if (!MC.viewer || !MC.volume) return;
  [MC.isoShape, MC.isoNegShape].forEach(function (shape) {
    if (shape) MC.viewer.removeShape(shape);
  });
  MC.isoShape = null;
  MC.isoNegShape = null;
  const opacity = Number(molIsoOpacity);
  const posval = Math.abs(Number(molIsoPosValue));
  const negval = Math.abs(Number(molIsoNegValue));
  if (!Number.isFinite(opacity) || !Number.isFinite(posval) || !Number.isFinite(negval)) return;
  const base = { opacity: opacity, clickable: true, contextMenuEnabled: true };
  if (posval > 0 && molVolumeHasThreshold(1, posval)) {
    MC.isoShape = MC.viewer.addIsosurface(MC.volume, Object.assign({}, base, {
      isoval: posval, color: molIsoPosColor
    }));
    if (MC.isoShape) MC.isoShape._mctaIsoSign = 1;
  }
  if (negval > 0 && molVolumeHasThreshold(-1, negval)) {
    MC.isoNegShape = MC.viewer.addIsosurface(MC.volume, Object.assign({}, base, {
      isoval: -negval, color: molIsoNegColor
    }));
    if (MC.isoNegShape) MC.isoNegShape._mctaIsoSign = -1;
  }
  MC.viewer.render();
  molMarkViewDirty();
}

function configureMolDensity(data) {
  MC.volume = null;
  MC.isoShape = null;
  MC.isoNegShape = null;
  closeMolDensityPanels();
  $("molDensityGroup").classList.add("hidden");
  molSyncExtraCtl();
  const groups = data.densities;
  if (!Array.isArray(groups) || !groups.length) return;
  setMolDensityKindItems(groups, 0);
  MC.volumeGroups = groups.map(function (g) {
    return {
      volume: new $3Dmol.VolumeData(g.cube, "cube"),
      options: g.options,
    };
  });
  switchMolDensityGroup(0);
  $("molDensityGroup").classList.remove("hidden");
  molSyncExtraCtl();
}

function switchMolDensityGroup(index) {
  if (!MC.volumeGroups || !MC.volumeGroups[index]) return;
  MC.volume = MC.volumeGroups[index].volume;
  const options = MC.volumeGroups[index].options || {};
  const step = Math.max(Number(options.step) || 0, 1e-6);
  const posMax = Math.max(step, Number(options.max) || 0);
  const negMax = Math.max(step, -(Number(options.min) || 0));
  const raw = Math.abs(Number(options.value) || 0);
  const posDefault = Math.min(posMax, Math.max(step, raw || step));
  const negDefault = Math.min(negMax, Math.max(step, raw || step));
  molIsoOpacity = MOL_ISO_OPACITY_DEFAULT;
  molIsoPosValue = posDefault;
  molIsoNegValue = negDefault;
  const posField = MOL_STYLE_FIELDS.find(function (f) { return f.key === "IsoPos"; });
  const negField = MOL_STYLE_FIELDS.find(function (f) { return f.key === "IsoNeg"; });
  if (posField) {
    posField.min = step; posField.max = posMax; posField.step = step;
    posField.def = posDefault;
  }
  if (negField) {
    negField.min = step; negField.max = negMax; negField.step = step;
    negField.def = negDefault;
  }
  molSyncStyleFields();
  updateMolIsosurface();
  molSyncAtomEditButtons();
  molFillAtomPanel();
}

function closeMolDensityPanels() {
  document.querySelectorAll(".mol-density-panel.show").forEach(function (p) {
    p.classList.remove("show");
  });
  document.querySelectorAll(".mol-density-pop.active").forEach(function (b) {
    b.classList.remove("active");
  });
}

function setMolPlayerVisible(on) {
  $("molPlayer").classList.toggle("hidden", !on);
  molSyncExtraCtl();
}

function closeStructure() {
  cancelMolLoad();
  clearDirty($("molView"));
  setMolArchiveEnabled(false);
  stopMolPlay();
  molClearBondPickShapes();
  molHidePickPanel();
  molHideAtomPanel();
  if (MC.saveJob) closeMolSave();
  resetModalMax($("molView"));
  MC.frames = 0;
  MC.index = 0;
  MC.home = null;
  MC.baseName = "";
  MC.volume = null;
  MC.isoShape = null;
  MC.isoNegShape = null;
  MC.volumeGroups = null;
  closeMolDensityPanels();
  $("molDensityGroup").classList.add("hidden");
  setMolPlayerVisible(false);
  molSyncAtomEditButtons();
  if (MC.viewer) {
    try { MC.viewer.clear(); } catch (err) { /* 忽略 */ }
    MC.viewer = null;
  }
  molClearMolCanvas($("molCanvas"));
  $("molView").classList.add("hidden");
  MC = freshMolCtx();
  molSyncPanButton();
  molSyncMeasureButton();
  activeMask = null;
  if (!anyViewerOpen() && state.viewing) state.viewing = null;
}

// 左键平移开关：捕获阶段接管拖动，避免 3Dmol 同时旋转。
// 长按 500ms 与右键等价：坐标轴 / 原子 / 键 / 空白都打开对应弹窗。
function molBindViewControls(host) {
  if (!host || host._mctaPanLongPress) return;
  host._mctaPanLongPress = true;
  let panDrag = null, press = null, selDrag = null, midDrag = null;
  let shortcutGuardTimer = null;
  host.addEventListener("pointerdown", function (ev) {
    // Shift+中键拖动用于移动选中原子；阻止中键自动滚动。
    if (ev.button === 1) {
      if (!ev.shiftKey || !(MC.selectedAtoms || []).length) return;
      ev.preventDefault(); ev.stopPropagation();
      midDrag = { cx: ev.clientX, cy: ev.clientY, before: molAtomCoordSnapshots() };
      try { host.setPointerCapture(ev.pointerId); } catch (err) {}
      return;
    }
    if (ev.button !== 0) return;
    if (ev.target && ev.target.closest && ev.target.closest(".zoom-ctl")) return;
    // Shift+左键框选、Ctrl(⌘)+左键点选都可直接选中原子，无需先进入按钮模式；
    // 这两种方式只高亮，不新建“原子坐标”弹窗。按钮模式下的普通点击仍会弹出弹窗。
    const shortcut = !!(ev.shiftKey || ev.ctrlKey || ev.metaKey);
    if (MC.selectMode || shortcut) {
      const box = !!ev.shiftKey;
      selDrag = { x: ev.pageX, y: ev.pageY, cx: ev.clientX, cy: ev.clientY,
                  dragging: false, box: box, shortcut: shortcut,
                  additive: !!(ev.ctrlKey || ev.metaKey) };
      if (box || shortcut) {
        ev.preventDefault(); ev.stopPropagation();
        try { host.setPointerCapture(ev.pointerId); } catch (err) {}
      }
      if (shortcut) {
        // 吞掉这次点击附带的 3Dmol 测量拾取，与按钮模式行为一致。
        MC.longPressHandled = true;
        clearTimeout(shortcutGuardTimer);
        shortcutGuardTimer = setTimeout(function () { MC.longPressHandled = false; }, 5000);
      }
      return;
    }
    if (MC.leftPan) {
      ev.preventDefault();
      ev.stopPropagation();
      panDrag = { x: ev.clientX, y: ev.clientY };
      try { host.setPointerCapture(ev.pointerId); } catch (err) {}
    }
    press = {
      x: ev.clientX, y: ev.clientY,
      pageX: ev.pageX, pageY: ev.pageY,
      target: ev.target,
      timer: setTimeout(function () {
        if (!press) return;
        MC.longPressHandled = true;
        // 长按之后浏览器会在 pointerup 再补一个 click；文档级“点击外部关闭弹窗”
        // 会把它当成普通点击而立刻关掉刚打开的菜单，这里先标记并吞掉那一次 click。
        MC.longPressClickGuard = true;
        panDrag = null;
        molOpenContextHere({
          target: press.target,
          clientX: press.x, clientY: press.y,
          pageX: press.pageX, pageY: press.pageY,
          preventDefault: function () {}, stopPropagation: function () {}
        });
        setTimeout(function () { MC.longPressHandled = false; }, 400);
        press = null;
      }, 500)
    };
  }, true);
  host.addEventListener("pointermove", function (ev) {
    if (midDrag) {
      ev.preventDefault(); ev.stopPropagation();
      molMoveSelectedByPixels(ev.clientX - midDrag.cx, ev.clientY - midDrag.cy, true);
      midDrag.cx = ev.clientX; midDrag.cy = ev.clientY;
      return;
    }
    if (selDrag) {
      if (Math.abs(ev.pageX - selDrag.x) > 4 || Math.abs(ev.pageY - selDrag.y) > 4) selDrag.dragging = true;
      if (selDrag.box) {
        ev.preventDefault(); ev.stopPropagation();
        if (selDrag.dragging) molSelectionBox(host, selDrag, ev);
      }
      return;
    }
    if (panDrag && MC.leftPan) {
      ev.preventDefault();
      ev.stopPropagation();
      const dx = ev.clientX - panDrag.x;
      const dy = ev.clientY - panDrag.y;
      panDrag.x = ev.clientX;
      panDrag.y = ev.clientY;
      if (MC.viewer && typeof MC.viewer.translateScene === "function") {
        MC.viewer.translateScene(dx, dy);
        MC.viewer.render();
        molDrawAxisGizmo();
        molRevealZoomCtl();
        molMarkViewDirty();
      }
    }
    if (press && (Math.abs(ev.clientX - press.x) > 8 || Math.abs(ev.clientY - press.y) > 8)) {
      clearTimeout(press.timer);
      press = null;
    }
  }, true);
  ["pointerup", "pointercancel"].forEach(function (name) {
    host.addEventListener(name, function (ev) {
      if (midDrag) {
        molPushTransformHistory(midDrag.before);
        midDrag = null;
        if (MC.viewer) MC.viewer.render();
        return;
      }
      if (selDrag) {
        const d = selDrag; selDrag = null;
        molRemoveSelectionBox(host);
        if (d.shortcut) {
          clearTimeout(shortcutGuardTimer);
          shortcutGuardTimer = null;
          setTimeout(function () { MC.longPressHandled = false; }, 0);
        }
        if (name === "pointerup") {
          const opts = d.shortcut
            ? { silent: !MC.selectMode, additive: d.additive } : undefined;
          if (d.box && d.dragging) molBoxSelect(d, ev, opts);
          else if (!d.dragging) molClickSelect(ev, opts);
          // 普通左键拖动已交给 3Dmol 旋转视图，这里不处理选中。
        }
        return;
      }
      panDrag = null;
      if (press) { clearTimeout(press.timer); press = null; }
      if (name === "pointerup") {
        // click 仍在本次事件循环里派发；若长按没有补 click，兜底在下一轮清掉标记。
        if (MC.longPressClickGuard) setTimeout(function () { MC.longPressClickGuard = false; }, 0);
      } else {
        MC.longPressClickGuard = false;
      }
    }, true);
  });
}

function molDelay(ms, signal) {
  return new Promise(function (resolve, reject) {
    if (signal && signal.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    const timer = setTimeout(resolve, ms);
    if (signal) {
      signal.addEventListener("abort", function () {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }
  });
}

async function molLoadFullTrajectory(path, loadSeq, controller, anchor) {
  try {
    const full = await api("/api/structure?path=" + q(path) + "&frames=1",
                           undefined, controller ? controller.signal : undefined);
    if (loadSeq !== molLoadSeq || !MC.viewer || !full.xyz) return;
    const view = MC.viewer.getView();
    const look = MC.viewer.lookingAt ? MC.viewer.lookingAt.clone() : null;
    MC.viewer.clear();
    MC.viewer.addModelsAsFrames(full.xyz, "xyz");
    molApplyDefaultAtomStyle();
    if (full.cell) MC.cellShapes = drawMolCell(full.cell);
    MC.viewer.setFrame(Math.min(MC.index || 0, (full.nframes || 1) - 1));
    if (view) MC.viewer.setView(view);
    if (look && MC.viewer.lookingAt) MC.viewer.setLookingAt(look);
    molApplyGlobalAtomStyle();
    molApplyBondRadius();
    molApplyVisibility();
    MC.viewer.render();
    molRebuildBondPickShapes();
    const loaded = molViewerModels();
    if (loaded.length && MC.cell) {
      const lm = loaded[0];
      MC.sourceFrames = (lm.frames && lm.frames.length) ? lm.frames.slice() : [lm.atoms || []];
      molApplySupercellModel();
      MC.viewer.render();
    }
    toast(tx("完整轨迹已加载"), false, anchor);
  } catch (err) {
    if (err && err.name === "AbortError") return;
    // 后台补全失败不影响已显示的首帧，不弹错误打断用户操作。
  }
}

async function openStructure(path, anchor) {
  // 取消尚未完成的加载；切换文件/关闭窗口后，旧响应到达时由序号拦截。
  cancelMolLoad();
  const loadSeq = molLoadSeq;
  const controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
  molLoadAbort = controller;
  const mask = acquireMask("molView", "view:" + path);
  mask.dataset.dockTag = "3D";
  setMolArchiveEnabled(false);
  const loadBadge = $("molLoading");
  const cancelBtn = $("molCancelLoad");
  if (loadBadge) { loadBadge.textContent = tx("正在渲染…"); loadBadge.classList.remove("hidden"); }
  if (cancelBtn) {
    cancelBtn.title = tx("取消加载");
    cancelBtn.setAttribute("aria-label", tx("取消加载"));
    cancelBtn.classList.remove("hidden");
    cancelBtn.onclick = function () { cancelMolLoad(); toast(tx("已取消加载")); };
  }
  if (typeof $3Dmol === "undefined") {
    toast("3Dmol 资源未加载，无法显示结构", true, anchor);
    return;
  }
  if (!hasWebGL()) {
    toast("当前浏览器不支持 WebGL，无法显示 3D 结构", true, anchor);
    return;
  }
  try {
    const host = $("molCanvas");
    let data = null;
    let partialTrajectory = false;
    let attempt = 0;
    while (true) {
      try {
        // 首屏只取 1 帧：大轨迹不必等完整 JSON 下载/解析完就能出画面。
        data = await api("/api/structure?path=" + q(path) + "&frames=1&limit=1",
                         undefined, controller ? controller.signal : undefined);
        break;
      } catch (err) {
        if (!err || err.status !== 429 || attempt >= 3 ||
            (controller && controller.signal.aborted)) throw err;
        attempt += 1;
        if (loadBadge) loadBadge.textContent = tx("排队中，稍后重试…");
        await molDelay((err.retryAfter || 2) * 1000,
                       controller ? controller.signal : null);
        if (loadSeq !== molLoadSeq) return;
      }
    }
    if (loadBadge) loadBadge.classList.add("hidden");
    if (cancelBtn) cancelBtn.classList.add("hidden");
    if (loadSeq !== molLoadSeq) return;  // 已被更新的请求取代
    state.viewing = path;
    MC.sourcePath = path;
    const many = (data.nframes || 1) > 1;
    $("molName").textContent = data.name + " · " + data.formula + " · " + fmtSize(data.size) + " · " + data.mtime;
    stopMolPlay();
    MC.frames = many ? data.nframes : 0;
    MC.index = 0;
    MC.cell = data.cell || null;
    MC.cellOrigin = { x: 0, y: 0, z: 0 };
    MC.atomStyles = {};
    MC.archive = null;
    MC.selectMode = false; MC.selectedAtoms = []; MC.selectShapes = []; MC.selectStyles = {};
    molHideAtomPanel();
    MC.atomEdits = {}; MC.atomDeleted = {}; MC.atomAdditions = []; MC.atomElementChanges = {};
    MC.atomHistory = { undo: [], redo: [] };
    molSyncAtomEditButtons();
    molClearMeasure(true);
    molHidePickPanel();
    $("molView").classList.remove("hidden");
    if (MC.viewer) {
      try { MC.viewer.clear(); } catch (err) { /* 忽略 */ }
      MC.viewer = null;
    }
    molClearMolCanvas(host);
    await new Promise(function (resolve) { requestAnimationFrame(resolve); });
    if (loadSeq !== molLoadSeq) return;
    // upscale:false：让画布后备像素 = CSS 尺寸 × 真实 devicePixelRatio，
    // 与屏幕物理像素 1:1 对应；3Dmol 默认的 upscale 会强制按 2 倍渲染，
    // 在 125%/150% 缩放屏上被非整数缩小，边缘会发虚。
    MC.viewer = $3Dmol.createViewer($("molCanvas"),
      { backgroundAlpha: 0, antialias: true, upscale: false, orthographic: true });
    // 视图变化（拖拽/按钮旋转/复位）时同步重画左上角坐标轴指示器。
    if (MC.viewer.setViewChangeCallback) {
      MC.viewer.setViewChangeCallback(function () { molDrawAxisGizmo(); });
    }
    // 深度雾强度由“样式设置”弹窗控制（0 关闭，1 最强）
    molApplyDepthCue();
    molSetProjection(true);
    if (many) {
      // 多帧轨迹：把全部帧放进同一个 model，setFrame 才能逐帧切换。
      // partial 时首屏只有 1 帧，先用 cif 出画面，完整轨迹在后台补齐。
      partialTrajectory = !!data.partial;
      if (partialTrajectory) MC.viewer.addModel(data.cif, "cif");
      else MC.viewer.addModelsAsFrames(data.xyz, "xyz");
      molApplyDefaultAtomStyle();
      if (data.cell) MC.cellShapes = drawMolCell(data.cell);
      MC.viewer.setFrame(0);
      $("molRange").max = String(MC.frames - 1);
      setMolPlayerVisible(true);
      molLabel();
    } else {
      const model = MC.viewer.addModel(data.cif, "cif");
      MC.structureModel = model;
      molApplyDefaultAtomStyle();
      if (data.cell) MC.cellShapes = drawMolCell(data.cell);
      setMolPlayerVisible(false);
    }
    // 若设置了全局原子大小/颜色，覆盖到新载入的结构（逐原子样式已在上面清空）。
    molApplyGlobalAtomStyle();
    // 保存原胞各帧作为扩胞基准，再按当前超晶胞数生成原生扩胞模型。
    const loaded = molViewerModels();
    if (loaded.length && MC.cell) {
      const lm = loaded[0];
      MC.sourceFrames = (lm.frames && lm.frames.length) ? lm.frames.slice() : [lm.atoms || []];
      molApplySupercellModel();
    }
    // 沿用用户设定的键粗（键型固定为原生 stick）
    molApplyBondRadius();
    molApplyVisibility();
    MC.viewer.zoomTo();
    MC.viewer.setClickable({}, true, molOnAtomClick);
    configureMolDensity(data);
    molSyncAtomEditButtons();
    // 记录“未应用任何存档”的初始相机，供“重置”回到无 json 的初始状态。
    // 必须在读取 _mcta.json 之前捕获，否则 home 会变成存档里的视图。
    MC.home = {
      view: MC.viewer.getView(),
      look: MC.viewer.lookingAt ? MC.viewer.lookingAt.clone() : null
    };
    MC.baseName = data.name || "structure";
    // 打开结构时先看同目录有无 <完整文件名>_mcta.json 存档；有则恢复其中记录的操作。
    const arc = await molLoadArchive(molArchivePath(path));
    if (loadSeq !== molLoadSeq) return;
    if (arc) {
      MC.archive = arc;
      molApplyArchive(arc);
    } else {
      MC.viewer.render();
      molDrawAxisGizmo();
    }
    molEnsureZoomCtl();
    molSyncZoomCtl();
    molRebuildBondPickShapes();
    // 加载阶段的样式/投影调用不算“视图调整”；此处开始记录用户改动。
    MC.viewDirtyArmed = true;
    if (!host._mctaViewDirty) {
      host._mctaViewDirty = true;
      host.addEventListener("pointerdown", function (ev) {
        if (ev.button !== 0 && ev.button !== 1) return;  // 左键旋转、中键平移都算视图调整
        if (ev.target && ev.target.closest && ev.target.closest(".mol-axis-gizmo")) return;
        molMarkViewDirty();
      }, true);
    }
    // 滚轮方向与 3Dmol 默认相反：向前滚缩小、向后滚放大。
    // 在容器上以捕获阶段拦截并阻止冒泡，屏蔽 3Dmol 绑定在画布上的滚轮处理。
    if (!host._mctaWheel) {
      host._mctaWheel = true;
      host.addEventListener("wheel", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!MC.viewer) { return; }
        molRevealZoomCtl();
        const cam = MC.viewer.rotationGroup.position;
        const span = 0.85 * (MC.viewer.CAMERA_Z - cam.z);
        const tick = Math.min(Math.abs(ev.deltaY) || 100, 300);
        cam.z += (ev.deltaY < 0 ? 1 : -1) * span * tick / 400;
        cam.z = MC.viewer.adjustZoomToLimits(cam.z);
        MC.viewer.show();
        molSyncZoomCtl();
        molMarkViewDirty();
      }, { passive: false, capture: true });
    }
    // 右键：命中原子打开原子样式、键打开键样式、坐标轴打开轴设置、空白处打开样式设置。
    if (!host._mctaContextMenu) {
      host._mctaContextMenu = true;
      host.addEventListener("contextmenu", molOpenContextHere);
    }
    molBindViewControls(host);
    if (partialTrajectory) {
      molLoadFullTrajectory(path, loadSeq, controller, anchor);
    }
  } catch (err) {
    if (loadBadge) loadBadge.classList.add("hidden");
    if (cancelBtn) cancelBtn.classList.add("hidden");
    if (err && err.name === "AbortError") return;  // 被新请求取消，无需提示
    if (loadSeq !== molLoadSeq) return;
    toast(err.message, true, anchor);
    closeStructure();
  }
}

function b64encode(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach(function (b) { binary += String.fromCharCode(b); });
  return btoa(binary);
}

function b64decode(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) { bytes[i] = binary.charCodeAt(i); }
  return bytes;
}

function termCellSize() {
  // 用 xterm 自己测得的单元格尺寸，避免硬编码字符宽高导致右侧/底端留下空隙。
  if (state.term && state.term._core && state.term._core._renderService) {
    const d = state.term._core._renderService.dimensions;
    if (d && d.css && d.css.cell && d.css.cell.width > 0 && d.css.cell.height > 0) {
      return {w: d.css.cell.width, h: d.css.cell.height};
    }
  }
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  ctx.font = '13px ui-monospace, Consolas, "Courier New", monospace';
  return {w: ctx.measureText("M").width || 8.2, h: 15.6};
}

function termPadding(box) {
  const cs = window.getComputedStyle(box);
  return {
    x: (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0),
    y: (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0)
  };
}

function termViewport() {
  if (!state.term || !state.term.element) return null;
  return state.term.element.querySelector(".xterm-viewport");
}

function termScrollbarWidth() {
  const vp = termViewport();
  if (vp && vp.offsetWidth > vp.clientWidth) return vp.offsetWidth - vp.clientWidth;
  // 首次渲染还没有 viewport 时用同款细滚动条宽度兜底。
  return 8;
}

function termSize() {
  const box = $("termBox");
  const pad = termPadding(box);
  const cell = termCellSize();
  // 视口占满内容区，滚动条在右边缘；列数按「去掉滚动条后的可用宽度」算，
  // 否则字符会压到滚动条下面导致它无法拖动。
  const sb = termScrollbarWidth();
  const cols = Math.max(20, Math.floor((box.clientWidth - pad.x - sb) / cell.w));
  const rows = Math.max(10, Math.floor((box.clientHeight - pad.y) / cell.h));
  return {cols: cols, rows: rows, cell: cell, sb: sb};
}

// 视口贴右边缘，只把字符网格在可用区域内居中：左右留白相等，
// 右边距是「字符到滚动条」而不是「字符到浮窗边缘」。
function centerTermGrid(size) {
  if (!state.term || !state.term.element) return;
  const box = $("termBox");
  const pad = termPadding(box);
  const el = state.term.element;
  el.style.marginLeft = "0";
  el.style.marginTop = "0";
  el.style.width = "100%";
  el.style.height = "100%";
  const screen = el.querySelector(".xterm-screen");
  if (!screen) return;
  const cell = size.cell || termCellSize();
  const sb = size.sb != null ? size.sb : termScrollbarWidth();
  const availW = Math.max(0, box.clientWidth - pad.x - sb);
  const availH = Math.max(0, box.clientHeight - pad.y);
  const mx = Math.max(0, (availW - size.cols * cell.w) / 2);
  const my = Math.max(0, (availH - size.rows * cell.h) / 2);
  screen.style.marginLeft = mx + "px";
  screen.style.marginTop = my + "px";
}

function relFromBase(cwd, base) {
  if (!cwd || !base) return null;
  if (cwd === base) return "";
  const prefix = base.charAt(base.length - 1) === "/" ? base : base + "/";
  if (cwd.indexOf(prefix) !== 0) return null;
  return cwd.slice(prefix.length);
}

async function syncCwd() {
  if (!state.term) return;
  try {
    const data = await api("/api/term/cwd");
    if (!data.cwd || data.cwd === state.lastCwd) return;
    state.lastCwd = data.cwd;
    // 终端可以进入任意目录（如 /mnt/d）；服务端按终端 cwd 放行。
    if (data.cwd !== state.cwd) await load(data.cwd, true);
  } catch (err) { /* 忽略路径同步错误 */ }
}

// 把路径输入框的内容变成真实目录：先让终端 cd（保持页面与终端同步），
// 再交给 syncCwd 刷新列表；终端不可用时直接请求。
function sendTermInput(text) {
  if (!state.term) return Promise.reject(new Error("终端未连接"));
  return api("/api/term/input", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({data: b64encode(text), sid: SESSION_ID})
  });
}

// 页面切换目录前，先清掉终端里已输入但尚未回车的内容。
// Ctrl+E 跳到行尾、Ctrl+U 清掉整行；与 cd 同批发送，避免清行后被当成新输入残留。
function sendTermCd(target) {
  const quoted = "'" + String(target).replace(/'/g, "'\\''") + "'";
  return sendTermInput("\u0005\u0015cd " + quoted + "\n");
}

// 规整为绝对路径：相对输入基于当前显示的目录，去掉多余的 /、.、..。
function absNormPath(raw, base) {
  let p = String(raw || "").trim().replace(/\\/g, "/");
  if (!p) return "";
  if (p.charAt(0) !== "/") p = (base || "/").replace(/\/+$/, "") + "/" + p;
  const segs = [];
  p.split("/").forEach(function (s) {
    if (!s || s === ".") return;
    if (s === "..") { segs.pop(); return; }
    segs.push(s);
  });
  return "/" + segs.join("/");
}

// 点击“进入”或回车：空输入或与当前目录一致则不动作；否则让终端 cd，
// 由 syncCwd 跟随刷新。无效路径 cd 会失败，cwd 不变，页面自然不切换。
function navigateToPath(raw) {
  const el = $("pathNote");
  const old = el ? (el.dataset.label || "") : "";
  const base = absNormPath(old || state.cwd, "/");
  const target = absNormPath(raw, base);
  if (!target || target === base) {
    if (el) el.value = old;
    return false;
  }
  // 先还原输入框：有效路径会在 cwd 跟随刷新时更新为新的目录，
  // 无效路径则 cd 失败、cwd 不变，输入框保持当前路径（点击无效）。
  if (el) el.value = old;
  sendTermCd(target).catch(function () { load(target, true); });
  return true;
}

(function initPathInput() {
  const el = $("pathNote");
  const btn = $("pathGo");
  if (!el) return;
  function restore() { el.value = el.dataset.label || ""; }
  function submit() { navigateToPath(el.value); }
  el.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") {
      ev.preventDefault();
      submit();
      this.blur();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      restore();
      this.blur();
    }
  });
  el.addEventListener("blur", restore);
  if (btn) {
    // 阻止按钮抢焦点，避免 blur 先把输入还原成旧路径。
    btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    btn.addEventListener("click", submit);
  }
})();

// ---- 3D 工具栏绑定（从 app.js 迁入，依赖 viewer 函数）----
$("btnMolClose").onclick = closeStructureWithConfirm;
$("molProj").onclick = function () { molSetProjection(!MC.ortho); };
// ↑ 下载按钮：将当前结构文件下载到电脑；保存图片到电脑是左侧独立按钮。
$("molSave").onclick = function () {
  const p = MC.sourcePath || state.viewing || "";
  if (p) downloadFile(p);
  else toast(tx("尚未打开结构"), true, this);
};
$("molSaveImage").onclick = openMolSave;
$("molArchive").onclick = function () { molSaveArchive(this); };
$("molSaveOk").onclick = confirmMolSave;
$("molSaveCancel").onclick = closeMolSave;
$("molFormat").onchange = syncMolSaveName;
$("molScale").onchange = syncMolSaveName;
$("molSaveName").onkeydown = function (ev) {
  if (ev.key === "Enter") { ev.preventDefault(); confirmMolSave(); }
  else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeMolSave(); }
};
$("molZoomIn").onclick = function () { molZoom(true); };
$("molZoomOut").onclick = function () { molZoom(false); };
$("molSelectAtoms").onclick = function (ev) {
  ev.stopPropagation();
  MC.selectMode = !MC.selectMode;
  if (MC.selectMode) {
    MC.measureMode = false;
    molSyncMeasureButton();
    molClearMeasure(true);
    MC.selectedAtoms = [];
    molClearSelectionShapes();
  } else {
    MC.selectedAtoms = [];
    molClearSelectionShapes();  // 同时恢复选中前原子样式
    molApplyHiddenAtoms();      // 恢复样式后重新隐藏已删除/已移动的原子
    if (MC.viewer) MC.viewer.render();
  }
  molHideAddPanel();
  molSyncSelectButton();
};
$("molAddAtom").onclick = function (ev) { ev.stopPropagation(); molOpenAddPanel(ev); };
$("molUndoEdit").onclick = function (ev) { ev.stopPropagation(); molUndoAtomEdit(); };
$("molRedoEdit").onclick = function (ev) { ev.stopPropagation(); molRedoAtomEdit(); };
(function () {
  const tableBtn = $("molAddTableBtn");
  if (tableBtn) tableBtn.onclick = function (ev) {
    ev.stopPropagation();
    const panel = $("molPeriodicPanel");
    if (panel && !panel.classList.contains("hidden")) molHidePeriodicPanel();
    else molOpenPeriodicPanel(ev);
  };
  const periodic = $("molPeriodicPanel");
  if (periodic) periodic.onclick = function (ev) { ev.stopPropagation(); };
  const confirm = $("molAddConfirm");
  if (confirm) confirm.onclick = function (ev) { ev.stopPropagation(); molSubmitAddAtom(); };
  const input = $("molAddElem");
  if (input) input.onkeydown = function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); molSubmitAddAtom(); }
    else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); molHideAddPanel(); }
  };
})();
document.addEventListener("keydown", function (ev) {
  if (!MC) return;
  const tag = ev.target && ev.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (ev.key === "Delete" || ev.key === "Backspace") {
    if (!(MC.selectedAtoms || []).length) return;
    ev.preventDefault(); molDeleteSelected(); return;
  }
  const arrows = { ArrowLeft: 1, ArrowRight: 1, ArrowUp: 1, ArrowDown: 1 };
  if (!arrows[ev.key]) return;
  ev.preventDefault();
  const host = $("molCanvas");
  const cw = (host && host.clientWidth) || window.innerWidth || 800;
  const ch = (host && host.clientHeight) || window.innerHeight || 600;
  const sx = Math.max(12, Math.round(cw * 0.04));
  const sy = Math.max(12, Math.round(ch * 0.04));
  let dx = 0, dy = 0;
  if (ev.key === "ArrowLeft") dx = -sx;
  else if (ev.key === "ArrowRight") dx = sx;
  else if (ev.key === "ArrowUp") dy = -sy;
  else dy = sy;
  const isX = ev.key === "ArrowUp" || ev.key === "ArrowDown";
  const sign = ev.key === "ArrowUp" || ev.key === "ArrowLeft" ? 1 : -1;

  if (ev.shiftKey) {
    // Shift 系列只作用于选中的原子；没有选中原子时忽略。
    if (!(MC.selectedAtoms || []).length) return;
    if (ev.altKey) {
      // Shift+Alt+方向键：选中原子在屏幕内移动（步长与视角平移一致）。
      molMoveSelectedByPixels(dx, dy);
    } else {
      // Shift+方向键：选中原子绕屏幕坐标轴旋转，上/下绕 x 轴、左/右绕 y 轴。
      const rad = getMolAngle() * Math.PI / 180;
      if (isX) molRotateSelectedScreenX(sign * rad);
      else molRotateSelectedScreenY(sign * rad);
    }
    return;
  }

  if (ev.altKey) {
    // Alt+方向键：平移视角，与按住鼠标中键拖动一致，只移动相机。
    if (MC.viewer && typeof MC.viewer.translateScene === "function") {
      MC.viewer.translateScene(dx, dy);
      MC.viewer.render();
      molDrawAxisGizmo();
      molRevealZoomCtl();
      molMarkViewDirty();
    }
    return;
  }

  // 方向键：旋转视角，上/下绕 x 轴、左/右绕 y 轴，角度取工具栏设定值。
  molRotateViewScreen(isX ? "x" : "y", sign);
});
molSyncSelectButton();
molBuildPeriodicTable();
molSyncAtomEditButtons();
$("molRotL").onclick = function (ev) { ev.stopPropagation(); molRotate(1); };
$("molRotR").onclick = function (ev) { ev.stopPropagation(); molRotate(-1); };
function molSyncPanButton() {
  const btn = $("molPanToggle");
  if (!btn) return;
  MC.leftPan = !!MC.leftPan;
  btn.classList.toggle("active", MC.leftPan);
  btn.setAttribute("aria-pressed", MC.leftPan ? "true" : "false");
  const label = MC.leftPan ? "左键平移（已开启）" : "左键平移";
  btn.title = tx(label);
  btn.setAttribute("aria-label", btn.title);
}
$("molPanToggle").onclick = function () {
  MC.leftPan = !MC.leftPan;
  molSyncPanButton();
};
molEnsureZoomCtl();
molSyncZoomCtl();
molSyncPanButton();
$("molMeasureToggle").onclick = function () {
  MC.measureMode = !MC.measureMode;
  molSyncMeasureButton();
  // 关闭只阻止新的左键测量拾取；已有元素标签/距离/角度保留，仍可点“清除选中”清除。
  molMarkViewDirty();
};
molSyncMeasureButton();
// 等值面设置弹窗字段的实时更新（rAF 节流）
let molDensityUpdateScheduled = false;
function scheduleMolDensityUpdate() {
  if (molDensityUpdateScheduled) return;
  molDensityUpdateScheduled = true;
  requestAnimationFrame(function () {
    molDensityUpdateScheduled = false;
    updateMolIsosurface();
  });
}

$("molReset").onclick = resetMolView;
$("molFit").onclick = molFitToView;
$("molPickClear").onclick = function () { molClearMeasure(); };
$("molPickColor").oninput = molApplyAtomStyle;
molAttachColorEditor($("molPickColor"), molApplyAtomStyle);
$("molPickSize").oninput = function () { molApplyAtomStyle(); };
$("molPickSizeRange").oninput = function () {
  const num = $("molPickSize");
  if (num) num.value = this.value;
  molApplyAtomStyle();
};
$("molPickSizeBtn").onclick = function () { molToggleNumPop("molPickSize", this); };
$("molPickReset").onclick = molResetPickSettings;
molSyncClearButton();
// 点击外部关闭密度类型下拉（等值面/透明度已移入设置弹窗）
document.addEventListener("click", function (ev) {
  if (!ev.target.closest(".mol-dd")) {
    document.querySelectorAll(".mol-dd.open").forEach(function (d) { d.classList.remove("open"); });
  }
});
$("molPlay").onclick = function () {
  if (MC.timer) { stopMolPlay(); return; }
  startMolPlay();
};
$("molPrev").onclick = function () { stopMolPlay(); showMolFrame(MC.index - 1); };
$("molNext").onclick = function () { stopMolPlay(); showMolFrame(MC.index + 1); };
$("molRange").oninput = function () { stopMolPlay(); showMolFrame(Number(this.value)); };
