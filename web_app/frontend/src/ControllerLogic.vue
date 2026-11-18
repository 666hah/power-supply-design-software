<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue';
import type { Spec } from './types';

type Point = [number, number];
type DiagramItem = {
  id: string;
  key?: string;
  parameter?: string;
  focus_fields?: string[];
  kind: 'block' | 'comparator' | 'latch' | 'driver' | 'sum' | 'pin' | 'note';
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  detail?: string;
  side?: 'left' | 'right';
  pins?: { name: string; x: number; y: number }[];
};
type Schematic = {
  width: number;
  height: number;
  title?: string;
  source?: string;
  boundary: [number, number, number, number];
  items: DiagramItem[];
  routes: { points: Point[]; label?: string; label_at?: Point; arrow?: boolean; tone?: string }[];
  junctions?: Point[];
};

const props=defineProps<{ definition:Spec; values:Spec; design:Spec; selected:string }>();
const emit=defineEmits<{ selected:[key:string] }>();
const activeKey=computed(()=>props.definition.parameters[props.selected]?props.selected:Object.keys(props.definition.parameters)[0]);
const active=computed(()=>props.definition.parameters[activeKey.value]);
const scroll=ref<HTMLElement|null>(null);
const diagram = ref<SVGSVGElement | null>(null);
const zoom = ref(100);
const arrowId = `controller-arrow-${useId()}`;
const schematic = computed<Schematic | undefined>(() => {
  const topology = props.design.topology;
  const selected = Number(props.values.niso_profile);
  const defaultProfile = topology === 'BOOST' ? 3 : props.design.control_mode === 'Voltage Mode' ? 1 : 2;
  const voltageMode = props.design.control_mode === 'Voltage Mode';
  return props.definition.schematic_variants?.[selected || defaultProfile]
    ?? (voltageMode ? props.definition.schematic_voltage : undefined)
    ?? props.definition.schematic;
});
const viewBox = computed(() => {
  const bounds = schematic.value ?? props.definition;
  return `0 0 ${bounds.width} ${bounds.height}`;
});
const title = computed(() => schematic.value?.title || '芯片控制逻辑 · 仿真模型');
const source = computed(() => schematic.value?.source || props.definition.source);
const inspected = ref<DiagramItem | null>(null);
const inspectedGroup = computed(() => props.definition.nodes.find((node: Spec) => node.id === inspected.value?.key));
const matchesParameter = (item: DiagramItem) => item.parameter === activeKey.value || item.focus_fields?.includes(activeKey.value);
const hasExactSymbol = computed(() => schematic.value?.items.some(matchesParameter) ?? false);
const activeItems = computed(() =>
  schematic.value?.items.filter(item => selectedSymbol(item)) ?? [],
);
const points = (values: Point[]) => values.map(point => point.join(',')).join(' ');

