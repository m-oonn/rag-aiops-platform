import { reactive } from "vue";
import { request } from "./api";

let loading;
export const session = reactive({
  user: null,
  async load() {
    if (this.user) return this.user;
    if (!loading)
      loading = request("/auth/me")
        .then((user) => {
          this.user = user;
          return user;
        })
        .finally(() => {
          loading = null;
        });
    return loading;
  },
  logout() {
    localStorage.removeItem("token");
    this.user = null;
  },
});
