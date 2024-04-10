<template>
  <div class="container mx-auto py-8 flex flex-col gap-4">
    <VCard>
      <VCardHeader><h1 class="text-md">Taxon names</h1></VCardHeader>
      <VCardContent>
        <VTable>
          <VTableHeader>
            <VTableHeaderRow>
              <VTableHeaderCell>Taxon name</VTableHeaderCell>
              <VTableHeaderCell>Author</VTableHeaderCell>
            </VTableHeaderRow>
          </VTableHeader>
          <VTableBody>
            <VTableBodyRow
              v-for="item in taxonNames"
              :key="item.id"
            >
              <VTableBodyCell v-html="item.cached_html" />
              <VTableBodyCell v-html="item.cached_author_year" />
            </VTableBodyRow>
          </VTableBody>
        </VTable>
      </VCardContent>
    </VCard>

    <VCard>
      <VCardHeader><h1 class="text-md">Sources</h1></VCardHeader>
      <VCardContent>
        <VTable>
          <VTableHeader>
            <VTableHeaderRow>
              <VTableHeaderCell>Source</VTableHeaderCell>
            </VTableHeaderRow>
          </VTableHeader>
          <VTableBody>
            <VTableBodyRow
              v-for="item in sources"
              :key="item.id"
            >
              <VTableBodyCell v-html="item.cached" />
            </VTableBodyRow>
          </VTableBody>
        </VTable>
      </VCardContent>
    </VCard>
  </div>
</template>

<script setup>
import { ref, onBeforeMount } from 'vue'
import { makeAPIRequest } from '@/utils'

const taxonNames = ref([])
const sources = ref([])

async function loadTaxonNames() {
  try {
    const { data } = await makeAPIRequest.get('/taxon_names', {
      params: {
        validity: true,
        recent: true,
        per: 10
      }
    })

    taxonNames.value = data
  } catch (e) {}
}

async function loadSources() {
  try {
    const { data } = await makeAPIRequest.get('/sources', {
      params: {
        recent: true,
        per: 10
      }
    })

    sources.value = data
  } catch (e) {}
}

onBeforeMount(() => {
  loadTaxonNames()
  loadSources()
})
</script>
