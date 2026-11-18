<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref } from 'vue';
import { request } from './api';
import { capacitorMode, capacitorRef, capacitorRows, type Capacitor, type CapacitorSide, type ImpedanceCurve, type NominalKey } from './capacitor_inputs';
import { fmt, type Spec } from './types';

const props = withDefaults(defineProps<{ spec: Spec; side?: CapacitorSide; railIndex?: number; scalarFallback?: Spec }>(), { side: 'output' });
const emit = defineEmits<{ change: [value: Capacitor[]] }>();
const nominalFields = [['C', 1e-6], ['ESR', 1e-3], ['ESL', 1e-9]] as const;
const count=ref('');
const rows = computed(() => capacitorRows(props.spec, props.side, props.scalarFallback));
const native = inject('power-native', computed(() => false));
const selected = ref(0);
const activeIndex = computed(() => Math.min(selected.value, rows.value.length - 1));
const active = computed(() => rows.value[activeIndex.value]);
const sweep = computed(() => active.value?.impedance_curve);
const mode = computed(() => capacitorMode(active.value));
const curveRange = computed(() => {
  const points = sweep.value?.points;
  if (!points?.length) return '';
  return `${fmt(points[0][0], 'Hz', 5)} – ${fmt(points.at(-1)?.[0], 'Hz', 5)}`;
});
const importing = ref(false);
const importError = ref('');
let pending: AbortController | undefined;

