<template>
  <div class="container mx-auto py-4">
    <h1 class="text-4xl font-bold">Keys</h1>
    <div class="flex flex-col gap-4 mt-4">
      <ObservationMatricesTable />
      <KeysTable />
    </div>
  </div>
</template>

<script setup>
import ObservationMatricesTable from './components/ObservationMatricesTable.vue'
import KeysTable from './components/KeysTable.vue'
</script>
