<template>
  <div class="container mx-auto py-4">
    <h1 class="text-4xl font-bold">Recent</h1>
    <div class="flex flex-col gap-4 mt-4">
      <RecentTable
        :attributes="{
          cached_html: 'Taxon name',
          cached_author_year: 'Author'
        }"
        route="/taxon_names"
        :parameters="{
          validity: true,
          recent: true,
          recent_target: 'created_at'
        }"
      />

      <RecentTable
        :attributes="{
          cached: 'Source'
        }"
        route="/sources"
        :parameters="{
          in_project: true,
          recent: true,
          recent_target: 'created_at'
        }"
      />
    </div>
  </div>
</template>

<script setup>
import RecentTable from './components/RecentTable.vue'
</script>
