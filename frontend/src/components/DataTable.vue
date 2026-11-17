<script setup lang="ts">
import EmptyState from './EmptyState.vue'
import type { TableColumn } from './ui-types'

const props = withDefaults(defineProps<{
  rows: Record<string, unknown>[]
  columns: TableColumn[]
  loading?: boolean
  emptyText?: string
  rowKey?: string
  mobileTitleKey?: string
  actionWidth?: number
}>(), { loading: false, emptyText: '暂无数据', rowKey: 'id', mobileTitleKey: '', actionWidth: 150 })

const emit = defineEmits<{ 'row-click': [row: Record<string, unknown>] }>()

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function keyOf(row: Record<string, unknown>, index: number): string | number {
  const value = row[props.rowKey]
  return typeof value === 'string' || typeof value === 'number' ? value : index
}

function mobileTitle(row: Record<string, unknown>): string {
  const key = props.mobileTitleKey || props.columns.find((col) => col.primary)?.key
  return key ? display(row[key]) : ''
}
</script>

<template>
  <div v-loading="loading" class="data-table">
    <div class="desktop">
      <el-table
        :data="rows"
        :row-key="rowKey"
        :empty-text="emptyText"
        @row-click="emit('row-click', $event)"
      >
        <el-table-column
          v-for="col in columns"
          :key="col.key"
          :prop="col.key"
          :label="col.label"
          :width="col.width"
          :min-width="col.minWidth"
          :align="col.align"
        >
          <template #default="{ row }">
            <slot :name="`cell-${col.key}`" :row="row">{{ display(row[col.key]) }}</slot>
          </template>
        </el-table-column>
        <el-table-column v-if="$slots.actions" label="操作" :width="actionWidth" fixed="right">
          <template #default="{ row }">
            <div class="actions-cell">
              <slot name="actions" :row="row" />
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="mobile">
      <EmptyState v-if="!rows.length && !loading" :title="emptyText" compact />
      <article v-for="(row, index) in rows" :key="keyOf(row, index)" class="card">
        <header v-if="mobileTitle(row)" class="card-head">{{ mobileTitle(row) }}</header>
        <dl class="fields">
          <div v-for="col in columns" v-show="!col.hideOnMobile" :key="col.key" class="field">
            <dt>{{ col.label }}</dt>
            <dd>
              <slot :name="`cell-${col.key}`" :row="row">{{ display(row[col.key]) }}</slot>
            </dd>
          </div>
        </dl>
        <footer v-if="$slots.actions" class="card-actions">
          <slot name="actions" :row="row" />
        </footer>
      </article>
    </div>
  </div>
</template>

<style scoped>
.data-table {
  min-inline-size: 0;
}

.mobile {
  display: none;
}

.desktop {
  overflow-x: auto;
}

.card {
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  background: var(--hmi-surface);
  padding: 0.7rem 0.8rem;
  margin-block-end: 0.5rem;
}

.card-head {
  font-weight: 600;
  font-size: var(--hmi-fs-4);
  padding-block-end: 0.45rem;
  margin-block-end: 0.45rem;
  border-block-end: 1px solid var(--hmi-line-soft);
}

.fields {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0;
}

.field {
  display: flex;
  align-items: baseline;
  gap: 0.7rem;
  font-size: var(--hmi-fs-3);
}

.field dt {
  flex: 0 0 92px;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
}

.field dd {
  margin: 0;
  min-inline-size: 0;
  color: var(--hmi-text-2);
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-block-start: 0.6rem;
  padding-block-start: 0.5rem;
  border-block-start: 1px solid var(--hmi-line-soft);
}

.actions-cell {
  display: flex;
  gap: 0.2rem;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.actions-cell :deep(.el-button + .el-button),
.card-actions :deep(.el-button + .el-button) {
  margin-inline-start: 0;
}

@media (max-width: 768px) {
  .desktop {
    display: none;
  }

  .mobile {
    display: block;
  }
}
</style>
