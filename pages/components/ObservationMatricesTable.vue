<template>
  <VCard>
    <VCardContent>
      <ClientOnly>
        <VSpinner v-if="isLoading" />
      </ClientOnly>
      <VTable>
        <VTableHeader>
          <VTableHeaderRow>
            <VTableHeaderCell>Observation matrix</VTableHeaderCell>
          </VTableHeaderRow>
        </VTableHeader>
        <VTableBody>
          <VTableBodyRow
            v-for="item in list"
            :key="item.id"
          >
            <VTableBodyCell>
              <RouterLink
                :to="{
                  name: item.is_media_matrix
                    ? 'image-matrices-id'
                    : 'interactive-keys-id',
                  params: { id: item.id }
                }"
              >
                {{ item.name }}
              </RouterLink>
            </VTableBodyCell>
          </VTableBodyRow>
        </VTableBody>
      </VTable>
      <VPagination
        class="mt-4"
        v-model="pagination.page"
        :total="pagination.total"
        :per="pagination.per"
        @update:modelValue="
          (page) => {
            loadList(page)
          }
        "
      />
    </VCardContent>
  </VCard>
</template>

<script setup>
import { ref, onBeforeMount } from 'vue'
import { makeAPIRequest } from '@/utils'

const props = defineProps({
  per: {
    type: Number,
    default: 10
  }
})

const list = ref([])
const isLoading = ref(false)
const pagination = ref({ page: 1, total: 0, per: props.per })

async function loadList(page = 1) {
  isLoading.value = true

  makeAPIRequest
    .get('/observation_matrices', {
      params: {
        per: props.per,
        page
      }
    })
    .then(({ data, headers }) => {
      pagination.value = getPagination(headers)
      list.value = data
    })
    .finally(() => {
      isLoading.value = false
    })
}

function getPagination(headers) {
  return {
    page: Number(headers['pagination-page']),
    per: Number(headers['pagination-per-page']),
    total: Number(headers['pagination-total'])
  }
}

onBeforeMount(loadList)
</script>
