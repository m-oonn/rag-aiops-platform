<template>
  <div class="empty-state">
    <el-icon :size="size" class="empty-icon"><Search /></el-icon>
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-extra">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { Search } from '@element-plus/icons-vue'

defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  size: { type: Number, default: 42 },
})
</script>

<style scoped>
.empty-state {
  padding: 48px 0 32px;
  text-align: center;
}
.empty-icon {
  color: var(--el-text-color-placeholder);
}
.empty-title {
  margin: 12px 0 4px;
  color: var(--app-text-secondary);
  font-size: 14px;
}
.empty-desc {
  margin: 0 0 16px;
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.empty-extra {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}
</style>
