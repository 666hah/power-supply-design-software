# 变压器三维预览资源

此目录是桌面预览窗口的离线显示层。读取 Python 共享绕制评估的毫米制快照，显示磁芯主要机械尺寸、逐匝等效线束和串联绕组跨线。预览几何独立于电气与场求解输入。

`viewer.js` 和 `winding_paths.js` 是可维护源码，`viewer.bundle.js` 是随软件分发的本地 IIFE。`core_geometry.js` 是无界面依赖的构建期几何生成器，生成的各型号网格保存在 `resources/core_shapes/meshes`。程序直接读取这些内置网格。`index.html` 通过本地文件路径载入，无需互联网、CDN 或命令行服务。

`window.updateScene(payload)` 接收 `power-transformer.preview.v1` 快照及首次 `core_mesh`；浏览库时调用宿主 `core_mesh(model)` 按白名单读取。`window.previewDiagnostics()` 提供只读验收指标，`window.previewScreenshot()` 强制渲染当前帧并返回 PNG（隐藏窗口也适用）。桌面截图调用宿主 `save_png`。

## 显示约定

- 坐标 X/Y 是横截面，Z 是绕组轴；全部尺寸为 mm。与计算输入的 SI 米制换算在 Python 数据边界完成。
- 芯体默认不透明度 16%；绕组采用深铜、深蓝、墨绿等颜色，保持可分辨。所有旋转、缩放、分解与隐藏均为视图操作。
- 各线束轨迹按逐匝截面连续推进。串联相邻层在同端换层，隔层沿轴向折返至骨架下端。已声明的引线优先采用其毫米坐标，其余折返路径及局部抬高为工艺示意。利兹线按等效线束显示。
- 规格书机械尺寸与原电气磁芯库各自保存。复杂磁芯使用指定原厂三视图轮廓，原始路径及尺寸来源写入目录；图纸未注出的局部加工细节保留说明。场仿真继续使用独立确认的 CAD。缺少尺寸的型号不生成虚假的芯体。
- 立体视角采用透视相机；正视、俯视和侧视采用正交相机，可选择完整装配或单半芯检查轮廓、窗口和中柱。
- `spacer` 把上下半芯整体分开；`center_leg_ground` 只缩短中柱。显示真实声明气隙，不把电气等效气隙当作加工尺寸。
- 分层隐藏只减少屏幕绘制；数据不删除。单次逐匝容量由 Python 入口明确检查。

## 重建

从仓库根目录执行：

```powershell
npm.cmd install --prefix artifacts/transformer-preview-build --no-audit --no-fund --ignore-scripts three@0.170.0 esbuild@0.25.12
node resources/transformer_preview/build.mjs
.\.venv-web\Scripts\python.exe tools/build_core_meshes.py
```

固定依赖：Three.js 0.170.0（MIT，许可证见 `THREE-LICENSE.txt`）；esbuild 0.25.12 仅用于生成 bundle，不随应用执行。官方源为 [Three.js](https://github.com/mrdoob/three.js/tree/r170) 与 [esbuild](https://github.com/evanw/esbuild/tree/v0.25.12)。Three.js 的网格、材质和 OrbitControls 负责 GPU 视图；几何参数来源保存在 `resources/core_shapes/catalog.json`。
