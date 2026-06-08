<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from "vue";

let selectId = 0;

const props = defineProps({
  modelValue: {
    type: [String, Number, Boolean],
    default: "",
  },
  options: {
    type: Array,
    required: true,
  },
  placeholder: {
    type: String,
    default: "",
  },
  ariaLabel: {
    type: String,
    default: "",
  },
  compact: {
    type: Boolean,
    default: false,
  },
  align: {
    type: String,
    default: "start",
  },
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:modelValue"]);

const rootRef = ref(null);
const triggerRef = ref(null);
const menuRef = ref(null);
const optionRefs = ref([]);
const isOpen = ref(false);
const highlightedIndex = ref(-1);
const menuStyle = ref({});
const listboxId = `app-select-${selectId += 1}`;

const selectedIndex = computed(() => props.options.findIndex((option) => option.value === props.modelValue));
const selectedOption = computed(() => props.options[selectedIndex.value] || null);
const selectedLabel = computed(() => selectedOption.value?.label || props.placeholder);

watch(
  () => props.modelValue,
  () => {
    highlightedIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : 0;
  },
  { immediate: true }
);

watch(isOpen, async (open) => {
  if (!open) {
    optionRefs.value = [];
    removeOpenListeners();
    return;
  }

  updateMenuPosition();
  addOpenListeners();
  highlightedIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : 0;
  await nextTick();
  updateMenuPosition();
  focusOption(highlightedIndex.value);
});

function setOptionRef(element, index) {
  if (!element) {
    return;
  }
  optionRefs.value[index] = element;
}

function focusOption(index) {
  optionRefs.value[index]?.focus();
}

function closeMenu({ restoreFocus = false } = {}) {
  isOpen.value = false;
  if (restoreFocus) {
    nextTick(() => {
      triggerRef.value?.focus();
    });
  }
}

function openMenu() {
  if (props.disabled) {
    return;
  }
  isOpen.value = true;
}

function toggleMenu() {
  if (isOpen.value) {
    closeMenu();
    return;
  }
  openMenu();
}

function selectOption(option) {
  emit("update:modelValue", option.value);
  closeMenu({ restoreFocus: true });
}

function moveHighlight(step) {
  const total = props.options.length;
  if (!total) {
    return;
  }
  const baseIndex = highlightedIndex.value >= 0 ? highlightedIndex.value : selectedIndex.value >= 0 ? selectedIndex.value : 0;
  const nextIndex = (baseIndex + step + total) % total;
  highlightedIndex.value = nextIndex;
  focusOption(nextIndex);
}

function updateMenuPosition() {
  const trigger = triggerRef.value;
  if (!trigger) {
    return;
  }

  const rect = trigger.getBoundingClientRect();
  const maxWidth = Math.min(Math.max(rect.width, 160), window.innerWidth - 24);
  let left = props.align === "end" ? rect.right - maxWidth : rect.left;
  left = Math.max(12, Math.min(left, window.innerWidth - maxWidth - 12));

  menuStyle.value = {
    top: `${rect.bottom + 6}px`,
    left: `${left}px`,
    width: `${maxWidth}px`,
  };
}

function onTriggerKeydown(event) {
  if (props.disabled) {
    return;
  }

  if (event.key === "ArrowDown") {
    event.preventDefault();
    if (!isOpen.value) {
      openMenu();
      return;
    }
    moveHighlight(1);
  }

  if (event.key === "ArrowUp") {
    event.preventDefault();
    if (!isOpen.value) {
      openMenu();
      return;
    }
    moveHighlight(-1);
  }

  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    toggleMenu();
  }

  if (event.key === "Escape") {
    closeMenu();
  }
}

function onOptionKeydown(event, option, index) {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveHighlight(1);
    return;
  }

  if (event.key === "ArrowUp") {
    event.preventDefault();
    moveHighlight(-1);
    return;
  }

  if (event.key === "Home") {
    event.preventDefault();
    highlightedIndex.value = 0;
    focusOption(0);
    return;
  }

  if (event.key === "End") {
    event.preventDefault();
    const lastIndex = props.options.length - 1;
    highlightedIndex.value = lastIndex;
    focusOption(lastIndex);
    return;
  }

  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    selectOption(option);
    return;
  }

  if (event.key === "Escape") {
    event.preventDefault();
    closeMenu({ restoreFocus: true });
    return;
  }

  highlightedIndex.value = index;
}

function onWindowPointerDown(event) {
  if (
    !isOpen.value
    || rootRef.value?.contains(event.target)
    || menuRef.value?.contains(event.target)
  ) {
    return;
  }
  closeMenu();
}

