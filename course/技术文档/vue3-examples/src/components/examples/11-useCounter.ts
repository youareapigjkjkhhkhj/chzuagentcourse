import { ref } from 'vue'

export function useCounter(init = 0) {
  const count = ref(init)
  const inc = () => count.value++
  const dec = () => count.value--
  const reset = () => (count.value = init)
  return { count, inc, dec, reset }
}
