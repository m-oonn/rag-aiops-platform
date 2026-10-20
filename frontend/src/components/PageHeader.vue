<template>
  <div class="page-header">
    <div class="page-header-text">
      <h2 class="page-title">{{ title }}</h2>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-gap-inline);
  flex-wrap: wrap;
  margin-bottom: var(--app-gap-section);
}
.page-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 600;
  line-height: 1.35;
  color: var(--app-text-primary);
}
.page-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-secondary);
}
.page-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
