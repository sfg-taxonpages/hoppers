---
title: 'TaxonPages: World Auchenorrhyncha Database'
lead: 'The database has a comprehansive checklist of the hemipteran suborder Auchenorrhyncha. Besides nomenclature, the database contains descriptions, distributions, biological associations (host plants, parasitoids, etc.), literature references, illustrations, and tools for identification of selected groups. It was designed and maintained with support from several grants from National Science Foundation (USA).'
project: 'TaxonPages: World Auchenorrhyncha Database'
---

<div>
  <div class="flex justify-center align-middle">
    <table>
      <tbody>
        <tr class="border-b-0">
          <td v-for="item in otus" :key="item.id">
            <RouterLink
            :to="{
                name: 'otus-id',
                params: { id: item.id }
              }"
            >
              <img v-bind="item.image">
            </RouterLink>
          </td>
        </tr>
        <tr>
          <td colspan="6" class="text-center">
            Valid Species: <ValidSpeciesCount/>; Fossil Species: <FossilSpeciesCount/>; <ProjectStats :data="['Taxon names', 'Collection objects', 'Project sources', 'Documents', 'Citations', 'Images']" class="capitalize"/>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="flex justify-center align-middle">
    <autocomplete-otu style="width:25rem;"/>
  </div>
</div>

<script setup>
const otus = [
  {
    id: 28073,
    image: {
    src: '/images/Flexamia_grammica_Cicadellidae.png',
    alt: 'Cicadellidae: Flexamia grammica (Ball, 1900). Photo by C.H. Dietrich',
    title: 'Cicadellidae: Flexamia grammica (Ball, 1900). Photo by C.H. Dietrich'
    }
  },
  {
    id: 20043,
    image: {
      src: '/images/Tinobregmus_viridescens_IL.png',
      alt: 'Cicadellidae: Tinobregmus vittatus Van Duzee, 1894. Photo by C.H. Dietrich',
      title: 'Cicadellidae: Tinobregmus vittatus Van Duzee, 1894. Photo by C.H. Dietrich'
    }
  },
  {
    id: 55079,
    image: {
      src: '/images/Bocydium_PNSO.png',
      title: 'Membracidae: Bocydium sp. Photo by C.H. Dietrich',
      alt: 'Membracidae: Bocydium sp. Photo by C.H. Dietrich'
    }
  },
  {
    id:2367,
    image: {
      src: '/images/Cercopidae_Brazil.png',
      alt: 'Cecropidae from Brazil. Photo by C.H. Dietrich',
      title: 'Cecropidae from Brazil. Photo by C.H. Dietrich'
    }
  },
  {
    id:7666,
    image: {
      src: '/images/Cicadidae_Cicadetta_calliope.png',
      title: 'Cicadidae: Cicadetta calliope (Walker, 1830). Photo by C.H. Dietrich',
      alt: 'Cicadidae: Cicadetta calliope (Walker, 1830). Photo by C.H. Dietrich'
    }
  },
  {
    id:71398,
    image: {
      src: '/images/Fulgorid_Lycorma_delicatula_China.png',
      title: 'Fulgoridae: Lycorma delicatula (White, 1845). Photo by C.H. Dietrich',
      alt: 'Fulgoridae: Lycorma delicatula (White, 1845). Photo by C.H. Dietrich'
    }
  }
]
</script>
