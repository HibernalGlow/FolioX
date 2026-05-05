<script lang="ts">
  let { panelWidth = $bindable(480) }: { panelWidth: number } = $props();

  let dragging = $state(false);

  function handleMouseDown(e: MouseEvent) {
    e.preventDefault();
    dragging = true;
    const startX = e.clientX;
    const startWidth = panelWidth;

    function onMove(e: MouseEvent) {
      const delta = startX - e.clientX;
      panelWidth = Math.min(Math.max(startWidth + delta, 280), window.innerWidth * 0.6);
    }

    function onUp() {
      dragging = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="relative z-[5] mx-[-2px] ml-[-3px] w-[5px] flex-shrink-0 cursor-col-resize transition-colors
  {dragging ? 'bg-accent' : 'hover:bg-accent'}"
  onmousedown={handleMouseDown}
  role="separator"
  aria-orientation="vertical">
</div>
