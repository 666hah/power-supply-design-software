<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import type { Spec } from './types';
const props=defineProps<{config?:Spec;schema:Spec;phases:number}>();
const emit=defineEmits<{(e:'update',value:Spec):void}>();
const open=ref(false), tab=ref(0), draft=ref<Spec>({}), error=ref(''), saved=ref('');
const copy=(x:any)=>JSON.parse(JSON.stringify(x));
function load(){
  draft.value=copy(props.config||{});
  if(!draft.value.phase_parameters)draft.value.phase_parameters=Array.from({length:props.phases},()=>copy(props.schema.phase_defaults));
  error.value='';saved.value='';
}
watch(open,v=>{if(v)load()});
const groups=computed(()=>props.schema?.groups||[]);
function get(path:string,fallback:any){let obj:any=draft.value;for(const key of path.split('.'))obj=obj?.[key];return obj===undefined?fallback:obj;}
function set(path:string,value:any){const parts=path.split('.');let obj=draft.value;for(const key of parts.slice(0,-1))obj=obj[key]??(obj[key]={});obj[parts[parts.length-1]]=value;saved.value='';}
function numeric(field:Spec,e:Event){const text=(e.target as HTMLInputElement).value;set(field.key,text===''?null:Number(text)/field.factor);}
function apply(){
  error.value='';
  if(draft.value.phase_parameters.length!==props.phases){error.value=`当前 ${props.phases} 相，需要恰好 ${props.phases} 行逐相参数。`;return;}
  for(const group of groups.value)for(const field of group.fields){const value=get(field.key,field.default);if(!field.choices&&(value===null||!Number.isFinite(value)||value<0)){error.value=`请检查${field.label}`;return;}}
  for(const row of draft.value.phase_parameters)for(const field of props.schema.phase_fields){const value=row[field.key]??props.schema.phase_defaults[field.key];if(!Number.isFinite(value)||(field.key!=='sense_offset_A'&&value<=0)){error.value=`请检查逐相${field.label}`;return;}}
  const minOff=get('uvlo_off_V',0), minOn=get('uvlo_on_V',0);
  if(minOff>minOn){error.value='输入关断阈值不可高于启动阈值。';return;}
  if(get('model','cadence_pi')==='current_feedback'&&(get('current_feedback_hz_per_a',0)<=0||get('current_filter_hz',0)<=0)){error.value='总电流反馈增益和滤波带宽须大于零。';return;}
  if(get('acceptance.recovery_s',.002)<=0||get('acceptance.settling_band_pct',2)<=0){error.value='恢复时间和恢复电压带须大于零。';return;}
  if(draft.value.acceptance)draft.value.acceptance.imbalance_pct=get('phase_imbalance_limit_pct',10);
  emit('update',copy(draft.value));saved.value='已应用；保存工程可保留这些设置。';
}
</script>
<template>
  <button class="secondary" @click="open=true">COT 控制、均流、保护与验收</button>
  <div v-if="open" class="cot-backdrop" @click.self="open=false">
    <section class="cot-dialog" role="dialog" aria-modal="true" aria-label="COT 工程配置">
      <header><div><h2>COT 工程配置</h2><p>共用一套控制、逐相和验收参数，随当前工程保存。</p></div><button @click="open=false">关闭</button></header>
      <nav><button v-for="(group,i) in groups" :key="group.name" :class="{selected:tab===i}" @click="tab=i">{{group.name}}</button><button :class="{selected:tab===groups.length}" @click="tab=groups.length">逐相器件与采样</button></nav>
      <div class="cot-content">
        <div v-if="tab<groups.length" class="cot-fields">
          <label v-for="field in groups[tab].fields" :key="field.key"><span>{{field.label}}<small v-if="field.unit"> / {{field.unit}}</small></span>
            <select v-if="field.choices" :value="get(field.key,field.default)" @change="set(field.key,($event.target as HTMLSelectElement).value)"><option v-for="(label,key) in field.choices" :key="key" :value="key">{{label}}</option></select>
            <input v-else type="number" step="any" min="0" :value="get(field.key,field.default)*field.factor" @input="numeric(field,$event)"/>
            <small>{{field.note}}</small>
          </label>
        </div>
        <div v-else>
          <p>当前 {{phases}} 相，已配置 {{draft.phase_parameters.length}} 行。倍率作用于主界面的单相标称值。</p>
          <div class="cot-table"><table><thead><tr><th>相</th><th v-for="field in schema.phase_fields" :key="field.key">{{field.label}}</th><th>操作</th></tr></thead><tbody><tr v-for="(row,i) in draft.phase_parameters" :key="i"><th>PH{{Number(i)+1}}</th><td v-for="field in schema.phase_fields" :key="field.key"><input type="number" step="any" :value="row[field.key]??schema.phase_defaults[field.key]" @input="row[field.key]=Number(($event.target as HTMLInputElement).value)"/></td><td><button @click="draft.phase_parameters.splice(i,1)">删除</button></td></tr></tbody></table></div>
          <button :disabled="draft.phase_parameters.length>=16" @click="draft.phase_parameters.push(copy(schema.phase_defaults))">增加一相参数</button>
        </div>
      </div>
      <footer><span class="cot-error" v-if="error">{{error}}</span><span v-else>{{saved||'修改后点击应用；计算时检查完整物理约束。'}}</span><button class="primary" @click="apply">应用到当前设计</button></footer>
    </section>
  </div>
</template>
<style scoped>
.cot-backdrop{position:fixed;inset:0;z-index:1200;background:#0b1d3590;display:grid;place-items:center;padding:24px}.cot-dialog{width:min(1180px,96vw);max-height:90vh;background:#fff;border-radius:15px;display:flex;flex-direction:column;box-shadow:0 20px 80px #07193260;color:#172b46}.cot-dialog header,.cot-dialog footer{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 24px}.cot-dialog h2{margin:0 0 7px;font-size:22px}.cot-dialog p{color:#62748a;margin:5px 0 12px}.cot-dialog nav{flex-shrink:0;display:flex;flex-wrap:wrap;gap:7px;padding:0 24px 12px;border-bottom:1px solid #dfe7f2}.cot-dialog button{padding:9px 14px;border:1px solid #cbd8e9;border-radius:6px;background:#f6f9fd;cursor:pointer}.cot-dialog .selected,.cot-dialog .primary{background:#1769d2;color:white}.cot-content{overflow:auto;padding:20px 24px;min-height:0;flex:1 1 auto}.cot-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 26px}.cot-fields label{display:flex;flex-direction:column;gap:8px}.cot-fields small{font-size:12px;color:#62748a;line-height:1.6}.cot-dialog input,.cot-dialog select{border:1px solid #bbcde2;border-radius:5px;padding:9px 10px;min-width:0;color:#172b46;background:white}.cot-table{overflow-x:auto;margin-bottom:16px}.cot-table table{border-collapse:collapse}.cot-table th,.cot-table td{padding:7px;border-bottom:1px solid #e0e7ef;white-space:nowrap}.cot-table input{width:100px}.cot-error{color:#a62920}.cot-dialog footer{border-top:1px solid #e1e8f2}@media(max-width:800px){.cot-fields{grid-template-columns:1fr}.cot-backdrop{padding:8px}.cot-dialog{max-height:96vh}}
</style>
