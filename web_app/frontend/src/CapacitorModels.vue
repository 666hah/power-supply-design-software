<script setup lang="ts">
import { computed, inject, ref } from 'vue';
import { capacitorMode, capacitorRef, capacitorRows, type CapacitorMode,
  type CapacitorModelEdit, type CapacitorSide } from './capacitor_inputs';
import type { Spec } from './types';

const props = defineProps<{ spec: Spec; multi: boolean }>();
const emit = defineEmits<{ change: [edit: CapacitorModelEdit] }>();
const native = inject('power-native', computed(() => false));
const port = ref('input');
const selected = ref(0);

type Group = { id: string; side: CapacitorSide; spec: Spec; title: string; railIndex?: number };
const groups = computed<Group[]>(() => [
  { id: 'input', side: 'input', spec: props.spec, title: '输入' },
  ...(props.multi ? props.spec.outputs.map((rail: Spec, railIndex: number): Group => {
    const id = `OUT${railIndex + 1}`;
    const title = rail.name?.trim();
    return { id, side: 'output', spec: rail, title: title && title !== id ? `${id} · ${title}` : id, railIndex };
  }) : [{ id: 'output', side: 'output', spec: props.spec, title: '输出' }]),
]);
const group = computed(() => groups.value.find(item => item.id === port.value) ?? groups.value[0]);
const groupRows = (item: Group) => capacitorRows(item.spec, item.side, item.railIndex === undefined ? undefined : props.spec);
const rows = computed(() => groupRows(group.value));
const activeIndex = computed(() => Math.min(selected.value, rows.value.length - 1));
const active = computed(() => rows.value[activeIndex.value]);
const mode = computed(() => capacitorMode(active.value));
const curve = computed(() => active.value?.impedance_curve);
const activeCount = computed(() => groups.value.reduce((count, item) => count
  + groupRows(item).filter(cap => capacitorMode(cap) === 'curve').length, 0));
function choosePort(event: Event) {
  port.value = (event.target as HTMLSelectElement).value;
  selected.value = 0;
}
function switchMode(event: Event) {
  const value = (event.target as HTMLSelectElement).value as CapacitorMode;
  if (value === 'curve' && (!curve.value || native.value)) return;
  const next = rows.value.slice();
  next[activeIndex.value] = { ...active.value, impedance_mode: value };
  emit('change', { side: group.value.side, railIndex: group.value.railIndex, rows: next });
}
</script>

<template>
  <details class="manual-events capacitor-models">
    <summary>电容模型<span v-if="activeCount"> · {{ activeCount }} 颗使用阻抗曲线</span></summary>
    <label class="cap-field">
      <span>电容组</span>
      <select :value="group.id" @change="choosePort">
        <option v-for="item in groups" :key="item.id" :value="item.id">{{ item.title }}</option>
      </select>
    </label>
    <label class="cap-field">
      <span>电容位号</span>
      <select :value="activeIndex" @change="selected = Number(($event.target as HTMLSelectElement).value)">
        <option v-for="(row, index) in rows" :key="index" :value="index">
          {{ capacitorRef(group.side, index, group.railIndex) }} · {{ capacitorMode(row) === 'curve' ? '阻抗曲线' : '固定参数' }}
        </option>
      </select>
    </label>
    <template v-if="active">
      <label class="cap-field">
        <span>电容模型</span>
        <select :value="mode" @change="switchMode">
          <option value="fixed">固定参数</option>
          <option value="curve" :disabled="!curve || native">阻抗曲线</option>
        </select>
      </label>
      <small v-if="native">阻抗曲线模型由桌面版或本地 Python 网页计算。</small>
      <small v-else-if="!curve">先在对应电容组的「阻抗曲线与热阻」导入曲线。</small>
    </template>
  </details>
</template>

<style scoped>
.capacitor-models { border-top: 1px solid #d8e2ed; border-bottom: 1px solid #d8e2ed; padding: 2px 0 8px; }
.cap-field { display: grid; grid-template-columns: 6em minmax(0, 1fr); align-items: center; gap: 6px; margin-top: 8px; }
.cap-field select { width: 100%; min-width: 0; box-sizing: border-box; }
.capacitor-models small { display: block; margin: 6px 0; font-size: .85em; }
</style>
