<script setup>
defineProps({ modelValue: Boolean, title: String, wide: Boolean });
defineEmits(["update:modelValue"]);
</script>
<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="wide ? '960px' : '640px'"
    :close-on-click-modal="false"
    destroy-on-close
    align-center
    @update:model-value="$emit('update:modelValue', $event)"
    ><slot /><template v-if="$slots.footer" #footer
      ><slot name="footer" /></template
  ></el-dialog>
</template>
