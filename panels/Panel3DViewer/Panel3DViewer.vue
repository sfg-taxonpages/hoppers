<template>
  <VCard v-if="model">
    <VCardHeader> 3D Viewer </VCardHeader>
    <VCardContent>
      <div
        ref="container"
        class="relative w-full h-96"
      >
        <div
          v-if="loading"
          class="absolute inset-0 flex items-center justify-center text-sm text-gray-500"
        >
          Loading 3D model…
        </div>
        <div
          v-else-if="error"
          class="absolute inset-0 flex items-center justify-center text-sm text-red-500"
        >
          {{ error }}
        </div>
      </div>

      <p
        v-if="model.description"
        class="mt-3 text-sm text-gray-600 dark:text-gray-300"
      >
        {{ model.description }}
      </p>
    </VCardContent>
  </VCard>
</template>

<script setup>
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const { base_url } = __APP_ENV__

const props = defineProps({
  otuId: {
    type: Number,
    required: true
  },

  models: {
    type: Object,
    default: () => ({})
  },

  background: {
    type: Object,
    default: () => ({})
  }
})

const model = computed(() => {
  const entry = props.models?.[props.otuId]

  if (!entry) {
    return null
  }

  return typeof entry === 'string' ? { url: entry } : entry
})

const container = ref(null)
const loading = ref(false)
const error = ref(null)

const DEFAULT_BACKGROUND = {
  light: '#f5f5f5',
  dark: '#111827'
}

let renderer,
  scene,
  camera,
  controls,
  object,
  frameId,
  resizeObserver,
  themeObserver

function isDark() {
  return document.documentElement.classList.contains('dark')
}

function applyBackground() {
  if (!scene) {
    return
  }

  const theme = isDark() ? 'dark' : 'light'
  const color = props.background?.[theme] ?? DEFAULT_BACKGROUND[theme]

  scene.background = new THREE.Color(color)
}

function isExternal(url) {
  return /^(https?:)?\/\//i.test(url) || url.startsWith('data:')
}

function resolveUrl(url) {
  if (isExternal(url)) {
    return url
  }

  const base = (base_url || '/').replace(/\/+$/, '')

  return `${base}/${url.replace(/^\/+/, '')}`
}

function detectFormat(url, explicitFormat) {
  if (explicitFormat) {
    return explicitFormat.toLowerCase()
  }

  const clean = url.split(/[?#]/)[0]
  const ext = clean.split('.').pop()?.toLowerCase()

  return ext
}

function render() {
  frameId = requestAnimationFrame(render)
  controls?.update()
  renderer?.render(scene, camera)
}

function fitCameraToObject(object) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const radius = Math.max(size.x, size.y, size.z) * 0.5 || 1
  const distance = radius / Math.tan((camera.fov * Math.PI) / 360)

  camera.position.set(0, 0, distance * 1.6)
  camera.near = Math.max(distance / 100, 0.01)
  camera.far = distance * 100
  camera.updateProjectionMatrix()

  controls.target.set(0, 0, 0)
  controls.update()
}

function centerObject(object) {
  const box = new THREE.Box3().setFromObject(object)
  const center = box.getCenter(new THREE.Vector3())
  object.position.sub(center)
}

function initScene() {
  const el = container.value
  const width = el.clientWidth || 1
  const height = el.clientHeight || 1

  scene = new THREE.Scene()
  applyBackground()

  camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000)
  camera.position.set(0, 0, 100)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.setSize(width, height)
  el.appendChild(renderer.domElement)

  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.2))

  const keyLight = new THREE.DirectionalLight(0xffffff, 1.2)
  keyLight.position.set(1, 1, 1)
  scene.add(keyLight)

  const fillLight = new THREE.DirectionalLight(0xffffff, 0.6)
  fillLight.position.set(-1, 0.5, -1)
  scene.add(fillLight)

  const backLight = new THREE.DirectionalLight(0xffffff, 0.4)
  backLight.position.set(0, -1, -1)
  scene.add(backLight)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true

  resizeObserver = new ResizeObserver(() => {
    const w = el.clientWidth || 1
    const h = el.clientHeight || 1
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h)
  })
  resizeObserver.observe(el)

  themeObserver = new MutationObserver(applyBackground)
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class']
  })

  render()
}

function normalizeMaterials(child) {
  const materials = Array.isArray(child.material)
    ? child.material
    : [child.material]

  materials.forEach((m) => {
    m.side = THREE.DoubleSide
  })
}

function finalizeObject(loadedObject) {
  loadedObject.traverse((child) => {
    if (child.isMesh) {
      child.geometry.computeVertexNormals()
      normalizeMaterials(child)
    }
  })

  centerObject(loadedObject)
  scene.add(loadedObject)
  fitCameraToObject(loadedObject)

  object = loadedObject
  loading.value = false
}

function handleLoadError(err) {
  console.error('[Panel3DViewer] Failed to load model:', err)
  error.value = 'Failed to load 3D model.'
  loading.value = false
}

function loadGLTF(resolvedUrl) {
  const loader = new GLTFLoader()

  loader.load(
    resolvedUrl,
    (gltf) => finalizeObject(gltf.scene),
    undefined,
    handleLoadError
  )
}

function loadSTL(resolvedUrl) {
  const loader = new STLLoader()

  loader.load(
    resolvedUrl,
    (geometry) => {
      const material = new THREE.MeshStandardMaterial({
        color: 0x999999,
        metalness: 0.1,
        roughness: 0.75
      })

      finalizeObject(new THREE.Mesh(geometry, material))
    },
    undefined,
    handleLoadError
  )
}

function loadModel(url, format) {
  loading.value = true

  const resolvedUrl = resolveUrl(url)
  const type = detectFormat(url, format)

  if (type === 'glb' || type === 'gltf') {
    loadGLTF(resolvedUrl)
  } else if (type === 'stl') {
    loadSTL(resolvedUrl)
  } else {
    handleLoadError(new Error(`Unsupported 3D model format: "${type}"`))
  }
}

onMounted(() => {
  if (!model.value?.url) {
    return
  }

  initScene()
  loadModel(model.value.url, model.value.format)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(frameId)
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  controls?.dispose()

  if (object) {
    object.traverse((child) => {
      if (child.isMesh) {
        child.geometry?.dispose()

        if (Array.isArray(child.material)) {
          child.material.forEach((m) => m.dispose())
        } else {
          child.material?.dispose()
        }
      }
    })
  }

  if (renderer) {
    renderer.dispose()
    renderer.domElement.remove()
  }
})
</script>
