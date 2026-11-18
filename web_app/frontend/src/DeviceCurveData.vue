<script setup lang="ts">
import type { CurveTarget } from './types';

defineProps<{ target: CurveTarget }>();
defineEmits<{ preview: [target: CurveTarget]; importCurve: [target: CurveTarget]; remove: [target: CurveTarget] }>();
</script>

<template>
  <div class="curve-row">
    <div class="curve-title"><strong>{{ target.ref }}</strong><span>{{ target.role }}</span></div>
    <p>{{ target.axes }}</p>
    <div class="curve-actions">
      <button type="button" class="small-button" @click="$emit('importCurve', target)">{{ target.loaded ? '替换曲线' : '导入曲线' }}</button>
      <button v-if="target.loaded" type="button" class="small-button" @click="$emit('preview', target)">预览</button>
      <button v-if="target.loaded" type="button" class="small-button"
        :disabled="target.source === 'curve'" @click="$emit('remove', target)">解除绑定</button>
    </div>
    <small v-if="target.filename" class="curve-filename" :title="target.filename">{{ target.filename }}</small>
    <small v-if="target.loaded && target.source === 'curve'" class="curve-filename">
      解绑前，先在「器件模型精度选择」为此项选择固定参数。
    </small>
  </div>
</template>
