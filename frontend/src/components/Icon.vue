<script setup>
import {
  ArrowDown,
  ArrowRight,
  ArrowLeft,
  Check,
  ChatDotRound,
  Clock,
  Close,
  Collection,
  DataAnalysis,
  DataBoard,
  Document,
  Download,
  FirstAidKit,
  FolderOpened,
  List,
  Lock,
  MagicStick,
  Menu,
  Monitor,
  More,
  Operation,
  Plus,
  Promotion,
  Refresh,
  Search,
  Share,
  SwitchButton,
  Upload,
  User,
} from "@element-plus/icons-vue";
defineProps({ name: String, size: { type: Number, default: 20 } });
const icons = {
  overview: DataBoard,
  pulse: FirstAidKit,
  history: Clock,
  chat: ChatDotRound,
  book: Collection,
  spark: MagicStick,
  workflow: Share,
  chart: DataAnalysis,
  tasks: List,
  folder: FolderOpened,
  server: Monitor,
  users: User,
  search: Search,
  plus: Plus,
  arrow: ArrowRight,
  chevron: ArrowRight,
  down: ArrowDown,
  refresh: Refresh,
  file: Document,
  upload: Upload,
  download: Download,
  close: Close,
  check: Check,
  logout: SwitchButton,
  menu: Menu,
  send: Promotion,
  shield: Lock,
  clock: Clock,
  dots: More,
  operation: Operation,
  arrowLeft: ArrowLeft,
};
</script>
<template>
  <component
    :is="icons[name] || Document"
    :style="{ width: `${size}px`, height: `${size}px` }"
    aria-hidden="true"
  />
</template>
