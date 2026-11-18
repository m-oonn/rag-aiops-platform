<script setup>
defineProps({
  loading: Boolean,
  error: String,
  empty: Boolean,
  text: { type: String, default: "暂无数据" },
});
defineEmits(["retry"]);
</script>
<template>
  <div v-if="error" class="feedback error-feedback" role="alert">
    <span>{{ error }}</span
    ><button class="text-button" @click="$emit('retry')">重试</button>
  </div>
  <div v-else-if="loading" class="feedback" role="status">
    <span class="spinner" />正在加载
  </div>
  <div v-else-if="empty" class="empty-state">
    <slot
      ><span>{{ text }}</span></slot
    >
  </div>
</template>
