# 电容阻抗、分流与温升

## 1. 输入与计算范围

输入电容组、单路输出以及多路隔离电源各输出的电容可分别导入扫频数据。每颗保留标称容量、固定 ESR 和 ESL，同时可输入装配条件下的单颗热阻 `Rθ`，单位 K/W。工程 JSON 内嵌曲线，复制工程时可直接重算。

展开对应的输入或输出电容组，选中电容后导入阻抗曲线或填写热阻。电容数量和标称 C/ESR/ESL 也在该组调整。准备好数据后，在「器件模型精度选择」按端口和位号选择固定参数或阻抗曲线。切回固定参数后，已存曲线可再次启用。

可导入下面格式的 CSV，单位为 Hz、Ω、度。幅值应大于零，频率应为互异正数，电容性相位为负，感性相位为正。扫频仪应导出阻抗 `Z` 的相位。测量时记录直流偏置、激励大小和温度，并按夹具执行开短路补偿。 [Keysight 阻抗测量手册](https://www.keysight.com/zz/en/assets/7018-06840/application-notes/5950-3000.pdf)

```csv
frequency_hz,magnitude_ohm,phase_deg
50000,0.0266,-15.3
100000,0.0210,-5.0
200000,0.0180,8.0
```

启用曲线的支路在扫频范围内使用表中复阻抗。中间点沿对数频率对实部和虚部分别插值。扫频带外和选择固定参数的支路采用该颗固定 RLC。环路、LTspice 时域和标称低频纹波估算也采用固定参数。设计报告把固定 ESR 与当前工况下的等效 ESR 分列。

工程 JSON 将模式记录在每颗电容的 `impedance_mode`，固定参数为 `fixed`，启用扫频为 `curve`。历史工程缺少该字段时，已导入曲线的电容继续按扫频计算，其余使用固定参数。

## 2. 逐频点分流与损耗

记 `fₕ` 为纹波频谱中第 `h` 个正频率，`|Zⱼ|` 为第 `j` 颗电容在该频率的阻抗幅值（Ω），`φⱼ` 为相位。复阻抗为 `Zⱼ = |Zⱼ|(cos φⱼ + j sin φⱼ)`，`Yⱼ = 1/Zⱼ` 为复导纳（S）。`I组,ₕ` 是同一并联组纹波电流的 RMS 相量（A）。

```text
Iⱼ,ₕ = I组,ₕ × Yⱼ(fₕ) / ΣₖYₖ(fₕ)
Pⱼ = Σₕ |Iⱼ,ₕ|² Re[Zⱼ(fₕ)]
ΔTⱼ = Pⱼ Rθ,ⱼ
```

`Pⱼ` 是单颗总纹波损耗（W），`ΔTⱼ` 是相对局部环境的稳态自热估算（K）。温升随 PCB 铜皮、风速和装配改变，未填热阻时保留损耗。等效 ESR 定义为 `Pⱼ/Σₕ|Iⱼ,ₕ|²`，随纹波频谱变化。曲线覆盖率是扫频范围内的支路均方电流占比，可用于识别超出扫频范围的频带。 [KEMET 纹波电流与自热](https://www.kemet.com/en/us/technical-resources/ripple-current-and-mlcc-basic-principles.html)

## 3. 对照算例

从软件「示例」菜单打开「Buck · 并联电容阻抗与温升 · 合成数据」。该例为 18–30 V 输入、12 V / 24 W 输出、50 kHz 开关频率，输入两颗电容、输出三颗。合成阻抗由固定 RLC 串联一个并联 RC 支路生成，扫频范围 100 Hz–20 MHz。固定 ESR 取同一支路在 100 kHz 的阻抗实部。合成阻抗和热阻不对应具体器件型号。

示例工程 [24W_BUCK_CAP_IMPEDANCE.json](../examples/24W_BUCK_CAP_IMPEDANCE.json) 已包含全部数据。单独导入可用 [input-c1.csv](../examples/capacitor_impedance_curves/input-c1.csv)、[input-c2.csv](../examples/capacitor_impedance_curves/input-c2.csv)、[output-c1.csv](../examples/capacitor_impedance_curves/output-c1.csv)、[output-c2.csv](../examples/capacitor_impedance_curves/output-c2.csv) 和 [output-c3.csv](../examples/capacitor_impedance_curves/output-c3.csv)。重新生成数据使用 `tools/build_capacitor_impedance_example.py`。

| 满载比较 | 18 V 固定 RLC | 18 V 扫频 | 30 V 固定 RLC | 30 V 扫频 |
| --- | ---: | ---: | ---: | ---: |
| 输入电容组损耗 / mW | 25.80 | 29.25 | 33.99 | 38.40 |
| 输出电容组损耗 / mW | 3.37 | 3.39 | 12.10 | 12.34 |
| 输出电容端总纹波 / mVpp | 27.74 | 39.37 | 51.81 | 74.10 |

30 V 满载时，47 µF 输出支路的 RMS 电流从 0.276 A 增至 0.353 A，损耗从 1.10 mW 增至 2.40 mW。采用示例中 55 K/W 的单颗热阻，自热由 0.061 K 增至 0.132 K。两端点逐颗曲线覆盖率最低为 99.32%。