function reveal() {
  const viewport = scroll.value;
  const svg = diagram.value;
  const node = activeItems.value.find(item => item.w > 0) ?? activeItems.value[0]
    ?? props.definition.nodes.find((item: Spec) => item.id === active.value.node);
  if (!viewport || !svg || !node) return;
  const scale = svg.clientWidth / (schematic.value ?? props.definition).width;
  const left = (node.x - 26) * scale;
  const right = (node.x + node.w + 26) * scale;
  const top = (node.y - 26) * scale;
  const bottom = (node.y + node.h + 26) * scale;
  if (left < viewport.scrollLeft || right > viewport.scrollLeft + viewport.clientWidth) {
    viewport.scrollLeft = Math.max(0, left);
  }
  if (top < viewport.scrollTop || bottom > viewport.scrollTop + viewport.clientHeight) {
    viewport.scrollTop = Math.max(0, top);
  }
}
function setZoom(value: number) {
  zoom.value = value;
  void nextTick(reveal);
}
watch(activeKey, reveal, { flush: 'post' });
watch([() => props.selected, schematic], () => { inspected.value = null; });
function value(key:string,compact=false):string {
  const meta=props.definition.parameters[key];
  const n=Number(props.values[key] ?? props.design.spice_config?.[key] ?? meta?.default ?? 0);
  if (!Number.isFinite(n)) return '编辑中…';
  if (key==='qr_zcd_delay_ns' && n===-1) return '自动估算';
  if (key==='acf_dead_ns' && n===0) return `沿用设计 ${Number(props.design.forward_dead_time || 100e-9)*1e9} ns`;
  if (compact && props.definition.short_choices[key]) return props.definition.short_choices[key][String(n)] || '编辑中…';
  if (key==='frequency_hz' && !n) return `跟随设计 ${Number(props.design.f_sw)/1000} kHz`;
  if (!n && ['kp','fz1','fp1','fz2','fp2'].includes(key)) return '沿用软件';
  if (!n && ['cs_limit','comp_voltage_max'].includes(key)) return '自动确定';
  return meta?.unit==='Hz' && Math.abs(n)>=1000 ? `${n/1000} kHz` : `${n}${meta?.unit?' '+meta.unit:''}`;
}
function pick(node?:string) {
  if (!node || active.value.node === node) return;
  const key=Object.keys(props.definition.parameters).find(k=>props.definition.parameters[k].node===node);
  if(key)emit('selected',key);
}
function pickSymbol(node: DiagramItem) {
  if (node.parameter && props.definition.parameters[node.parameter]) {
    inspected.value = null;
    if (node.parameter !== activeKey.value) emit('selected', node.parameter);
    return;
  }
  const parameters = props.definition.parameters;
  const hasParameter = Object.keys(parameters).some(key => parameters[key].node === node.key);
  inspected.value = hasParameter ? null : node;
  if (hasParameter) pick(node.key);
}
function selectedSymbol(node: DiagramItem) {
  if (inspected.value) return inspected.value.id === node.id;
  return hasExactSymbol.value ? matchesParameter(node) : node.key === active.value.node;
}
function summary(row:Spec) { return row.values.map((k:string)=>`${props.definition.short_labels[k] || k} ${value(k,true)}`).join(' / '); }
const stateNote=computed(()=>{
  const n=(key:string,defaultValue=0)=>Number(props.values[key] ?? defaultValue);
  if (['ss_comp_start_v','ss_comp_end_v'].includes(props.selected) && n('soft_start_mode')!==2) return '当前软启动模式未使用此项；COMP上限缓升时生效。';
  if (props.selected==='soft_start_current_fraction' && n('soft_start_mode')!==1) return '当前软启动模式未使用此项；CS限流缓升时生效。';
  if (props.selected==='slope' && n('slope_mode',1)!==2) return '当前使用自动/设计斜坡，手动值暂不生效。';
  if (props.selected==='hiccup_off_ms' && n('short_mode')!==1) return '当前不是打嗝模式，等待时间暂不生效。';
  if (['scp_threshold_v','scp_blanking_ns','olp_enabled','olp_ms','ocp_hold_us'].includes(props.selected) && !n('short_mode')) return '当前仅逐周期限流，不执行SCP/OLP故障关断。';
  if (['fz2','fp2'].includes(props.selected)) return '第二组零极点只作用于三型；二型保留此值但不使用。';
  return '';
});
</script>
<template>
  <aside class="controller-logic" aria-label="控制器内部逻辑与参数说明">
    <div class="logic-toolbar">
      <h4>控制器逻辑框图</h4>
      <div class="logic-zoom" role="group" aria-label="框图缩放">
        <button type="button" aria-label="缩小框图" :disabled="zoom === 100" @click="setZoom(zoom - 25)">−</button>
        <button type="button" aria-label="适合宽度" :disabled="zoom === 100" @click="setZoom(100)">{{ zoom }}%</button>
        <button type="button" aria-label="放大框图" :disabled="zoom === 200" @click="setZoom(zoom + 25)">＋</button>
      </div>
    </div>
    <div class="logic-scroll" ref="scroll">
      <svg ref="diagram" :viewBox="viewBox" :style="{ width: `max(${zoom}%, ${5.15 * zoom}px)` }" role="group" :aria-label="title">
        <defs>
          <marker :id="arrowId" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 z" fill="#344956" />
          </marker>
        </defs>
        <template v-if="schematic">
          <rect class="logic-boundary" :x="schematic.boundary[0]" :y="schematic.boundary[1]"
            :width="schematic.boundary[2]" :height="schematic.boundary[3]" />
          <text class="logic-chip-title" :x="schematic.boundary[0] + 14" :y="schematic.boundary[1] + 21">{{ title }}</text>
          <g v-for="(route, i) in schematic.routes" :key="i">
            <polyline class="logic-wire" :class="{ 'logic-wire-external': route.tone === 'external', 'logic-wire-protection': route.tone === 'protection' }"
              :points="points(route.points)" :marker-end="route.arrow === false ? undefined : `url(#${arrowId})`" />
            <text v-if="route.label && route.label_at" class="logic-signal" :x="route.label_at[0]"
              :y="route.label_at[1]">{{ route.label }}</text>
          </g>
          <circle v-for="([x, y], i) in schematic.junctions" :key="i" class="logic-junction" :cx="x" :cy="y" r="3" />
          <g v-for="node in schematic.items" :key="node.id"
            :class="['logic-symbol', { 'logic-selectable': node.key, 'logic-selected': selectedSymbol(node) }]"
            :role="node.key ? 'button' : undefined" :tabindex="node.key ? 0 : undefined" :aria-label="node.label"
            :aria-pressed="node.key ? selectedSymbol(node) : undefined"
            @click="node.key && pickSymbol(node)" @keydown.enter="node.key && pickSymbol(node)" @keydown.space.prevent="node.key && pickSymbol(node)">
            <title>{{ [node.label, node.detail].filter(Boolean).join(' · ') }}</title>
            <template v-if="node.kind === 'pin'">
              <circle class="logic-shape" :cx="node.x" :cy="node.y" r="4" />
              <text class="logic-pin" :x="node.x + (node.side === 'right' ? 10 : -10)" :y="node.y"
                :text-anchor="node.side === 'right' ? 'start' : 'end'">{{ node.label }}</text>
            </template>
            <text v-else-if="node.kind === 'note'" class="logic-signal logic-note" :x="node.x + node.w / 2"
              :y="node.y + node.h / 2" text-anchor="middle" dominant-baseline="central">{{ node.label }}</text>
            <template v-else>
              <polygon v-if="node.kind === 'comparator' || node.kind === 'driver'" class="logic-shape"
                :points="points([[node.x, node.y], [node.x + node.w, node.y + node.h / 2], [node.x, node.y + node.h]])" />
              <circle v-else-if="node.kind === 'sum'" class="logic-shape"
                :cx="node.x + node.w / 2" :cy="node.y + node.h / 2" :r="Math.min(node.w, node.h) / 2" />
              <rect v-else class="logic-shape" :x="node.x" :y="node.y" :width="node.w" :height="node.h" />
              <text class="logic-symbol-name"
                :x="node.x + node.w * (node.kind === 'comparator' || node.kind === 'driver' ? .39 : .5)"
                :y="node.y + node.h / 2" text-anchor="middle">{{ node.label }}</text>
              <text v-for="pin in node.pins" :key="pin.name + pin.x + pin.y" class="logic-signal logic-symbol-pin"
                :x="pin.x" :y="pin.y">{{ pin.name }}</text>
            </template>
          </g>
        </template>
        <template v-else>
          <rect x="32" y="164" width="656" height="628" class="logic-boundary" />
          <text x="48" y="187" class="logic-chip-title">{{ title }}</text>
          <polyline v-for="(edge,i) in definition.edges" :key="i" :points="points(edge)"
            class="logic-wire" :marker-end="`url(#${arrowId})`" />
          <g v-for="node in definition.nodes" :key="node.id" role="button" tabindex="0" :aria-label="node.title"
            :aria-pressed="active.node===node.id" :class="['logic-selectable', { 'logic-selected': active.node === node.id }]"
            @click="pick(node.id)" @keydown.enter="pick(node.id)" @keydown.space.prevent="pick(node.id)">
            <rect :x="node.x" :y="node.y" :width="node.w" :height="node.h" class="logic-shape" />
            <text :x="node.x+12" :y="node.y+27" class="logic-node-title">{{ node.title }}</text>
            <text v-for="(line,i) in node.body" :key="i" :x="node.x+12" :y="node.y+53+Number(i)*20" class="logic-node-body">{{ line }}</text>
            <text :x="node.x+12" :y="node.y+node.h-14" class="logic-node-value">{{ summary(node) }}</text>
          </g>
        </template>
      </svg>
    </div>
    <div class="logic-description" aria-live="polite">
      <template v-if="inspected">
        <strong>{{ inspected.label }}</strong>
        <p v-if="inspected.detail">{{ inspected.detail }}</p>
        <p v-for="line in inspectedGroup?.body" :key="line">{{ line }}</p>
      </template>
      <template v-else>
        <strong>{{ active.label }} · {{ value(activeKey) }}</strong>
        <p>{{ active.purpose }}</p><p>{{ active.meaning }}</p>
        <p v-if="stateNote" class="logic-state">{{ stateNote }}</p>
      </template>
    </div>
    <p class="logic-caption">点选输入参数或图中符号，查看对应的模型说明。</p>
    <a v-if="source" :href="source" target="_blank" rel="noopener noreferrer">芯片数据手册</a>
  </aside>
</template>
