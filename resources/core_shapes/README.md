# 磁芯机械参考目录

本目录服务于可旋转的三维结构预览。`catalog.json` 包含当前电气库全部 67 个型号，记录参考厂家、完整型号、规格书链接、页码、原图符号与显示尺寸。主要尺寸来自厂家机械图，不从有效磁截面积、磁体积或平均匝长反推。

## 证据与使用范围

| 状态 | 数量 | 含义 |
| --- | ---: | --- |
| `datasheet_nominal` | 58 | 按已指定厂家机械图的主要尺寸建立外形 |
| `reference_variant` | 8 | 库中短型号不足以唯一确定机械版本，明确选择一个厂家版本 |
| `designation_nominal` | 1 | T58x37x20 按型号给定的 58×37×20 mm 建立几何体，尚未绑定原厂料号 |

八个参考变体为 EE25、EE42、EE55、ER28、ER35、PQ32-25、PT18 和 PT22。ER28/35 采用列明的 TDK EER28/35；PT18 采用 Ferroxcube PT18/11；PT22 采用 TDK P22/13 外形。选择参考外形不等于确认实物型号，不改变原有电气参数。

厂商的同名磁芯可能具有不同厚度、柱径和高度。本目录 PQ32-25 明确选用东磁 PQ32/25：外宽 32 mm，半芯高 12.5 mm，沟深 8.1 mm；此前的 Ferroxcube 33 mm 宽参考版本已替换。PQ32-30 选用 TDK PC95PQ32/30Z-12：外宽 32 mm、深 22 mm、半芯高 15.175 mm、沟深 10.65 mm。它们使用各自图纸，不对邻近型号做统一比例缩放。

67 个名称中，59 个采用 TDK 或东磁资料；其余 7 个保持已有明确厂商的同型号参考，1 个磁环仍按型号尺寸。来源优先不改变型号：例如 PQ20/17 保留安磁原厂 Fig.1，不改成 TDK PQ20/16。几何和原工程的 DMR44、Ae、Ve、绕组及电气求解独立。

## 实体构造与投影校核

目录具有 40 个明确的二维实体截面；其余 27 个 E、EI、U 和磁环按尺寸约束的矩形、圆和环构造。软件内置已生成网格，运行时不下载原厂 PDF，也不调用外部建模软件。

| 系列 | 主要结构 |
| --- | --- |
| PQ | 收腰底轭、中央柱裸露圆弧、两个引线开口、窗口圆弧极靴；8 款 TDK 从各型号独立页提取矢量，另两款按自己的原厂图约束 |
| ER/EER/ETD | 按逐型号俯视外廓建立底轭，外柱内壁保留弧线，中央柱按图纸直径；不把弧形外柱改为矩形 |
| RM | 按 A/F/I/E 等尺寸及对应图示区分平面轮廓，保留侧面开口；不使用同一个八边形等比例替代全部型号 |
| EP | 前侧引线槽、后侧圆弧腔体和中央柱相对位置分别表达 |
| EFD/EPC | 保留扁平柱、偏心位置、梯形引线凹口或弧形外柱；各型号使用自己的图纸 |
| PM/PT | 按壳形芯内外径、通孔和引线开口构造；开口宽按图纸的弦宽定位 |
| E/EI/U/磁环 | 图纸主尺寸直接约束实体；EI 使用一个 E 芯与一块 I 板 |

PQ32-30 的底轭不是完整八边形板。其俯视收腰轮廓由 TDK 第 21 页的四段外轮廓形成；截去直径 27.5 mm 的窗口圆得到左右外柱，中央柱直径为 13.45 mm。底轭厚度为 15.175−10.65=4.525 mm。原图的 E 标注是 X 向肩间距，不是额外矩形槽的深度。