function resize(n:number){
  if(!Number.isInteger(n)||n<1)return;
  const old=rows.value;
  emit('change',Array.from({length:n},(_,i)=>({...old[Math.min(i,old.length-1)]})));
  count.value='';
}
function editNominal(index: number, key: NominalKey, scale: number, event: Event) {
  const field = event.target as HTMLInputElement;
  const next = rows.value.slice();
  next[index] = { ...next[index], [key]: Number(field.value) * scale };
  emit('change', next);
}
function remove(index: number) {
  if (rows.value.length === 1) return;
  if (index < activeIndex.value) selected.value = activeIndex.value - 1;
  emit('change', rows.value.filter((_, row) => index !== row));
}
function editData(index: number, values: Partial<Capacitor>) {
  const next = rows.value.slice();
  const updated = { ...next[index], ...values };
  if (updated.impedance_curve === undefined) delete updated.impedance_curve;
  if (updated.thermal_resistance_K_per_W === undefined) delete updated.thermal_resistance_K_per_W;
  next[index] = updated;
  emit('change', next);
}
function removeSweep() {
  if (mode.value === 'fixed') editData(activeIndex.value, { impedance_curve: undefined });
}
function editThermal(event: Event) {
  const field = event.target as HTMLInputElement;
  const value = field.value.trim() ? field.valueAsNumber : undefined;
  if (value !== undefined && (!Number.isFinite(value) || value <= 0)) {
    field.setCustomValidity('热阻须大于 0，清空可恢复为未设置。');
    field.reportValidity();
    return;
  }
  editData(activeIndex.value, { thermal_resistance_K_per_W: value });
}
async function loadSweep(event: Event) {
  const field = event.target as HTMLInputElement;
  const file = field.files?.[0];
  field.value = '';
  if (!file || importing.value) return;
  importError.value = '';
  if (file.size > 2_000_000) {
    importError.value = '电容阻抗曲线文件不能超过 2 MB。';
    return;
  }
  const bank = rows.value;
  const index = activeIndex.value;
  const controller = new AbortController();
  pending = controller;
  importing.value = true;
  try {
    const sweepData = await request<ImpedanceCurve>(`/capacitors/impedance?filename=${encodeURIComponent(file.name)}`, {
      method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' }, signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    if (rows.value !== bank) {
      importError.value = '这组电容已更改，请重新选择曲线文件。';
      return;
    }
    editData(index, { impedance_curve: sweepData, impedance_mode: capacitorMode(bank[index]) });
  } catch (error) {
    if (!controller.signal.aborted)
      importError.value = error instanceof Error ? error.message : '无法读取电容阻抗曲线。';
  } finally {
    pending = undefined;
    importing.value = false;
  }
}
onBeforeUnmount(() => pending?.abort());
</script>
<template>
  <div class="bank">
    <div class="bank-actions"><strong>{{side==='input'?'输入':'输出'}}并联电容 · {{rows.length}} 颗</strong><button type="button" @click="resize(rows.length+1)">增加</button></div>
    <div class="bank-actions"><input v-model="count" type="number" min="1" step="1" :placeholder="String(rows.length)" aria-label="电容数量" /><button type="button" @click="resize(Number(count))">设置数量</button></div>
    <div class="cap-list"><table><thead><tr><th>位号</th><th>C / µF</th><th>ESR / mΩ</th><th>ESL / nH</th><th></th></tr></thead><tbody>
      <tr v-for="(row,i) in rows" :key="i"><td>{{ capacitorRef(side, i, railIndex) }}</td>
        <td v-for="[key,scale] in nominalFields" :key="key"><input type="number" min="0" step="any" :aria-label="`${capacitorRef(side, i, railIndex)} ${key}`" :value="row[key]/scale" @change="editNominal(i,key,scale,$event)" /></td>
        <td><button type="button" :disabled="rows.length===1" @click="remove(Number(i))">删除</button></td>
      </tr>
    </tbody></table></div>
    <details v-if="active" class="cap-data">
      <summary>阻抗曲线与热阻</summary>
      <label class="cap-field">
        <span>电容位号</span>
        <select :value="activeIndex" :disabled="importing" @change="selected = Number(($event.target as HTMLSelectElement).value); importError = ''">
          <option v-for="(_, index) in rows" :key="index" :value="index">{{ capacitorRef(side, index, railIndex) }}</option>
        </select>
      </label>
      <small v-if="sweep" class="cap-source" role="status">
        {{ mode === 'curve' ? '曲线已启用' : '曲线已保存' }} · {{ sweep.source || '项目内曲线' }} · {{ sweep.points.length }} 点 · {{ curveRange }}
      </small>
      <label v-if="!native" class="cap-field">
        <span>{{ sweep ? '替换曲线' : '导入曲线' }}</span>
        <input type="file" accept=".csv,.tsv,.txt,.json" :disabled="importing" @change="loadSweep" />
      </label>
      <small v-if="!native">表头可用 f_Hz、Z_ohm、phase_deg。曲线范围外使用固定 C、ESR、ESL。</small>
      <button v-if="sweep" type="button" :disabled="importing || mode === 'curve'" @click="removeSweep">移除曲线</button>
      <small v-if="sweep && mode === 'curve'">移除前，先在「器件模型精度选择」切换到固定参数。</small>
      <small v-else-if="sweep && !native">在「器件模型精度选择」启用已保存的曲线。</small>
      <small v-if="native">阻抗曲线与热阻由桌面版或本地 Python 网页计算。</small>
      <small v-if="importing" role="status">正在读取阻抗曲线…</small>
      <small v-if="importError" class="cap-error" role="alert">{{ importError }}</small>
      <label v-if="!native || active.thermal_resistance_K_per_W != null" class="cap-field">
        <span>热阻 / K/W</span>
        <input type="number" min="0" step="any" placeholder="可选" :disabled="importing"
          :value="active.thermal_resistance_K_per_W ?? ''"
          @input="($event.target as HTMLInputElement).setCustomValidity('')" @change="editThermal" />
      </label>
    </details>
  </div>
</template>
<style scoped>
.bank{margin:8px 0;padding:8px;border:1px solid #aabccc;border-radius:6px}.bank-actions{display:flex;align-items:center;gap:8px;margin-bottom:6px}.bank-actions strong{flex:1}.bank-actions input{width:65px}.cap-list{max-height:230px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:3px;font-size:13px}td input{width:100%;min-width:52px;box-sizing:border-box;padding:4px}small{display:block;margin-top:6px}button{cursor:pointer;padding:4px 7px}
.cap-data { margin-top: 8px; }
.cap-field { display:grid; grid-template-columns:6em minmax(0,1fr); align-items:center; gap:6px; margin-top:8px; }
.cap-field :is(select,input) { width:100%; min-width:0; box-sizing:border-box; }
.cap-source, .cap-error { overflow-wrap:anywhere; }
.cap-error { color:#a62929; }
</style>
