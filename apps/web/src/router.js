import { createRouter, createWebHistory } from "vue-router";
import WorkspaceView from "./views/WorkspaceView.vue";
import PreviewView from "./views/PreviewView.vue";
import AdminView from "./views/AdminView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "workspace",
      component: WorkspaceView,
    },
    {
      path: "/preview/:jobId",
      name: "preview",
      component: PreviewView,
      props: true,
    },
    {
      path: "/admin/:page?",
      name: "admin",
      component: AdminView,
      props: true,
    },
  ],
});

export default router;
