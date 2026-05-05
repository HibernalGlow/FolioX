<script lang="ts">
  import { ocrRunning, ocrProgress } from '$lib/stores';
</script>

{#if $ocrRunning}
  <div class="h-[3px] flex-shrink-0 bg-white/10">
    <div class="h-full rounded-r-sm bg-accent transition-all duration-300"
      style="width: {$ocrProgress.total > 0 ? Math.round(($ocrProgress.done / $ocrProgress.total) * 100) : 0}%"></div>
  </div>
{/if}
