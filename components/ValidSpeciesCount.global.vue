<template>
  <span>{{ count }}</span>
</template>

<script setup>
import { makeAPIRequest } from '@/utils'
import { onMounted, ref } from 'vue'

const count = ref('??')

onMounted(() => {
  makeAPIRequest
    .get('/taxon_names.json', {
      params: {
        validity: true,
        rank: ['NomenclaturalRank::Iczn::SpeciesGroup::Species'],
        descendants: true
      }
    })
    .then((response) => {
      count.value = response.headers['pagination-total']
    })
})
</script>