主尺寸使用图纸标注；未标角度、过渡圆弧由对应原图采样，并在 `shape_evidence.limits` 记录。独立笔画连接处的极小交叠需在生成时闭合，TDK PQ 修复面积最大约 0.0003 mm²。小倒角、夹具、骨架和引脚没有凭空补造。模型用于结构查看；电磁求解继续使用联合仿真已配置的 CAD 与网格。

## 坐标和单位

所有 `dimensions_mm` 都是毫米。X 为外廓宽，Y 为外廓深，Z 为绕线柱轴向及合模方向。一般双半芯以合模面为 Z=0，`half_height` 表示单个半芯高度，`window_height` 表示该半芯沟深。EI 的 `half_height` 为整个 E 芯高度，另用 `i_height` 表示 I 板厚。磁环使用整体 `height`。EPC 以中央柱为原点，其外廓可以不对称；EFD 的中央柱偏心单独记录，不把所有底轭强制居中。

`center_width` 和 `center_depth` 定义中心柱包络；圆柱另给 `center_diameter`。`window_outer_width` 表示两个外柱之间的窗口外边界，并非单侧可绕空间。壳形芯另给 `window_diameter`，磁环用 `inner_diameter`。UU 没有中央柱，该系列的中心柱字段只提供单侧绕线柱截面，模板按两侧柱解释。

图纸为上下限时取中点；对称公差取名义值。仅标最小值的尺寸取其下限建立参考边界。单边公差通常保留图纸基准值；明确采用区间中点的型号另记 `dimension_selection`，例如 TDK ETD54/59。目录未执行机械公差叠加分析。

`shape_profile.yoke_xy_mm` 为底轭闭合轮廓，`returns_xy_mm` 为各外柱轮廓，`center_xy_mm` 为可选中央柱截面。点坐标均为毫米，末点不必重复首点。`center_offset_xy_mm` 保留原图定位。窗口圆、中央通孔和轴向气隙由对应尺寸与场景参数处理。

## 维护方法

1. 在厂家原图中确认总成与半芯尺寸、窗口边界、柱截面和单位，选定完整参考型号。
2. 更新条目的 `dimensions_mm`、`drawing_dimensions_mm`、`dimension_mapping`、来源和必要备注。图纸有修订时记录修订日期。复杂轮廓同时维护 `shape_profile` 与 `shape_evidence`，保留原 PDF 的 SHA-256、页码、图形位置或路径索引和采样尺度。
3. 不把 `center_shape` 等文字放入 `dimensions_mm`；该对象只接受数值。新增轮廓模板需同时更新三维渲染器。
4. 运行 `tests/core_shape_catalog_check.py` 和 `tests/transformer_preview_scene_check.py`，重新生成网格，再检查主视、俯视、侧视及透明装配。尺寸包络通过不等于形状正确；至少核对窗口、引线口和中央柱位置。

可复现的构造脚本位于 `tools/extract_tdk_pq_profiles.py`、`tools/complete_pq_reference_profiles.py`、`tools/extract_tdk_etd_profiles.py`、`tools/extract_tdk_eer_profiles.py`、`tools/extract_tdk_epc_profiles.py` 和 `tools/build_nonpq_drawing_profiles.py`。图纸提取用 PyMuPDF，轮廓检查用 Shapely，均为维护工具依赖；应用运行不需要它们。原厂 PDF 留在忽略的 artifacts 中，不随运行包分发。

公开 API 位于 `core_shape_catalog.py`：`get_core_shape(model)` 返回独立副本，未知型号返回 `None`；`list_core_shapes()` 返回全部完整条目；`catalog_metadata()` 返回单位与字段说明。加载过程只读本地资源，不请求网络。运行包须包含整个 `resources/core_shapes` 目录。

原厂来源主要包括 TDK 的 E、EER、ETD、EFD、PQ、RM、EP、EPC 资料和东磁 MnZn/PQ 目录。EF30、PQ20/17、PT18、两款磁环和 UU9.8/10.5 使用各自列明的其他厂家资料。东磁旧 PQ32/25 图及部分其他厂家资料由镜像托管，目录明确区分作者与托管方。
