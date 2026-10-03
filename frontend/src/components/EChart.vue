<template>
  <div ref="el" :style="{ height: height + 'px', width: '100%' }"></div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  option: echarts.EChartsOption
  height?: number
}>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function render() {
  if (!el.value || !el.value.clientWidth || !el.value.clientHeight) return
  if (!chart) chart = echarts.init(el.value, { color: ['#303030', '#737373', '#a3a3a3', '#d4d4d4'], textStyle: { color: '#737373', fontFamily: 'system-ui, sans-serif' }, categoryAxis: { axisLine: { lineStyle: { color: '#e5e5e5' } }, axisLabel: { color: '#737373' } }, valueAxis: { splitLine: { lineStyle: { color: '#ededed' } }, axisLabel: { color: '#737373' } } })
  chart.setOption(props.option, true)
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  if (el.value) {
    observer = new ResizeObserver(() => {
      if (el.value && el.value.clientWidth > 0 && el.value.clientHeight > 0) {
        render()
        resize()
      }
    })
    observer.observe(el.value)
  }
  window.addEventListener('resize', resize)
})

watch(
  () => props.option,
  () => nextTick(render),
  { deep: true },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>
