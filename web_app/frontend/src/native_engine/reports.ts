/** Browser-only OOXML authors. No Python, server, Office automation or CDN. */
import ExcelJS from "exceljs";
import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  TableLayoutType,
  WidthType,
  HeadingLevel,
  Bookmark,
  InternalHyperlink,
  SimpleField,
  LeaderType,
  Tab,
  TabStopType,
  Header,
  Footer,
  PageNumber,
  AlignmentType,
  BorderStyle,
  ImageRun,
  Math as WordMath,
  MathRun,
  MathFraction,
  MathSubScript,
  MathSuperScript,
  MathIntegral,
  type MathComponent,
  type IPageMarginAttributes,
  type IStylesOptions,
} from "docx";
import { zipSync, strToU8 } from "fflate";
import { type Spec, reference } from "./spec";
import { VERSION } from "./engine";
import { sourceFor } from "./devices";
import {
  normalizeNetwork,
  analyzeNetwork,
  networkNodes,
  networkPort,
  NETWORK_SCHEMA,
} from "./network";
export type Picture = {
  caseId: string;
  kind: string;
  title: string;
  data: Uint8Array;
  width: number;
  height: number;
};
type Row = [string, any, string, string?];
type Module = { name: string; rows: (c: Spec) => Row[]; pictures: string[] };
const stressTypes = [
  ["mos", "MOS 耐压"],
  ["diode", "二极管反向耐压"],
  ["capacitor", "电容耐压与纹波电流"],
  ["resistor", "电阻功耗"],
] as const;
const stressMetric = (kind: string, metric: string) => {
  if (kind === "mos") return metric === "peak" ? "Vds 尖峰" : "Vds 阻断";
  if (kind === "diode") return "稳态反向电压";
  if (kind === "capacitor") return metric === "ripple" ? "纹波电流 RMS" : "电压峰值";
  return "平均耗散";
};
const f = (v: any) =>
  v == null
    ? "未计算"
    : typeof v === "number"
      ? Number.isFinite(v)
        ? Number(v.toPrecision(6)).toString()
        : "未定义"
      : typeof v === "object"
        ? JSON.stringify(v)
        : typeof v === "boolean"
          ? v
            ? "是"
            : "否"
          : (
              {
                pass: "模型内满足",
                review: "需核对",
                undefined: "待数据 / 未定义",
                info: "说明",
                not_configured: "尚未配置",
                reference: "初选参考",
                na: "不适用",
                assessed: "已完成几何评估",
                invalid_plan: "层序无效",
              } as Spec
            )[String(v)] || String(v);
const voltageText = (min: number, max: number) => min === max ? f(min) : f(min) + "–" + f(max);
const unitOf = (key: string) =>
  /^I_/.test(key)
    ? "A"
    : /^V_/.test(key)
      ? "V"
      : /^P_/.test(key)
        ? "W"
        : ["f_sw", "fc", "fz1", "fz2", "fp1", "fp2"].includes(key)
          ? "Hz"
          : ["pm", "min_pm"].includes(key)
            ? "°"
            : key === "gm_db"
              ? "dB"
              : ["Ae", "Wa"].includes(key)
                ? "m²"
                : key === "Ve"
                  ? "m³"
                  : ["MLT", "gap"].includes(key)
                    ? "m"
                    : ["B_pk", "dB"].includes(key)
                      ? "T"
                      : key === "dT"
                        ? "K"
                        : ["Np", "Ns"].includes(key)
                          ? "匝"
                          : "—";
const entries = (x: Spec, keys: string[], unit = "") =>
  keys.map((k) => [k, x?.[k] ?? null, unit || unitOf(k)] as Row);
