# 开关电源设计与环路分析工具

**Power Supply Design & Loop Analyzer**

维护者 **szj** · [GitHub 项目主页](https://github.com/sunzhanjie2-sudo/power-supply-design-software)

一个在本地运行、由 AI 辅助开发并持续通过算例与仿真复核的电源设计工具。它将供电架构、功率级计算、器件损耗、磁件设计、控制环路和工程报告放进同一个工作流，减少重复录入，让设计结果可以追溯到输入参数和模型条件。

支持 Windows 桌面界面、本地网页版、Python API 和命令行。日常计算在用户电脑上完成；LTspice 仿真需要另行安装 LTspice。

## 主要功能

| 模块 | 功能 |
| --- | --- |
| 供电架构 | 拖动输入源、电源模块、LDO、负载和二极管 OR 汇流；编辑连接、支路压降及启用状态，进行级联电压与功率预算 |
| 电源树联合启停（桌面） | 集中配置源多次上电/掉电、可选恒流/折返/打嗝、输入UVLO、EN/多轨就绪、软启动和分阶段负载；连接现有通用开关级模型实际运行LTspice，观察浪涌、CS、OR切换、负载复位重启与关机残压，导出Word/HTML/CSV及原始证据。[说明与完整示例](docs/SYSTEM_STARTUP_SHUTDOWN.md) |
| 按规格生成初版 | 异步 Buck、LM5022 Boost 和 MP6005 定频 SSR 反激。反激可选满载 CCM / DCM，自动选磁芯、整数匝、励磁电感、各路电容、采样电阻并整定补偿。载入多路工程后沿用反馈路及各副边匝数比例，计算不同负载组合的端口电压和器件应力 |
| 功率级 | Buck、Boost、CCM/DCM 反激、准谐振反激、有源钳位正激、LLC；分别计算 Vinmin/Vinmax 工作点及关键波形 |
| COT 同步 Buck | 1–16相共享单输出；总电流反馈、逐相均流/失配、限流保护、动态容量、源阻抗及系统启停。实际器件四相例程用同一硬件完成两端动态和开关FRA对比。[工程配置](docs/COT_ENGINEERING.md) · [模型与操作](docs/COT_BUCK.md) |
| LLC 谐振变换器（桌面与 Python 内核） | 半桥／全桥原边，电压变频／混合滞环（HHC）控制。支持按规格初选、周期波形、磁件、损耗、ZVS、PI 环路、双向负载阶跃、容差和独立 LTspice 报告。[模型、操作和 300 W 例程](docs/LLC_DESIGN.md) |
| 多路输出 | 隔离拓扑最多 6 路输出；选择主反馈路，按实际匝数派生其他路参考；独立配置整流器、电容与绕组。定频反激、QR反激和有源钳位正激可启用非理想耦合矩阵，独立求解各路电流与负载角点电压 |
| 半导体损耗 | 固定值快速估算或导入曲线计算；MOS 转移特性、栅电荷、米勒平台与 t1–t8 分段；二极管 If–Vf 导通损耗 |
| 电容组 | 可增删的并联电容列表，每颗独立配置 C、ESR、ESL，计算分流、纹波和损耗 |
| 磁件 | 标准及自定义磁芯、匝数、磁密、Steinmetz 损耗、DCR、电流密度、热阻温升；窗口、利兹线、交错绕制及[三维绕组建模数据导出](docs/TRANSFORMER_GEOMETRY_EXPORT.md) |
| 三维结构预览（桌面） | 半透明磁芯、深色螺旋绕组，旋转/缩放、逐层隐藏、上下半芯、正交三视图、分解装配与 PNG 导出；67 个型号的网格随软件内置，保留原厂三视图来源和参考版本。[操作说明](docs/TRANSFORMER_3D_PREVIEW.md) |
| 变压器场仿真（桌面） | 从画布单元的磁件页调用本机提取器与 Elmer。查看端口电感和耦合矩阵、漏感及采用场解参数前后的电源端点对比，再决定是否写回单元。[首次配置与操作](docs/TRANSFORMER_GEOMETRY_EXPORT.md#从磁件页生成仿真与闭环报告) |
| 联合仿真报告（桌面） | 内置变压器提取内核，集中配置本机 Elmer、磁芯 CAD 与 LTspice。从当前绕制自动生成提取设置，支持跨电脑导入和导出磁芯配置包。串联场解、裕量、设计复算和电路对比，同一批证据输出 Word 与 Excel。[使用范围](docs/JOINT_SIMULATION.md) · [换电脑配置](docs/PORTABLE_SIMULATION.md) |
| 环路与补偿 | 功率级及补偿器 Bode 图、相位/增益裕度、二型/三型补偿、K 因子整定与补偿电路阻容反推、COT 频率 PI 整定 |
| BOM 与降额 | 厂家、型号、封装、额定值及降额对照；缺失额定值和未覆盖应力明确标注待复核 |
| 硬件容差边界与分布评估（桌面） | 固定选型后先推导适用的理论边界，再按指标复算少量候选工况。发现超限时按器件分布估计两类失效概率。[配置与解读](docs/TOLERANCE_ANALYSIS.md) |
| 工程验证与验收（桌面） | 两端核对器件规格和电源外特性，限值来自器件与设计参数。支持匹配仿真、实测和裕量追溯。[使用说明](docs/ENGINEERING_ACCEPTANCE.md) |
| 工程报告 | 设计计算、电路对比、联合仿真均有 Excel 版。首页突出结论，证据按模块和工况展开，支持同输入端点合并和图表追溯。[Excel 导出说明](docs/EXCEL_REPORT.md) |
| LTspice 联动 | 通用可配置行为控制器、可读 ASC 工程、仿真运行与计算对比；支持已接入的反激、QR、有源钳位正激、Buck/Boost 和 LLC 模式 |
| 自动化接口 | 无 GUI 的计算服务、Python API、CLI 和 MCP 入口，便于与其他工程工具联动 |

### 计算图示例

随附三路反激算例中 OUT1 的电流、整流二极管反压、输出纹波和输出电压。下图属于模型计算波形。

![三路反激 OUT1 计算波形](docs/images/flyback-output-waveforms.png)

## 使用流程

桌面版顶部「功能架构」可在独立窗口打开三张图解。沿流程查看场解矩阵、裕量、计算输入、设计快照和电路仿真之间的关系。点击功能卡片可直接打开对应的离线图文教程。[软件操作教程](resources/help/operations/index.html)

辅源画布顶部「架构示例」可载入分阶段电源树联合启停或[双源二极管 OR 汇流](examples/SYSTEM_AUX_ORING.json)。双击电源模块或 LDO，在同一窗口进入单元设计。

1. 在供电画布添加源、电源模块、OR 汇流及负载，建立供电关系。
2. 进入单元，选择拓扑，设置输入电压上下限、输出需求、频率和预设效率。
3. 配置器件、曲线、电容组、磁芯与绕组；多路输出选择主反馈路。
4. 检查工作点、损耗、波形、磁密与环路，逐项处理检查提示。
5. 按需导出 LTspice 工程，复核计算与开关仿真的差异。
6. 导出 Word/Excel 报告，保存工程 JSON 及系统连接。

在桌面「仿真配置中心」配置单元电路、变压器电磁和联合仿真。电磁页复用工程绕组、三维定位、磁材和气隙，并列出设备或磁芯缺项。设备与模型页集中登记本机软件和可选磁芯 CAD。详见 [联合报告与参数回填](docs/JOINT_SIMULATION.md)。

在架构页打开「仿真配置中心 → 系统启停」，集中设置整张电源树的试验条件。打开 `examples/SYSTEM_STAGED_STARTUP.json` 可配置双源恒流、二极管 OR、两级 Buck、LDO 和板卡分阶段负载。`examples/SYSTEM_STARTUP_SHUTDOWN.json` 保留原单阶段基线。源电压事件、负载阶段和多轨就绪条件均有表格编辑入口。默认源保护比较门限，显式选择恒流、折返或打嗝后才改变电路。源、板卡负载与 LDO 均按声明的行为近似。

QR 多路 SSR 的交叉调整率：在左侧设置各路实际最大/最小功率，启用“绕组两两耦合”并填入正定 kij 矩阵。桌面版在与“环路”并列的“交叉调整率”页选择“扫描负载角点”。Word/Excel及联合仿真报告显示同一硬件在 Vinmin/Vinmax 下的电压包络、负载组合与实际开关频率。参考点由Kc选RCD一次，角点固定同一阻容联立平均钳位功耗，不重新选择R/C。没有负载差就不代表已覆盖轻重载；真空载或无自洽单周期谷底的角点明确留为未完成。QR直流跨调采用矩阵换流/退磁/恒定电容谷底时序，低频环路仍是约化模型，不能代替完整换流线性化或实测。详见 [模型与边界](docs/CROSS_REGULATION.md)，计算说明第20章。此功能覆盖桌面与本地Python网页/API，独立TypeScript浏览器内核暂未移植。

在桌面电源单元打开「⑪ 硬件容差边界与分布评估」，核对各路输出范围、纹波、动态峰峰值和相位裕度验收线（严格大于 45°），再点击「计算极限容差」。结果列出理论边界、已算候选中最不利的工况和选择依据。发现超限后，可点击「运行蒙特卡洛」，沿用本轮固定的硬件和补偿估计失效概率。结果可随 Word 或 Excel 设计报告保存。[容差评估说明](docs/TOLERANCE_ANALYSIS.md)

直接打开「⑫ 工程验证与验收」，可刷新两端计算、导入带参数指纹的仿真 JSON/ZIP 并记录实测。验收按器件规格和电源外特性分组，使用器件 BOM、磁件参数、需求和环路中的限值。设计及联合 Word 和 Excel 在验收明细中列出各端点、来源和判定。联合报告同时保存场解、参数回填、电路试验及流程状态。Python 网页和 API 共用验收数据与报告内核。[验收说明](docs/ENGINEERING_ACCEPTANCE.md)

## 快速开始

### Windows 便携版

本机运行包位于 `releases/Windows-x64/`，功能和版本变化见 [更新日志](CHANGELOG.md)，构建方式见 [项目结构与发布](docs/PROJECT_STRUCTURE.md)。变压器支持完整线圈并绕，在磁件截面可点选、左右拖动及用方向键微调，位置随工程保存。内置示例并绕数为 1，磁材 DMR44、μi=2400，le=Ve/Ae。见 [并绕计算](docs/TRANSFORMER_ELECTRICAL.md)、[绕制操作](docs/WINDING_WINDOW.md) 与 [气隙说明](docs/TRANSFORMER_GAP.md)。

桌面和本地 Python 网页均将“文件”“示例”“自动设计”分列。从“自动设计”选择“按规格生成初版”。选择 FLYBACK 后可比较 CCM 与 DCM。已配置多路输出时，额定电流和最小电流指所选反馈路，其他路沿用工程负载。选值说明见《自动计算参数依据》第 7–9 章，可导入算例在 `output/反激自动设计初版/`。

- 桌面版：在 `PowerDesignDesktop` 中双击 `SwitchingPowerSupplyDesign_V0.exe`。
- 本地网页版：在 `PowerDesignWeb` 中双击 `StartWeb.cmd`。

桌面 LTspice 配置窗口可先选“快速预检（推荐）”，确认两端输入的启动、稳态、电流及纹波，再选“完整对比”运行 FRA 和交叉负载。已通过的相同标称仿真可复用；任务范围、实际运行/复用来源在报告中列明。见 [仿真对比说明](docs/SPICE_COMPREHENSIVE_COMPARISON.md)。

准谐振例程采用多绕组矩阵计算各路独立换流，ZCD 可自动或指定检测绕组。电流对比按实际完整周期统计，并检查辅助路电荷是否稳定；漏感振铃与正常谷底分别核对。见 [QR 电流与振铃](docs/QR_CURRENTS_AND_RINGING.md)。

该版在“计算方法与公式说明”第 19 章及“多路反激入门教程”第 16.5–16.17 节加入三路反激交叉调整率完整算例：参数、互感矩阵、分段换流、实际求解迭代、16 个角点及统计结果。两份文档保持原入口，公式可在 Word 中编辑。

复制完整程序文件夹，必须保留 `_internal`。运行包自带 Python 和计算依赖，目标电脑不需要安装 Python/Node；查看 Word/Excel 需要兼容的办公软件。Git 仓库不包含 EXE、虚拟环境或历史发布包，克隆源码后可按下文运行或自行构建。

### 从源码启动桌面版

已在 Windows / Python 3.13 环境验证。建议使用独立环境：

```powershell
python -m venv .venv-web
.\.venv-web\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-web\Scripts\python.exe desktop_entry.py
```

桌面版使用 Tkinter，Python 安装需包含 Tcl/Tk。

### 从源码启动本地网页版

另需 Node.js 20.19+、22.12+ 或 24+，以及 npm：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup_web.ps1
.\.venv-web\Scripts\python.exe run_web.py --open
```

准备脚本安装本项目环境的依赖并构建 Vue 前端。本地网页版通过 `127.0.0.1` 服务调用本机 Python 内核，不能只双击其中的 HTML 来替代服务。首次安装依赖需要联网，日常计算不用联网。

前端还保留独立 TypeScript 计算内核，其适用范围和 Python 版需要分别核对；组织专用的集成说明和部署脚本不在公开仓库中。

### Python API 与 CLI

```python
from design_api import run_design

report = run_design({
    "topology": "BUCK", "V_in": 24, "V_out": 12,
    "P_out": 24, "f_sw": 100e3, "L": 100e-6,
    "C_out": 220e-6,
})
print(report["ok"])
```

```powershell
.\.venv-web\Scripts\python.exe cli.py design --spec examples/40W_CCM_3OUT_FLYBACK.json --out output/design.json
.\.venv-web\Scripts\python.exe cli.py review --spec examples/40W_CCM_3OUT_FLYBACK.json --output-dir output/review-01 --report xlsx
```

`review` 使用同一套硬件的双端点计算结果，生成验收 JSON、计算快照和可选 Word 或 Excel 设计报告。结果目录须为新目录。退出码与响应中的 `ok` 表示计算和导出状态，工程判定见 `acceptance.json`。本机 Codex 可用 `$power-design-review` 调用该入口。

## 随附算例

全部19份JSON示例（含系统工程内的单元）已补入真实器件型号、参考计算参数与原厂来源；加载后可在“关键器件BOM与降额”查看。具体选值、条件和待核项见[示例器件初选与数据依据](docs/EXAMPLE_REAL_PARTS.md)。已保存的用户工程不会自动覆盖。

| 文件 | 用途 |
| --- | --- |
| [40W_CCM_3OUT_FLYBACK.json](examples/40W_CCM_3OUT_FLYBACK.json) | 三路 CCM 反激；文件名保留历史命名，实际需求以内容为准 |
| [90W_QR_L6565_252_442V_REFERENCE.json](examples/90W_QR_L6565_252_442V_REFERENCE.json) | L6565 逻辑参考 QR 反激，252–442 VDC 输入，双路输出与参考绕组 |
| [33W_3OUT_ACF_MP6005_COMPACT.json](examples/33W_3OUT_ACF_MP6005_COMPACT.json) | 三路有源钳位正激，MP6005 逻辑参考 |
| [SYSTEM_AUX_ORING.json](examples/SYSTEM_AUX_ORING.json) | 多源竞争、OR 汇流及负载网络 |
| [SYSTEM_LDO.json](examples/SYSTEM_LDO.json) | 含 LDO 的系统供电架构 |

## 项目结构

```text
desktop_entry.py      桌面入口与系统画布
main.py               单元计算界面
design_engine/        共享计算服务、数据合同与结果快照
power_stage.py        拓扑工作点与功率级
loss_model.py         损耗与效率汇总
magnetics.py          磁件计算
plants.py             小信号模型
web_app/              本地 Web 服务、Vue 界面与 TypeScript 内核
resources/            运行所需图像、图标与 SPICE 模型
examples/             JSON 算例
docs/                 使用说明、模型边界、公式文档与教程
tests/                计算、界面、报告、仿真和发布检查
tools/                环境准备、数据导出、构建和校验脚本
packaging/            PyInstaller 配置与发布模板
```

个人数据、第三方参考资料、独立器件提取/视频工程、外部集成部署文件及生成产物留在本地，不纳入仓库当前源码快照。

## 构建与验证

```powershell
.\.venv-web\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_release.ps1 -Target all -ReleaseId my-build
```

构建脚本拒绝覆盖同名发布目录。`tools/release_manifest.ps1` 校验文件清单，`tools/zip_release.ps1` 生成分发 ZIP。

代表性检查：

```powershell
.\.venv-web\Scripts\python.exe tests/design_engine_check.py
.\.venv-web\Scripts\python.exe tests/multi_output_charts_check.py
.\.venv-web\Scripts\python.exe tests/canvas_resources_check.py
.\.venv-web\Scripts\python.exe tests/resource_paths_check.py
```

部分检查仅适用于 Windows，需要显示会话、LTspice 或事先构建的运行包。检查通过说明对应代码路径和算例达到测试要求，不代表硬件已经验证。

## 文档

- [开始使用](开始使用.md)、[中文手册](docs/MANUAL_ZH.md)、[项目结构与发布](docs/PROJECT_STRUCTURE.md)
- [计算方法与公式说明（Word）](docs/reference/计算方法与公式说明.docx)、[开关电源介绍与计算方法（Word）](docs/reference/开关电源介绍与计算方法.docx)、[多路反激入门教程（Word）](docs/tutorials/多路反激电源设计入门教程.docx)、[自动计算参数依据（Word）](docs/reference/自动计算参数依据.docx)
- [项目文档写作与排版规范](docs/DOCUMENT_STYLE.md)
- [系统架构](docs/SYSTEM_WORKSPACE.md)、[LDO](docs/LDO_DESIGN.md)、[BOM 与降额](docs/COMPONENT_BOM_DERATING.md)
- [并联 ESR 环路模型](docs/PARALLEL_ESR_LOOP.md)、[寄生参数模型](docs/PARASITIC_MODELS.md)、[仿真对比](docs/SPICE_COMPREHENSIVE_COMPARISON.md)
- [更新日志](CHANGELOG.md)、[图表 UI 修正](docs/CHART_UI_FIX.md)
- [性能优化与复测](docs/PERFORMANCE.md)

## 模型边界与许可

本工具用于工程初选、教学及计算复核。效率、热、交叉调整率与寄生换流受模型假设和输入精度限制。计算波形、SPICE 波形、实测数据应分别标识。通用行为控制器参考芯片逻辑，不等同于原厂完整芯片模型。器件曲线、磁芯典型数据、寄生参数、安规和制造条件需结合规格书、样机及实测复核。

项目尚未指定开源许可证。仓库访问权限不代表授予第三方再分发许可；依赖库和参考资料遵循各自许可。
