<script setup>
defineProps({ title: String, back: String });
</script>
<template>
  <header class="page-header">
    <div class="page-heading">
      <RouterLink v-if="back" :to="back" class="back-link" aria-label="返回"
        ><span aria-hidden="true">←</span></RouterLink
      >
      <h1>{{ title }}</h1>
      <slot name="meta" />
    </div>
    <div class="actions"><slot /></div>
  </header>
</template>