function inputRows(parameters: Spec): Row[] {
  const rows: Row[] = [];
  const visit = (label: string, value: any, unit = "") => {
    if (Array.isArray(value)) {
      if (
        label.endsWith(".points") &&
        value.length &&
        value.every(
          (r) =>
            Array.isArray(r) &&
            r.length === 2 &&
            r.every((n: any) => typeof n === "number"),
        )
      ) {
        rows.push([
          label,
          value.length + " 个 x,y 点",
          "",
          "曲线点集另存于工程 JSON；报告仅保留范围和数量",
        ]);
        rows.push([
          label + " / X 范围",
          Math.min(...value.map((r) => r[0])) +
            " ～ " +
            Math.max(...value.map((r) => r[0])),
          "SI",
        ]);
        rows.push([
          label + " / Y 范围",
          Math.min(...value.map((r) => r[1])) +
            " ～ " +
            Math.max(...value.map((r) => r[1])),
          "SI",
        ]);
      } else if (value.every((v) => typeof v !== "object"))
        rows.push([label, value.join(" / "), unit]);
      else value.forEach((v, i) => visit(label + "[" + (i + 1) + "]", v));
    } else if (value && typeof value === "object") {
      const keys = Object.keys(value).filter((k) => !k.startsWith("_"));
      if (!keys.length) rows.push([label, "未配置", unit]);
      for (const key of keys) visit(label + "." + key, value[key]);
    } else rows.push([label, value, unit]);
  };
  for (const [key, value] of Object.entries(parameters)) {
    if (key.startsWith("_")) continue;
    const meta = reference.bootstrap.parameters.find(
      (r: Spec) => r.name === key,
    );
    visit(
      meta?.label ? meta.label + " / " + key : key,
      value,
      meta?.unit || "",
    );
  }
  return rows;
}
const modules: Module[] = [
  {
    name: "设计需求",
    rows: (c) => {
      const p = c.parameters;
      return [
        ["拓扑", p.topology, ""],
        ["控制方式", p.control_mode, ""],
        ["输入电压", voltageText(p.V_in_min, p.V_in_max), "V"],
        ["预设效率", p.eta_guess * 100, "%"],
        ["开关频率", p.f_sw, "Hz"],
        ["反馈路", p.feedback_output, ""],
        ...((p.outputs?.length ? p.outputs : [p]).flatMap(
          (r: Spec, i: number) => [
            [`OUT${i + 1} 输出电压`, r.V_out, "V"],
            [`OUT${i + 1} 最大功率`, r.P_out, "W"],
            [`OUT${i + 1} 最小功率`, r.P_out_min, "W"],
          ],
        ) as Row[]),
      ];
    },
    pictures: ["topology"],
  },
  {
    name: "功率级",
    rows: (c) =>
      entries(c.summary.operating_point, [
        "D",
        "Dp",
        "mode",
        "I_L_pk",
        "I_L_min",
        "I_L_rms",
        "I_sw_rms",
        "I_sw_pk",
        "I_d_rms",
        "I_d_pk",
        "V_sw_max",
        "V_d_max",
        "V_out_cap",
        "V_feedback",
        "f_sw",
      ]),
    pictures: ["power", "outputs", "clamp"],
  },
  {
    name: "器件与损耗",
    rows: (c) => [
      ...entries(
        c.summary.losses,
        [
          "P_semi",
          "P_mag",
          "P_cap",
          "P_cap_in",
          "P_sense",
          "P_rcd",
          "P_din",
          "P_dout",
          "P_total",
        ],
        "W",
      ),
      ["计算效率", c.summary.losses.eta * 100, "%"],
      ...entries(
        c.summary.mosfet,
        ["P_cond", "P_sw_on", "P_sw_off", "P_coss", "P_gate"],
        "W",
      ),
      ...entries(
        c.summary.mosfet,
        ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"],
        "s",
      ),
      ["t4 / t5 口径", "平台后栅电荷时间估计，不计入交叠损耗", ""],
      ...entries(c.summary.mosfet.gate, ["Vgp_on", "Vgp_off"], "V"),
      ...entries(
        c.summary.mosfet.gate,
        ["Qgs_on", "Qgs_off", "Qgd_on", "Qgd_off", "Qg_th", "Qg_on", "Qg_off"],
        "C",
      ),
    ],
    pictures: ["device_losses", "switching", "losses"],
  },
  {
    name: "电容纹波",
    rows: (c) => {
      const display = c.display;
      return [
        [
          "输出低频纹波",
          c.summary.operating_point.ripple_pp ?? display.ripple_pp,
          "V",
        ],
        ...(display.outputs.length > 1
          ? ["input"]
          : ["input", "output"]
        ).flatMap((side) =>
          display.capacitors[side].caps.flatMap(
            (cap: Spec, i: number) =>
              [
                [`${side} 电容${i + 1} C`, cap.C, "F"],
                [`${side} 电容${i + 1} ESR`, cap.ESR, "Ω"],
                [`${side} 电容${i + 1} RMS`, cap.total, "A"],
              ] as Row[],
          ),
        ),
        ...display.outputs.flatMap((r: Spec) => [
          [`OUT${r.id} 纹波`, r.ripple_pp, "V"],
          ...r.capacitors.output.caps.map(
            (cap: Spec, i: number) =>
              [`OUT${r.id} 电容${i + 1} RMS`, cap.total, "A"] as Row,
          ),
        ]),
      ];
    },
    pictures: ["input_caps", "output_caps"],
  },
  {
    name: "磁件与绕组",
    rows: (c) =>
      c.display.magnetics.flatMap((dev: Spec) => [
        [dev.kind + " 磁芯", dev.core_label || dev.core, ""],
        ...(dev.design_enabled === false
          ? [
              ["成品电感 / L", dev.L, "H"],
              ["成品电感 / DCR", dev.R_dc, "Ω"],
              ["成品电感 / 附加损耗", dev.P_extra, "W"],
              ["模型说明", dev.note, ""],
            ] as Row[]
          : []),
        ...entries(dev, [
          "Ae",
          "Ve",
          "Wa",
          "MLT",
          "Np",
          "Ns",
          "n_actual",
          "B_pk",
          "dB",
          "gap",
          "P_cu",
          "P_core",
          "P_total",
          "dT",
          "fill",
        ]),
        ...(dev.windings || []).flatMap(
          (w: Spec) =>
            [
              ["OUT" + w.id + " 匝数", w.Ns, ""],
              ["OUT" + w.id + " 线径", w.d_wire_s, "m"],
              ["OUT" + w.id + " 股数", w.n_strand_s, ""],
              ["OUT" + w.id + " 电流密度", w.J_actual / 1e6, "A/mm²"],
              ["OUT" + w.id + " DCR", w.R_dc, "Ω"],
            ] as Row[],
        ),
      ]),
    pictures: ["magnetics", "magnetic_flux", "winding"],
  },
  {
    name: "绕制与耦合",
    rows: (c) => {
      const a = c.display.winding_assessment,
        m = c.display.winding_model,
        rows: Row[] = [];
      if (a) {
        rows.push(
          ["窗口评估", a.status, ""],
          ["几何可容纳", a.fits, ""],
          ...entries(
            a,
            [
              "usable_width",
              "usable_height",
              "required_height",
              "height_margin",
            ],
            "m",
          ),
          ["物理层数", a.total_layer_count, "层"],
        );
        for (const [k, v] of Object.entries(a.config || {}))
          if (typeof v === "number") rows.push(["窗口 / " + k, v, "m"]);
        for (const [i, l] of (a.physical_layers || []).entries())
          rows.push([
            `第${i + 1}层 ${l.id}`,
            `${l.turns}匝；${l.winding_style}`,
            "",
            `等效宽 ${f(l.turn_width)} m；高 ${f(l.bundle_height)} m`,
          ]);
        rows.push(
          ...(a.warnings || []).map((v: string) => ["绕制边界", v, ""] as Row),
        );
      }
      if (m) {
        rows.push(
          ["周期模型", m.kind, ""],
          ["独立求解收敛", m.converged, ""],
          ["归一化残差", m.normalized_residual, ""],
          ["能量残差", m.energy_balance_W, "W"],
          ["相对能量残差", m.energy_balance_relative, ""],
          ["网格细化", m.mesh, ""],
          ["适用范围", m.assumptions || m.note, ""],
        );
        for (const key of ["K", "L"])
          for (const [i, r] of (m[key] || []).entries())
            rows.push([
              `${key} 矩阵第${i + 1}行`,
              r.map(f).join(" / "),
              key === "L" ? "H" : "",
              "顺序：原边、OUT1、OUT2…；L非对角项为有符号互感",
            ]);
        rows.push(
          ["求解电阻（含配置的PCB电阻）", m.R, "Ω"],
          ["各绕组 RMS", m.winding_rms, "A"],
        );
      } else rows.push(["耦合范围", "当前使用标称/理想匝比模型", ""]);
      return rows;
    },
    pictures: [],
  },
  {
    name: "环路与补偿",
    rows: (c) => [
      ...c.checks.filter((row: Spec) => row.id === "phase_margin").map((row: Spec) => [
        row.name, row.value, "°", `验收 ${row.comparison} ${f(row.limit)}° · ${f(row.state)}`,
      ] as Row),
      ...entries(c.summary.loop || {}, ["fc", "pm", "gm_db"]),
      ...entries(c.parameters, ["KP", "fz1", "fz2", "fp1", "fp2"]),
      [
        "闭环极点验证",
        c.summary.loop?.closed_loop_stable ?? "未完成",
        "",
        "直接核验状态矩阵；不得用 PM 代替",
      ],
      ["闭环极点 / rad·s⁻¹", c.summary.loop?.closed_loop_poles, ""],
      [
        "模型说明",
        c.summary.loop?.model?.assumptions || c.loop_error || "未完成",
        "",
      ],
    ],
    pictures: ["loop", "multi_reference", "multi_load"],
  },
  {
    name: "器件清单",
    rows: (c) =>
      c.summary.component_management.rows.filter((r: Spec) => r.quantity > 0).map((r: Spec) => [
          r.ref + " " + r.role,
          [r.manufacturer, r.model, r.package].filter(Boolean).join(" / ") ||
            "资料待填",
          "",
          [r.conditions, r.note].filter(Boolean).join("；"),
      ] as Row),
    pictures: [],
  },
  ...stressTypes.map(([kind, name]): Module => ({
    name,
    rows: (c) => {
      const rows: Row[] = [];
      for (const part of c.summary.component_management.rows) {
        if (part.kind !== kind) continue;
        for (const check of part.checks) {
          if (kind === "diode" && check.metric === "spike" && check.value == null) continue;
          rows.push([
            part.ref + " " + stressMetric(kind, check.metric), check.value, check.unit,
            `额定 ${f(check.rating)}，降额限值 ${f(check.limit)}，${f(check.state)}` +
              (kind === "diode" ? "" : "。" + (check.note || "")),
          ]);
        }
      }
      if (kind === "diode" && rows.length)
        rows.push(["反压范围", "寄生尖峰与外部反接反压待实测", ""]);
      return rows;
    },
    pictures: [],
  })),
  {
    name: "工程检查",
    rows: (c) => [
      ...c.checks.map(
        (r: Spec) =>
          [
            r.name,
            r.value,
            r.unit,
            r.limit == null
              ? `${f(r.state)}；${r.note || ""}`
              : `${r.comparison || ""} 限值 ${f(r.limit)}；${f(r.state)}；${r.note || ""}`,
          ] as Row,
      ),
      ...c.summary.warnings.map((v: string) => ["模型说明", v, ""] as Row),
    ],
    pictures: [],
  },
  {
    name: "交叉调整率",
    rows: (c) => {
      const cross = c.cross;
      if (!cross) return [["交叉负载角点", "未勾选计算", ""]];
      if (!cross.supported) return [["模型范围", cross.reason, ""]];
      const rows: Row[] = [
        [
          "角点完整性",
          cross.complete ? "全部成功" : "存在失败，包络不完整",
          "",
        ],
        ["计算口径", cross.note, ""],
      ];
      for (const rail of cross.summary) {
        const valid = cross.cases.filter(
          (r: Spec) => r.status === "ok" && r.V_in === c.V_in,
        );
        const values = valid.map((r: Spec) => r.voltages[rail.id - 1]);
        rows.push(
          [
            `OUT${rail.id} 端点包络最小值`,
            values.length ? Math.min(...values) : null,
            "V",
          ],
          [
            `OUT${rail.id} 端点包络最大值`,
            values.length ? Math.max(...values) : null,
            "V",
          ],
        );
      }
      for (const row of cross.cases.filter((r: Spec) => r.V_in === c.V_in))
        rows.push([
          row.id + " / 负载 W",
          row.powers.join(" / "),
          "",
          row.status === "ok"
            ? "输出 V：" + row.voltages.map(f).join(" / ")
            : row.error,
        ]);
      return rows;
    },
    pictures: [],
  },
  {
    name: "补偿电路计算",
    rows: (c) => {
      if (c.display.psr)
        return [
          ["补偿结构", "MP6005 PSR 物理 COMP 网络", ""],
          ...entries(c.display.psr, ["Rcomp"], "Ω"),
          ...entries(c.display.psr, ["Ccomp", "Cpole"], "F"),
          [
            "核算位置",
            "完整辅助采样与物理 COMP 结果见 PSR 控制核算；SSR 参考网络不适用",
            "",
          ],
        ];
      const d = c.display.compensation;
      if (!d)
        return [
          ["参考网络", "未配置 __comp；请在补偿页保存网络配置后重算", ""],
        ];
      if (d.error) return [["计算失败", d.error, ""]];
      return [
        ["网络", d.key, ""],
        ["方向", d.direction, ""],
        ["可实现", d.buildable, ""],
        ...Object.entries(d.parts)
          .filter(([, v]) => typeof v === "number")
          .map(
            ([k, v]) =>
              [k, v, /^C/.test(k) ? "F" : /^R/.test(k) ? "Ω" : ""] as Row,
          ),
        ...d.active_fields.map(
          (k: string) =>
            [
              k + " 目标 / 回代",
              f(d.targets[k]) + " / " + f(d.realized[k]),
              k === "KP" ? "" : "rad/s",
            ] as Row,
        ),
        ...d.notes.map((v: string) => ["核验说明", v, ""] as Row),
      ];
    },
    pictures: ["compensation"],
  },
  {
    name: "PSR控制核算",
    rows: (c) =>
      c.display.psr
        ? [
            ...Object.entries(c.display.psr)
              .filter(([, v]) => ["number", "string"].includes(typeof v))
              .map(
                ([k, v]) =>
                  [
                    k,
                    v,
                    /^R/.test(k)
                      ? "Ω"
                      : /^C/.test(k)
                        ? "F"
                        : /^V/.test(k)
                          ? "V"
                          : /^I/.test(k)
                            ? "A"
                            : "",
                  ] as Row,
              ),
          ]
        : [["适用性", "当前为 SSR；PSR 核算不适用", ""]],
    pictures: [],
  },
  {
    name: "寄生换流",
    rows: (c) => {
      const d = c.display.parasitics;
      if (!d) return [["适用性", "当前拓扑无局部寄生模型", ""]];
      return [
        ["模式", d.mode, ""],
        ["范围", d.scope || d.note, ""],
        ...d.edges.flatMap(
          (e: Spec) =>
            [
              ["器件", e.ref, ""],
              ["峰值", e.peak, "V"],
              ["振铃频率", e.frequency, "Hz"],
              ["初始能量", e.energy_initial, "J"],
              ["理想钳位触发", e.clamped, ""],
            ] as Row[],
        ),
      ];
    },
    pictures: ["parasitics"],
  },
  {
    name: "效率与负载",
    rows: (c) => [
      ["预设效率", c.parameters.eta_guess * 100, "%"],
      ["最终计算效率", c.summary.losses.eta * 100, "%"],
      ["控制器损耗", c.summary.losses.P_controller, "W"],
      ["附加寄生电阻损耗", c.summary.losses.P_parasitic, "W"],
      ["计算边界", "同套固定硬件；失败轻载不生成虚假稳压点", ""],
    ],
    pictures: ["efficiency", "losses"],
  },
  {
    name: "电容频带明细",
    rows: (c) => {
      const rows: Row[] = [],
        bank = (b: Spec, label: string) =>
          b.caps.forEach((cap: Spec, i: number) => {
            rows.push([`${label} 电容${i + 1} 总 RMS`, cap.total, "A"]);
            cap.bands.forEach((v: number, j: number) =>
              rows.push([`${label} 电容${i + 1} / ${b.labels[j]}`, v, "A"]),
            );
          });
      bank(c.display.capacitors.input, "输入");
      if (c.display.outputs.length)
        c.display.outputs.forEach((r: Spec) =>
          bank(r.capacitors.output, "OUT" + r.id),
        );
      else bank(c.display.capacitors.output, "OUT1");
      return rows;
    },
    pictures: [],
  },
  {
    name: "完整输入参数",
    rows: (c) => inputRows(c.parameters),
    pictures: [],
  },
];
export function reportCases(snapshot: Spec): Spec[] {
  const cc: Spec[] = snapshot.cases;
  const manual = snapshot.spec.mos_manual_events;
  const differentGateSettings = manual && sourceFor(snapshot.spec, "Q1:transfer") === "fixed" &&
    ["on", "off"].some(edge => ["Vgp", "Qgs"].some(key => manual.min?.[edge]?.[key] !== manual.max?.[edge]?.[key]));
  if (cc.length === 2 && cc[0].V_in === cc[1].V_in && cc.every(c => !c.error && c.summary) && !differentGateSettings)
    return cc.slice(0, 1);
  return cc;
}
function cases(snapshot: Spec) {
  return reportCases(snapshot).map((c: Spec) => ({
    ...c,
    display: snapshot.display.find((r: Spec) => r.id === c.id),
    cross: snapshot.cross_regulation,
  }));
}
function caseLabel(c: Spec, count: number) {
  return (count === 1 ? "固定输入" : c.id) + " · " + c.V_in + " V";
}
function keyResult(c: Spec) {
  if (c.error || !c.summary) return ["计算未完成", null, null, null];
  const design = c.checks || [];
  const stress = c.summary.component_management.rows.flatMap((r: Spec) => r.checks);
  const checks = [...design, ...stress];
  const review = checks.filter(row => row.state === "review").length;
  const missing = checks.filter(row => row.state === "undefined").length;
  return [
    review || missing ? `需复核 ${review} 项，待补数据 ${missing} 项` : "已列项目满足限值",
    c.summary.losses.eta * 100,
    c.summary.operating_point.V_sw_max,
    c.display?.ripple_pp != null ? c.display.ripple_pp * 1000 : null,
  ];
}
const conclusionHeaders = ["输入工况", "检查结果", "效率 / %", "主 MOS 电压 / V", "主路纹波 / mV"];
function moduleCases(module: Module, cc: Spec[]) {
  return ["设计需求", "器件清单", "完整输入参数"].includes(module.name)
    ? cc.filter(c => !c.error).slice(0, 1)
    : cc;
}
function modulePictures(pictures: Picture[], module: Module, c: Spec) {
  return pictures.filter(p => p.caseId === c.id && module.pictures.includes(p.kind));
}
function flattenedRows(module: Module, c: Spec): Row[] {
  if (c.error) return [["工况失败", c.error, ""]];
  return module.rows(c);
}
export async function excel(snapshot: Spec, pictures: Picture[] = []) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "PCS 技术货架";
  workbook.created = new Date(snapshot.created_at);
  workbook.subject = "辅源设计与检查";
  const cc = cases(snapshot);
  const conclusions = workbook.addWorksheet("关键结论");
  conclusions.columns = [25, 37, 16, 20, 21].map(width => ({ width }));
  conclusions.addRow(conclusionHeaders);
  for (const c of cc) conclusions.addRow([caseLabel(c, cc.length), ...keyResult(c)]);
  conclusions.getRow(1).height = 28;
  conclusions.getRow(1).eachCell(cell => {
    cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF17365D" } };
  });
  conclusions.views = [{ state: "frozen", xSplit: 0, ySplit: 1 }];
  for (const module of modules) {
    const selected = moduleCases(module, cc);
    if (!selected.some(c => flattenedRows(module, c).length)) continue;
    const sheet = workbook.addWorksheet(module.name, {
      views: [{ state: "frozen", xSplit: 0, ySplit: 5 }],
      pageSetup: {
        paperSize: 9,
        orientation: "landscape",
        fitToPage: true,
        fitToWidth: 1,
        fitToHeight: 0,
      },
    });
    const widths = selected.length === 1 ? [32, 23, 12, 48] : [30, 23, 12, 42, 4, 30, 23, 12, 42];
    const lastColumn = widths.length;
    sheet.columns = widths.map((width) => ({
      width,
    }));
    sheet.mergeCells(1, 1, 1, lastColumn);
    sheet.getCell("A1").value =
      (snapshot.spec.__web_project_title || "PCS 辅源设计") +
      " · " +
      module.name;
    sheet.getRow(1).height = 35;
    sheet.getCell("A1").font = {
      name: "微软雅黑",
      size: 18,
      bold: true,
      color: { argb: "FFFFFFFF" },
    };
    sheet.getCell("A1").fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: "FF0D1726" },
    };
    sheet.mergeCells(2, 1, 2, lastColumn);
    sheet.getCell("A2").value =
      "TypeScript 离线计算 · " +
      VERSION +
      " · 同一套固定磁件 · " +
      snapshot.created_at;
    sheet.getCell("A2").font = { size: 10, color: { argb: "FF68788F" } };
    selected.forEach((c: Spec, index: number) => {
      const column = index ? 6 : 1;
      sheet.mergeCells(3, column, 3, column + 3);
      const cell = sheet.getCell(3, column);
      cell.value = selected.length === 1 && cc.length > 1 ? "共用设计" : caseLabel(c, cc.length);
      cell.fill = {
        type: "pattern",
        pattern: "solid",
        fgColor: { argb: index ? "FF20AEBF" : "FF2376E5" },
      };
      cell.font = {
        name: "微软雅黑",
        bold: true,
        color: { argb: "FFFFFFFF" },
        size: 13,
      };
      const values = flattenedRows(module, c);
      ["参数 / 检查项", "计算值", "单位", "说明 / 判定"].forEach((v, j) => {
        const cell = sheet.getCell(5, column + j);
        cell.value = v;
        cell.fill = {
          type: "pattern",
          pattern: "solid",
          fgColor: { argb: "FFE9F2FF" },
        };
        cell.font = { bold: true, color: { argb: "FF152238" } };
      });
      values.forEach((row, i) =>
        row.forEach((v, j) => {
          const cell = sheet.getCell(i + 6, column + j);
          cell.value =
            v === ""
              ? null
              : typeof v === "number" && Number.isFinite(v)
                ? v
                : f(v);
          cell.font = {
            name: "微软雅黑",
            size: 11,
            color: { argb: "FF152238" },
          };
          cell.alignment = { vertical: "middle", wrapText: true };
          if (i % 2 === 0)
            cell.fill = {
              type: "pattern",
              pattern: "solid",
              fgColor: { argb: "FFF3F6FA" },
            };
          if (typeof v === "number")
            cell.numFmt =
              Math.abs(v) < 0.001 && v !== 0 ? "0.0000E+00" : "0.0000";
        }),
      );
      const own = modulePictures(pictures, module, c);
      let row = values.length + 9;
      for (const pic of own) {
        const id = workbook.addImage({
          buffer: pic.data as any,
          extension: "png",
        });
        sheet.addImage(id, {
          tl: { col: column - 1, row: row - 1 },
          ext: {
            width: 640,
            height: Math.round((640 * pic.height) / pic.width),
          },
        });
        row += Math.ceil((640 * pic.height) / pic.width / 20) + 3;
      }
    });
    sheet.eachRow((row) => {
      if (row.number > 4) {
        let lines = 1;
        row.eachCell((cell, col) => {
          const chars = String(cell.value ?? "")
            .split("")
            .reduce((n, c) => n + (c.charCodeAt(0) > 255 ? 2 : 1), 0);
          lines = Math.max(
            lines,
            Math.ceil(
              chars / Math.max(8, (sheet.getColumn(col).width || 20) - 2),
            ),
          );
        });
        row.height = Math.min(360, Math.max(32, lines * 16 + 8));
      }
    });
    sheet.autoFilter = {
      from: { row: 5, column: 1 },
      to: { row: 5, column: 4 },
    };
  }
  return new Uint8Array(await workbook.xlsx.writeBuffer());
}
// Match the technical document defaults used by Python's docx_layout.py.
// Browser exports retain their PCS titles and engineering report hierarchy.
const bodyFont = {
  ascii: "Cambria", hAnsi: "Cambria", cs: "Cambria", eastAsia: "SimSun",
};
const headingFont = { ...bodyFont, eastAsia: "Microsoft YaHei" };
const wordInk = "243547";
const pageMargin: IPageMarginAttributes = {
  top: "20mm", bottom: "19mm", left: "15mm", right: "15mm",
  header: "8mm", footer: "8mm",
};
const wordPage = { size: { width: "210mm", height: "297mm" }, margin: pageMargin } as const;
const wordStyles: IStylesOptions = {
  default: {
    document: {
      run: { font: bodyFont, size: 22, sizeComplexScript: 22, color: "000000" },
      paragraph: { spacing: { line: 280, after: 100 } },
    },
    title: {
      run: { font: headingFont, size: 60, sizeComplexScript: 60, bold: true, color: "000000" },
      paragraph: { spacing: { after: 240 }, keepNext: true },
    },
    heading1: {
      run: { font: headingFont, size: 40, sizeComplexScript: 40, bold: true, color: "000000" },
      paragraph: { spacing: { before: 240, after: 120 }, keepNext: true },
    },
    heading2: {
      run: { font: headingFont, size: 26, sizeComplexScript: 26, bold: true, color: "000000" },
      paragraph: { spacing: { before: 200, after: 120 }, keepNext: true },
    },
  },
  paragraphStyles: [
    {
      id: "Caption",
      name: "Caption",
      basedOn: "Normal",
      run: { font: bodyFont, size: 18, sizeComplexScript: 18, color: wordInk },
      paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 40, after: 150 } },
    },
  ],
};
function wordSection(children: (Paragraph | Table)[]) {
  const running = { font: bodyFont, size: 16, sizeComplexScript: 16, color: wordInk };
  return {
    properties: { page: wordPage },
    headers: {
      default: new Header({
        children: [new Paragraph({
          children: [new TextRun({ ...running, text: "PCS 技术货架  /  辅源设计" })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [
            new TextRun({ ...running, text: "设计评审 · " + VERSION + "  |  " }),
            new TextRun({ ...running, children: [PageNumber.CURRENT] }),
          ],
        })],
      }),
    },
    children,
  };
}
const paragraph = (text: string) => new Paragraph({ text });
// The usable width of an A4 page with 15 mm side margins is about 10205 twips.
const rightTab = 10100;

class WordBook {
  private readonly body: (Paragraph | Table)[];
  private readonly chapters: { label: string; anchor: string }[] = [];
  private contentsPosition = 0;
  private sections = 0;
  private tables = 0;
  private figures = 0;
  private equations = 0;

  constructor(title: string, ...context: string[]) {
    this.body = [
      new Paragraph({ heading: HeadingLevel.TITLE, text: title }),
      ...context.map(text => paragraph(text)),
    ];
  }

  chapter(title: string) {
    if (this.chapters.length === 1) this.contentsPosition = this.body.length;
    const number = this.chapters.length + 1;
    const label = `${String(number).padStart(2, "0")}　${title}`;
    const anchor = `report_chapter_${number}`;
    this.chapters.push({ label, anchor });
    this.sections = this.tables = this.figures = this.equations = 0;
    this.body.push(new Paragraph({
      heading: HeadingLevel.HEADING_1,
      keepNext: true,
      children: [new Bookmark({ id: anchor, children: [new TextRun(label)] })],
    }));
  }

  section(title: string) {
    this.body.push(new Paragraph({
      text: `${this.chapters.length}.${++this.sections}　${title}`,
      heading: HeadingLevel.HEADING_2, keepNext: true,
    }));
  }

  add(...lines: string[]) {
    this.body.push(...lines.map(text => paragraph(text)));
  }

  table(title: string, headers: string[], rows: any[][]) {
    this.body.push(
      new Paragraph({
        style: "Caption", alignment: AlignmentType.LEFT, keepNext: true,
        text: `表 ${this.chapters.length}-${++this.tables}　${title}`,
      }),
      table(headers, rows),
    );
  }

  figure(picture: Picture, title = picture.title, maxHeight = 650) {
    const ratio = Math.min(615 / picture.width, maxHeight / picture.height);
    this.body.push(new Paragraph({
      alignment: AlignmentType.CENTER, keepNext: true,
      children: [new ImageRun({
        type: "png", data: picture.data,
        altText: { name: title, title, description: title },
        transformation: {
          width: Math.round(picture.width * ratio),
          height: Math.round(picture.height * ratio),
        },
      })],
    }), new Paragraph({
      style: "Caption", text: `图 ${this.chapters.length}-${++this.figures}　${title}`,
    }));
  }

  equation(children: MathComponent[], symbols: string) {
    this.body.push(new Paragraph({
      children: [
        new WordMath({ children }),
        new TextRun({
          children: [new Tab(), `(${this.chapters.length}-${++this.equations})`],
          size: 18, color: wordInk,
        }),
      ],
      tabStops: [{ type: TabStopType.RIGHT, position: rightTab }],
      spacing: { after: 60 },
      keepNext: true,
    }), paragraph(symbols));
  }

  sectionWithContents() {
    const entries = this.chapters.map(({ label, anchor }) =>
      new Paragraph({
        children: [
          new InternalHyperlink({ anchor, children: [new TextRun({ text: label, color: wordInk })] }),
          new TextRun({ children: [new Tab()] }),
          new SimpleField(`PAGEREF ${anchor} \\h`),
        ],
        tabStops: [{ type: TabStopType.RIGHT, position: rightTab, leader: LeaderType.DOT }],
        spacing: { after: 45 },
      }),
    );
    return wordSection([
      ...this.body.slice(0, this.contentsPosition),
      new Paragraph({ heading: HeadingLevel.HEADING_1, text: "目录", pageBreakBefore: true, keepNext: true }),
      ...entries,
      ...this.body.slice(this.contentsPosition),
    ]);
  }
}
const tableBorder = { style: BorderStyle.SINGLE, size: 4, color: "D9D9D9" } as const;
const wordStatusColor = (label: string) => {
  if (["满足", "通过", "模型内满足", "已完成"].includes(label)) return "29633B";
  if (["需核对", "需复核", "超限", "不满足", "失败"].includes(label)) return "A12D24";
  if (label.startsWith("待") || ["未计算", "未定义"].includes(label)) return "8C5D16";
  return "000000";
};
function table(headers: string[], rows: any[][]) {
  const spans = headers[0] === "参数 / 检查项"
    ? [0.26, 0.24, 0.1, 0.4]
    : headers[1] === "SHA256"
      ? [0.34, 0.66]
      : headers.map(() => 1 / headers.length);
  const widths = spans.map(share => Math.floor(10204 * share));
  return new Table({
    width: { size: 10204, type: WidthType.DXA },
    layout: TableLayoutType.FIXED,
    columnWidths: widths,
    borders: {
      top: tableBorder, bottom: tableBorder, left: tableBorder, right: tableBorder,
      insideHorizontal: tableBorder, insideVertical: tableBorder,
    },
    rows: [headers, ...rows].map(
      (r, i) =>
        new TableRow({
          tableHeader: i === 0,
          cantSplit: true,
          children: headers.map((_, column) => {
            const v = column < r.length ? r[column] : "";
            const text = f(v);
            const color = i === 0 ? "000000" : wordStatusColor(text);
            return new TableCell({
              width: { size: widths[column], type: WidthType.DXA },
              shading: { fill: i === 0 ? "E5EBF2" : "FFFFFF" },
              margins: { top: 65, bottom: 65, left: 90, right: 90 },
              children: [
                new Paragraph({
                  spacing: { after: 0 },
                  keepNext: i === 0,
                  children: [
                    new TextRun({
                      text, font: bodyFont, size: 20, sizeComplexScript: 20,
                      bold: i === 0 || color !== "000000", color,
                    }),
                  ],
                }),
              ],
            });
          }),
        }),
    ),
  });
}
export async function word(snapshot: Spec, pictures: Picture[] = []) {
  const cc = cases(snapshot);
  const minVin = snapshot.spec.V_in_min;
  const maxVin = snapshot.spec.V_in_max;
  const book = new WordBook(
    "PCS 辅源设计计算报告",
    snapshot.spec.__web_project_title || "辅源电源设计",
    `输入 ${voltageText(minVin, maxVin)} V · ${snapshot.spec.topology}`,
  );
  book.chapter("关键结论");
  book.table("输入端点设计检查", conclusionHeaders,
    cc.map(c => [caseLabel(c, cc.length), ...keyResult(c)]));
  book.chapter("计算关系");
  book.add("下列公式给出共用计算关系。磁件、器件损耗和补偿的具体适用项见各设计章节。");
  const run = (s: string) => new MathRun(s),
    sub = (s: string, index: string) =>
      new MathSubScript({ children: [run(s)], subScript: [run(index)] }),
    sup = (s: MathComponent, index: string) =>
      new MathSuperScript({ children: [s], superScript: [run(index)] }),
    fraction = (a: MathComponent[], b: MathComponent[]) =>
      new MathFraction({ numerator: a, denominator: b });
  const equations: MathComponent[][] = [
    [
      sub("P", "in,预设"),
      run("="),
      fraction([sub("P", "out")], [sub("η", "预设")]),
    ],
    [
      sub("P", "cond,MOS"),
      run("="),
      sup(sub("I", "RMS"), "2"),
      run("·"),
      sub("R", "DS(on)"),
    ],
    [
      sub("P", "cond,D"),
      run("="),
      fraction([run("1")], [run("T")]),
      new MathIntegral({
        subScript: [run("0")],
        superScript: [run("T")],
        children: [run("i(t)·"), sub("V", "f"), run("(i(t)) dt")],
      }),
    ],
    [
      sub("R", "DCR"),
      run("="),
      fraction([run("ρ·MLT·N")], [run("n·π·"), sup(run("d"), "2"), run("/4")]),
    ],
    [
      sub("η", "计算"),
      run("="),
      fraction(
        [sub("P", "out")],
        [sub("P", "out"), run("+Σ"), sub("P", "loss")],
      ),
    ],
    [
      sub("M", "ij"),
      run("="),
      sub("k", "ij"),
      run("·√("),
      sub("L", "i"),
      run("·"),
      sub("L", "j"),
      run(")"),
    ],
    [
      sub("ΔT", "transformer"),
      run("="),
      sub("P", "cu+core"),
      run("·"),
      sub("R", "i-a"),
    ],
    [
      sub("G", "c,type2"),
      run("(s)="),
      fraction(
        [sub("K", "P"), run("·(1+s/"), sub("ω", "z1"), run(")")],
        [run("s·(1+s/"), sub("ω", "p1"), run(")")],
      ),
    ],
    [sub("f", "z,RC"), run("="), fraction([run("1")], [run("2πRC")])],
  ];
  const symbolNotes = [
    "式中，Pin,预设 为估计输入功率（W），Pout 为输出功率（W），η预设 为输入的效率估计（无量纲）。",
    "式中，Pcond,MOS 为 MOSFET 导通损耗（W），IRMS 为该器件电流有效值（A），RDS(on) 为导通电阻（Ω）。",
    "式中，Pcond,D 为二极管导通损耗（W），T 为开关周期（s），i(t) 为瞬时正向电流（A），Vf 为该电流下的正向压降（V）。",
    "式中，RDCR 为绕组直流电阻（Ω），ρ 为导体电阻率（Ω·m），MLT 为平均每匝长度（m），N 为匝数，n 为等效并联铜股总数，d 为单股裸铜直径（m）。",
    "式中，η计算 为由损耗回算的效率（无量纲），Pout 为输出功率（W），ΣPloss 为所列模型损耗之和（W）。",
    "式中，Mij 为第 i 与第 j 个绕组间的互感（H），Li、Lj 为各自自感（H），kij 为相同端点参考方向下的耦合系数（无量纲）。",
    "式中，ΔTtransformer 为变压器温升（K），Pcu+core 为铜损与磁芯损耗之和（W），Ri-a 为变压器至环境热阻（K/W）。",
    "式中，Gc,type2 为二型补偿器传递函数，s 为拉普拉斯变量（s⁻¹），KP 为补偿增益系数，ωz1、ωp1 为零点和极点角频率（rad/s）。",
    "式中，fz,RC 为一阶 RC 网络的特征频率（Hz），R 为参与构成该时间常数的电阻（Ω），C 为电容（F）。",
  ];
  equations.forEach((formula, index) => book.equation(formula, symbolNotes[index]));
  for (const module of modules) {
    if (["完整输入参数", "电容频带明细"].includes(module.name)) continue;
    const selected = moduleCases(module, cc);
    if (!selected.some(c => flattenedRows(module, c).length)) continue;
    book.chapter(module.name);
    for (const c of selected) {
      const rows = flattenedRows(module, c);
      if (!rows.length) continue;
      const operatingPoint = selected.length === 1 && cc.length > 1
        ? "共用设计" : caseLabel(c, cc.length);
      book.section(operatingPoint);
      book.table(`${module.name} ${operatingPoint}`,
        ["参数 / 检查项", "计算值", "单位", "说明 / 判定"], rows);
      for (const pic of modulePictures(pictures, module, c)) {
        const title = pic.kind === "topology" ? "共用拓扑与器件位号" : pic.title;
        book.figure(pic, title);
      }
    }
  }
  book.chapter("输入与复现");
  book.add("计算来源为浏览器内核 " + VERSION + "。完整输入见 Excel，器件曲线见工程 JSON。");
  book.table(
    "用于复现版本的源文件校验值", ["参考模块", "SHA256"],
    Object.entries(snapshot.provenance.reference_source_hashes).map(
      ([key, value]) => [key, String(value).replace(/(.{32})/g, "$1 ")],
    ),
  );
  const doc = new Document({
    creator: "PCS 技术货架",
    title: "辅源设计报告",
    description: "浏览器离线 TypeScript 计算",
    styles: wordStyles,
    features: { updateFields: true },
    sections: [book.sectionWithContents()],
  });
  return new Uint8Array(await (await Packer.toBlob(doc)).arrayBuffer());
}
export function bundle(files: Record<string, Uint8Array>) {
  return zipSync(files, { level: 5 });
}
export const jsonFile = (data: any) => strToU8(JSON.stringify(data, null, 2));
export function reportModules() {
  return modules;
}
export async function overview(
  project: Spec,
  manifest: Spec,
  picture?: Picture,
) {
  const book = new WordBook("PCS 技术货架 · 辅源架构与交付总览", project.title);
  book.chapter("关键结论");
  book.add(`已完成 ${manifest.units.filter((r: Spec) => r.state === "completed").length}/${manifest.units.length} 个单元报告。`);
  book.table("单元报告完成情况", ["单元", "名称", "计算状态", "说明"],
    manifest.units.map((r: Spec) => [
      r.id,
      r.name,
      r.state === "completed" ? "已完成" : "失败",
      r.error || "见单元目录中的 Word / Excel 与输入 JSON",
    ]),
  );
  book.chapter("系统架构与输入母线");
  if (picture) book.figure(picture);
  book.table("输入母线配置", ["编号", "名称", "输入范围 / V", "配置容量 / W"],
    project.sources.map((s: Spec) => [
      s.id,
      s.name,
      voltageText(s.min, s.max),
      s.capacity,
    ]),
  );
  if (project.schema_version === NETWORK_SCHEMA) {
    const p = normalizeNetwork(project),
      r = analyzeNetwork(p);
    book.chapter("OR 汇流、负载与竞争供电预算");
    book.add(r.method);
    for (const section of networkSections(p, r, manifest)) {
      book.section(section.title);
      book.table(section.title, section.header,
        section.rows.slice(0, section.title === "竞争供电工况" ? 24 : 256));
    }
    book.add(
      (r.coverage_complete ? "" : "部分竞争组合待检查。") +
        "完整工况及分配功率见供电网络预算.xlsx。",
    );
  } else {
    book.chapter("辅源与供电关系");
    for (const unit of project.units) {
      const p = unit.spec,
        rr = p.outputs?.length ? p.outputs : [p];
      book.section(unit.id + " · " + unit.name);
      book.table("上游与输出端口配置", ["项目", "配置"], [
        [
          "上游",
          (unit.source.kind === "none" ? "未连接" : unit.source.id) +
            (unit.source.kind === "unit"
              ? " / OUT" + unit.source.output
              : ""),
        ],
        ["设计输入 / V", voltageText(p.V_in_min, p.V_in_max)],
        ["拓扑", p.topology],
        ["预设效率", f(p.eta_guess * 100) + " %"],
        ...rr.map((r: Spec, i: number) => [
          "OUT" + (i + 1),
          f(r.V_out) + " V / " + f(r.P_out) + " W",
        ]),
      ]);
    }
  }
  book.chapter("工程文件");
  book.add("辅源工程.json 保存连接关系与单元输入。详细结果见各单元报告。");
  const document = new Document({
    creator: "PCS 技术货架",
    styles: wordStyles,
    features: { updateFields: true },
    sections: [book.sectionWithContents()],
  });
  return new Uint8Array(await (await Packer.toBlob(document)).arrayBuffer());
}

function networkSections(p: Spec, r: Spec, manifest: Spec) {
  return [
    {
      title: "节点与负载",
      header: ["节点", "名称", "类型", "配置", "状态"],
      rows: networkNodes(p).map(([kind, n]) => [
        n.id,
        n.name,
        kind === "junction"
          ? "OR汇流"
          : kind === "load"
            ? "负载"
            : kind === "unit"
              ? "电源单元"
              : "输入源",
        kind === "load"
          ? `${n.power}W；允许${n.min}–${n.max || "不限"}V`
          : kind === "bus"
            ? `${voltageText(n.min, n.max)} V，${n.capacity} W`
            : kind === "junction"
              ? `${n.capacity}W`
              : `${n.spec.topology}，输入 ${voltageText(n.spec.V_in_min, n.spec.V_in_max)} V`,
        n.enabled ? "启用" : "停用",
      ]),
    },
    {
      title: "供电连接",
      header: ["连接", "上游", "下游", "方式", "Vf/V", "状态"],
      rows: p.connections.map((e: Spec) => [
        e.id,
        networkPort(e.source),
        e.target,
        e.mode === "diode" ? "二极管OR" : "直连",
        e.mode === "diode" ? e.vf : "—",
        e.enabled ? "启用" : "停用",
      ]),
    },
    {
      title: "功率预算",
      header: ["端口", "正常W", "已评估最大W", "容量W", "检查", "最坏工况"],
      rows: r.capacity.map((c: Spec) => [
        c.port,
        c.normal,
        c.allocated,
        c.capacity,
        c.ok ? "未超容量" : "需核对",
        c.worst_case,
      ]),
    },
    {
      title: "电压与失电",
      header: [
        "节点",
        "可用下限V",
        "可用上限V",
        "允许下限V",
        "允许上限V",
        "检查",
      ],
      rows: r.interfaces.map((v: Spec) => [
        v.unit,
        v.source_min ?? "无供电",
        v.source_max ?? "无供电",
        v.design_min,
        v.design_max || "不限",
        v.note + (v.ok ? "" : "；电压需核对"),
      ]),
    },
    {
      title: "二极管损耗",
      header: ["支路", "上游", "下游", "Vf/V", "最大损耗W"],
      rows: r.diode_losses
        .filter((d: Spec) =>
          p.connections.some(
            (e: Spec) => e.id === d.connection && e.mode === "diode",
          ),
        )
        .map((d: Spec) => [d.connection, d.source, d.target, d.vf, d.loss]),
    },
    {
      title: "竞争供电工况",
      header: ["工况", "正常供电", "端口分配W", "导通支路", "失电节点"],
      rows: r.cases.map((c: Spec) => [
        c.name,
        c.normal ? "是" : "否",
        Object.entries(c.allocated)
          .map(([k, v]) => k + " = " + f(v) + "W")
          .join("；"),
        Object.entries(c.routes)
          .map(([k, v]) => k + " ← " + v)
          .join("；"),
        c.unavailable.join("、") || "无",
      ]),
    },
    {
      title: "单元交付状态",
      header: ["单元", "名称", "状态", "说明"],
      rows: (manifest.units || []).map((u: Spec) => [
        u.id,
        u.name,
        u.state === "completed" ? "已完成" : "失败",
        u.error || "见单元报告",
      ]),
    },
  ];
}
export async function networkExcel(
  project: Spec,
  manifest: Spec,
  review?: Spec,
) {
  const p = normalizeNetwork(project),
    r = review || analyzeNetwork(p),
    book = new ExcelJS.Workbook();
  book.creator = "PCS 技术货架";
  const info = book.addWorksheet("关键结论");
  info.addRows([
    ["项目", p.title],
    ["容量待复核", r.capacity.filter((row: Spec) => !row.ok).length],
    ["输入接口待复核", r.interfaces.filter((row: Spec) => !row.ok).length],
    ["工况覆盖", r.coverage_complete ? "完整" : "部分竞争组合待检查"],
    ["方法", r.method],
  ]);
  info.getColumn(1).width = 22;
  info.getColumn(2).width = 100;
  info.getColumn(2).alignment = { wrapText: true };
  for (const section of networkSections(p, r, manifest)) {
    const sheet = book.addWorksheet(section.title);
    sheet.addRow(section.header);
    sheet.addRows(section.rows);
    sheet.views = [{ state: "frozen", ySplit: 1 }];
    sheet.autoFilter = {
      from: { row: 1, column: 1 },
      to: { row: 1, column: section.header.length },
    };
    sheet.getRow(1).eachCell((cell) => {
      cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
      cell.fill = {
        type: "pattern",
        pattern: "solid",
        fgColor: { argb: "FF173B64" },
      };
    });
    for (let col = 1; col <= section.header.length; col++) {
      sheet.getColumn(col).width = Math.min(
        65,
        Math.max(
          18,
          ...section.rows
            .slice(0, 60)
            .map((row: any[]) => String(row[col - 1] ?? "").length + 3),
        ),
      );
      sheet.getColumn(col).alignment = { vertical: "top", wrapText: true };
    }
  }
  return new Uint8Array(await book.xlsx.writeBuffer());
}
