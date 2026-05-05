<script lang="ts">
  import { toasts } from '$lib/stores';
</script>

<div class="fixed bottom-5 left-1/2 z-[1000] flex -translate-x-1/2 flex-col items-center gap-2 pointer-events-none">
  {#each $toasts as toast (toast.id)}
    <div class="pointer-events-auto whitespace-nowrap rounded-xl px-5 py-2 text-[13px] font-medium text-white toast-enter
      {toast.type === 'error' ? 'bg-red-600' : toast.type === 'warn' ? 'bg-amber-600' : 'bg-emerald-600'}">
      {toast.message}
    </div>
  {/each}
</div>