function onWindowKeydown(event) {
  if (event.key === "Escape" && isOpen.value) {
    closeMenu({ restoreFocus: true });
  }
}

function addOpenListeners() {
  window.addEventListener("pointerdown", onWindowPointerDown);
  window.addEventListener("keydown", onWindowKeydown);
  window.addEventListener("resize", updateMenuPosition);
  window.addEventListener("scroll", updateMenuPosition, true);
}

function removeOpenListeners() {
  window.removeEventListener("pointerdown", onWindowPointerDown);
  window.removeEventListener("keydown", onWindowKeydown);
  window.removeEventListener("resize", updateMenuPosition);
  window.removeEventListener("scroll", updateMenuPosition, true);
}

onUnmounted(() => {
  removeOpenListeners();
});
</script>

<template>
  <div
    ref="rootRef"
    class="app-select"
    :class="{
      'app-select--open': isOpen,
      'app-select--compact': compact,
      'app-select--align-end': align === 'end',
      'app-select--disabled': disabled,
    }"
  >
    <button
      ref="triggerRef"
      class="app-select__trigger"
      type="button"
      :aria-controls="listboxId"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
      :aria-label="ariaLabel || undefined"
      :disabled="disabled"
      @click="toggleMenu()"
      @keydown="onTriggerKeydown"
    >
      <span class="app-select__value" :class="{ 'app-select__value--placeholder': !selectedOption }">
        {{ selectedLabel }}
      </span>
      <span class="app-select__chevron" aria-hidden="true">
        <svg viewBox="0 0 16 16" fill="none">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </span>
    </button>

    <Teleport to="body">
      <div
        v-if="isOpen"
        :id="listboxId"
        ref="menuRef"
        class="app-select__menu"
        :style="menuStyle"
        role="listbox"
      >
        <button
          v-for="(option, index) in options"
          :key="`${option.value}-${index}`"
          :ref="(element) => setOptionRef(element, index)"
          class="app-select__option"
          :class="{
            'app-select__option--active': option.value === modelValue,
            'app-select__option--highlighted': index === highlightedIndex,
          }"
          type="button"
          role="option"
          :aria-selected="option.value === modelValue"
          @click="selectOption(option)"
          @focus="highlightedIndex = index"
          @keydown="onOptionKeydown($event, option, index)"
        >
          {{ option.label }}
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.app-select {
  position: relative;
  min-width: 0;
}

.app-select__trigger,
.app-select__option {
  width: 100%;
  font: inherit;
}

.app-select__trigger {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 42px;
  padding: 0 34px 0 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.8);
  color: var(--text);
  text-align: left;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease, transform 160ms ease;
}

.app-select__trigger:hover {
  transform: translateY(-1px);
}

.app-select--open .app-select__trigger,
.app-select__trigger:focus-visible {
  border-color: var(--accent);
  box-shadow: 0 0 0 4px rgba(15, 110, 106, 0.12);
  background: #fff;
}

.app-select--disabled .app-select__trigger {
  cursor: not-allowed;
  opacity: 0.64;
}

.app-select__value {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.app-select__value--placeholder {
  color: var(--muted);
}

.app-select__chevron {
  position: absolute;
  right: 12px;
  top: 50%;
  width: 16px;
  height: 16px;
  color: var(--muted);
  transform: translateY(-50%);
  transition: transform 160ms ease;
}

.app-select--open .app-select__chevron {
  transform: translateY(-50%) rotate(180deg);
}

.app-select__chevron svg {
  display: block;
  width: 100%;
  height: 100%;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.app-select__menu {
  position: fixed;
  z-index: 120;
  display: grid;
  gap: 4px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: rgba(255, 250, 244, 0.98);
  box-shadow: 0 18px 38px rgba(47, 33, 20, 0.16);
  backdrop-filter: blur(18px);
  max-height: min(320px, calc(100vh - 24px));
  overflow: auto;
}

.app-select__option {
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  text-align: left;
  font-size: 13px;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.app-select__option:hover,
.app-select__option:focus-visible,
.app-select__option--highlighted {
  background: rgba(15, 110, 106, 0.08);
}

.app-select__option--active {
  border-color: rgba(15, 110, 106, 0.22);
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.app-select--compact .app-select__trigger {
  min-height: 38px;
  padding-left: 11px;
}

.app-select--compact .app-select__value,
.app-select--compact .app-select__option {
  font-size: 12px;
}
</style>
