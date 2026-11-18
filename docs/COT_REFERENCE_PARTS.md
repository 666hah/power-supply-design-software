# 四相 COT Buck：器件与验证依据

## 1 规格和实际器件

10–14 V 输入、1.2 V / 80 A 输出、四相，400 kHz 目标频率。负载从 80 A 减到 40 A，边沿 1 µs，动态偏差限值 ±60 mV。输入两端采用同一硬件、同一 PI 和同一保护阈值。

| 功能 | 型号 / 数量 | 录入值与条件 |
|---|---|---|
| 高侧 MOS | TI CSD17577Q3A，每相一颗 | 30 V；Rds 5.3 mΩ（4.5 V/10 A）；Qg 13 nC；Coss 208 pF（15 V），采用电气特性表 |
| 低侧 MOS | TI CSD17576Q5B，每相一颗 | 30 V；Rds 2.4 mΩ（4.5 V/25 A）；Qg 25 nC；Coss 389 pF（15 V）；Qrr 14.7 nC（15 V、25 A、300 A/µs） |
| 电感 | Coilcraft XAL7030-301MEC，每相一颗 | 0.30 µH±20%；DCR 典型1.75/最大1.92 mΩ；Isat 41 A 对应L下降30%；Irms 27.6 A 对应温升40 K |
| 输入电容 | Panasonic 25SVPF330M，4颗 | 每颗330 µF±20%、25 V、ESR上限14 mΩ（100 kHz）、纹波5 A |
| 输出电容 | Panasonic 2R5TPE330M9，16颗 | 每颗330 µF±20%、2.5 V、ESR上限9 mΩ（100 kHz）、纹波3.9 A |
| 控制结构 | TI TPS536C7B1 / D-CAP+参考 | 公开电流反馈、定时和均流结构；增益与保护阈值为本项目配置 |

本例的离散功率器件与控制行为分别引用，不等同 TPS536C7 原厂参考板或完整引脚电路。相同标称型号叠加逐相工程失配。

## 2 项目假设与定值

每颗 ESL 取 2 nH，电感附加损耗取 0.15 W/相，均为工程假设。MOS Coss 为规格书单电压点，并未拟合完整非线性曲线。聚合物电容电压和纹波采用 0.8 初选余量，是项目选择。

源电阻10 mΩ、源电感100 nH、输入上升1 ms。2 ms使能、软启动2 ms、5 ms卸载、7 ms关机、8 ms结束。限流32 A/相，检测延迟20 ns，死区20 ns，输入峰流限值20 A。

总电流反馈4000 Hz/A、滤波30 kHz；均流0.02 V/A、带宽2 kHz，占空比修正上限5%。固定Kp=2450332.0777366706 Hz、Ki=9.367015802142029×10¹⁰ Hz/s，以10 V下20 kHz/80°为目标整定。

## 3 选容与本轮验证

12颗330 µF、5 kHz/85°候选的平均闭环与开关仿真均超过60 mV。改为16颗、重新整定后，40 A卸载的计算偏差约50 mV。电荷初筛、平均闭环及开关仿真分别保留，没有放宽过冲标准。

实际LTspice的10 V/14 V卸载峰值为1.25189/1.25214 V，即4.324%/4.345%。全程最大相峰值不超过29.1 A；无OCP/OVP动作及上下管同时导通。输入峰流约13.32/18.64 A。实际每相频率约433/432 kHz，按实际频率比较。

10 V完整周期时权复核：各相平均电流最大差4.8 mA、RMS最大差6.9 mA、峰值最大差34.2 mA。均值按时间积分，避免LTspice非均匀时间步的算术平均偏差。

开关FRA的10 V/14 V穿越约20.250/20.305 kHz，PM约78.917°/79.014°；主幅与半幅最大差0.169 dB/1.803°。GM在有效频带内未覆盖，报告保留该项。步长减半后的输出均值差约0.055 µV、卸载峰差约3.815 µV。

## 4 配置与原厂资料

算例为 `examples/96W_BUCK_COT_4PH.json`；`tools/build_cot_reference_example.py` 可重建本例器件和控制配置。全部数值以JSON的SI单位为准。

- [CSD17577Q3A，SLPS515A §5.1](https://www.ti.com/lit/ds/symlink/csd17577q3a.pdf)。
- [CSD17576Q5B，SLPS497A §5.1](https://www.ti.com/lit/ds/symlink/csd17576q5b.pdf)。
- [XAL7030，Document 863-1](https://www.coilcraft.com/getmedia/0d05a05e-d55d-4a0c-911d-46bd73686633/xal7030.pdf)。
- [25SVPF330M原厂数据](https://na.industrial.panasonic.com/products/capacitors/polymer-capacitors/series/91057/model/91095)。
- [2R5TPE330M9原厂数据](https://util01.industrial.panasonic.com/ww/utilities/ds/chr-vw/2R5TPE330M9)。
- [TPS536C7数据手册 §7.6](https://www.ti.com/lit/ds/symlink/tps536c7.pdf)。
