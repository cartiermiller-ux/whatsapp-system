<template><div class="page" :class="`template-${kind}`"><slot /></div></template>
<script setup lang="ts">
defineProps<{ kind: 'dashboard' | 'list' | 'task-detail' | 'settings' }>()
</script>
<style>
.template-list > .el-card, .template-list > .el-tabs .el-card, .template-settings > .el-card, .template-settings .settings-tabs .el-card { border: 0; border-radius: 0; }
.template-list > .el-card > .el-card__body, .template-list > .el-tabs .el-card__body, .template-settings .settings-tabs .el-card__body { padding: 0; }
.template-list > .el-card > .el-card__header { padding: 0 0 12px; border: 0; }
.template-list > .el-card + .el-card { padding-top: 24px; border-top: 1px solid var(--wa-border); }
.template-settings .settings-tabs > .el-tabs__content { padding-left: 24px; min-width: 0; }
.template-settings .settings-tabs .el-tabs__item { justify-content: flex-start; }
.template-dashboard .stat-card, .template-list .stat-card { border: 0; padding: 12px 0; border-radius: 0; }
@media(max-width: 600px) { .template-settings .settings-tabs > .el-tabs__header { float: none; margin: 0 0 16px; }.template-settings .settings-tabs > .el-tabs__content { padding-left: 0; } }
</style>
