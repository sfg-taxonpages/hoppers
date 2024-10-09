<template>
  <div class="container mx-auto py-4">
    <h1 class="text-4xl font-bold">Recent</h1>
    <div class="flex flex-col gap-4 mt-4">
      <VCard>
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
          <VPagination
            v-model="taxonPagination.page"
            :total="taxonPagination.total"
            :per="taxonPagination.per"
            @update:modelValue="
              (page) => {
                loadTaxonNames(page)
              }
            "
          />
        </VCardContent>
      </VCard>

      <VCard>
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
          <VPagination
            v-model="sourcePagination.page"
            :total="sourcePagination.total"
            :per="sourcePagination.per"
            @update:modelValue="
              (page) => {
                loadSources(page)
              }
            "
          />
        </VCardContent>
      </VCard>
    </div>
  </div>
</template>

<script setup>
import { ref, onBeforeMount } from 'vue'
import { makeAPIRequest } from '@/utils'

const PER = 10

const taxonNames = ref([])
const sources = ref([])
const sourcePagination = ref({ page: 0, total: 0, per: 0 })
const taxonPagination = ref({ page: 0, total: 0, per: 0 })

async function loadTaxonNames(page = 1) {
  try {
    const { data, headers } = await makeAPIRequest.get('/taxon_names', {
      params: {
        validity: true,
        recent: true,
        recent_target: 'created_at',
        per: PER,
        page
      }
    })

    taxonPagination.value = getPagination(headers)
    taxonNames.value = data
  } catch (e) {}
}

async function loadSources(page = 1) {
  try {
    const { data, headers } = await makeAPIRequest.get('/sources', {
      params: {
        in_project: true,
        recent: true,
        recent_target: 'created_at',
        per: PER,
        page
      }
    })

    sourcePagination.value = getPagination(headers)
    sources.value = data
  } catch (e) {}
}

function getPagination(headers) {
  return {
    page: Number(headers['pagination-page']),
    per: Number(headers['pagination-per-page']),
    total: Number(headers['pagination-total'])
  }
}

onBeforeMount(() => {
  loadTaxonNames()
  loadSources()
})
</script>
