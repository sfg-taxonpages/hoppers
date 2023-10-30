<template>
  <VCard>
    <VCardHeader> Gender, form, and etymology </VCardHeader>
    <VCardContent class="text-sm">
      <div v-html="taxon.etymology" />
      <hr class="my-4" />
      <span
        v-for="item in classifications"
        v-html="item.object_tag"
        class="block"
      />
      <div
        v-if="inSpeciesGroup && adjectiveOrParticiple"
        class="flex-col gap-2 mt-4"
      >
        <div
          v-for="(label, key) in NAMES_PROP"
          :key="key"
        >
          <template v-if="taxon[key]">
            <p class="text-sm">
              {{ label }} name:
              <span class="font-bold">{{ taxon[key] }}</span>
            </p>
          </template>
        </div>
      </div>
    </VCardContent>
  </VCard>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { makeAPIRequest } from '@/utils'

const SPECIES_GROUP = 'SpeciesGroup'
const SPECIES_AND_INFRASPECIES = 'SpeciesAndInfraspecies'
const NAMES_PROP = {
  masculine_name: 'Masculine',
  femenine_name: 'Femenine',
  neuter: 'Neuter'
}

const props = defineProps({
  taxon: {
    type: Object,
    required: true
  }
})

const classifications = ref([])

const adjectiveOrParticiple = computed(() =>
  classifications.value.some(
    (item) =>
      item.type.includes('::PartOfSpeech::Adjective') ||
      item.type.includes('::PartOfSpeech::Participle')
  )
)

const inSpeciesGroup = computed(() => {
  const rank = props.taxon.rank_string

  return rank.includes(SPECIES_GROUP) || rank.includes(SPECIES_AND_INFRASPECIES)
})

function loadClassifications() {
  const params = {
    taxon_name_id: [props.taxon.id]
  }
  makeAPIRequest
    .get('/taxon_name_classifications', { params })
    .then(({ data }) => {
      classifications.value = data
    })
}

watch(() => props.taxon.id, loadClassifications, { immediate: true })
</script>
