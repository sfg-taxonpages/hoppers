<template>
  <VCard class="container mx-auto">
    <VSpinner
      v-if="isLoading"
      full-screen
    />
    <VCardHeader>{{ observationMatrix.name }}</VCardHeader>
    <VCardContent>
      <div class="image-matrix overflow-auto">
        <VTable>
          <VTableHeader>
            <VTableHeaderRow class="bg-base-foreground">
              <VTableHeaderCell class="border-b" />
              <VTableHeaderCell
                v-for="{ id, label } in descriptors"
                :key="id"
                class="border-l border-b"
              >
                {{ label }}
              </VTableHeaderCell>
            </VTableHeaderRow>
          </VTableHeader>
          <VTableBody>
            <VTableBodyRow v-for="item in list">
              <VTableBodyCell
                class="border-b text-base-content h-20"
                v-html="item.label"
              >
              </VTableBodyCell>
              <VTableBodyCell
                v-for="arr in item.depictions"
                class="border-l border-b"
              >
                <ListImage :images="arr.map(makeImageObject)" />
              </VTableBodyCell>
            </VTableBodyRow>
          </VTableBody>
        </VTable>
      </div>
    </VCardContent>
  </VCard>
</template>

<script setup>
import { ref } from 'vue'
import { makeAPIRequest } from '@/utils'
import { useRoute } from 'vue-router'
import { makeImageObject } from '../utils/makeImageObject.js'
import ListImage from '../components/ListImages.vue'

const list = ref([])
const isLoading = ref(true)
const descriptors = ref([])
const observationMatrix = ref({})
const route = useRoute()

makeAPIRequest
  .get(`/observation_matrices/${route.params.id}/image_matrix`)
  .then(({ data }) => {
    observationMatrix.value = data.observation_matrix
    descriptors.value = data.list_of_descriptors.map((item) => ({
      label: item.name,
      id: item.id
    }))

    list.value = data.depiction_matrix.map((item) => {
      const obj = {
        label: item.object.label,
        depictions: []
      }

      for (let i = 0; i < descriptors.value.length; i++) {
        const depictions = item.depictions[i].map((d) => ({
          ...d,
          ...data.image_hash[d.image_id]
        }))

        obj.depictions.push(depictions)
      }

      return obj
    })
  })
  .catch(() => {})
  .finally(() => {
    isLoading.value = false
  })
</script>

<style scoped>
.image-matrix {
  max-height: calc(100vh - 12rem);
}
</style>
