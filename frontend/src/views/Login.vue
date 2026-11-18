<script setup>
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request } from "../lib/api";
import { session } from "../lib/session";
import Icon from "../components/Icon.vue";
const form = reactive({ username: "", email: "", password: "" }),
  register = ref(false),
  busy = ref(false),
  error = ref("");
const router = useRouter(),
  route = useRoute();
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    if (register.value)
      await request("/auth/register", { method: "POST", body: form });
    const token = await request("/auth/login/access-token", {
      method: "POST",
      body: new URLSearchParams({
        username: form.username,
        password: form.password,
      }),
    });
    localStorage.setItem("token", token.access_token);
    session.user = null;
    await session.load();
    const target = route.query.redirect;
    router.replace(
      typeof target === "string" &&
        target.startsWith("/") &&
        !target.startsWith("//") &&
        !target.startsWith("/login")
        ? target
        : "/dashboard",
    );
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-page">
    <div class="login-brand">
      <span class="brand-symbol"><Icon name="pulse" :size="24" /></span>AIOps
    </div>
    <section class="login-form">
      <span class="login-kicker">运维工作空间</span>
      <h1>{{ register ? "创建账号" : "登录" }}</h1>
      <form @submit.prevent="submit">
        <label class="field"
          >用户名<input
            v-model.trim="form.username"
            required
            autocomplete="username"
            :disabled="busy" /></label
        ><label v-if="register" class="field"
          >邮箱<input
            v-model.trim="form.email"
            type="email"
            required
            autocomplete="email" /></label
        ><label class="field"
          >密码<input
            v-model="form.password"
            type="password"
            required
            :minlength="register ? 6 : 1"
            :autocomplete="register ? 'new-password' : 'current-password'"
            :disabled="busy"
        /></label>
        <p v-if="error" class="field-error" role="alert">{{ error }}</p>
        <button class="button primary login-submit" :disabled="busy">
          <span v-if="busy" class="spinner" />{{
            register ? "注册并登录" : "登录"
          }}<Icon name="arrow" :size="18" />
        </button>
      </form>
      <button
        class="text-button"
        :disabled="busy"
        @click="
          register = !register;
          error = '';
        "
      >
        {{ register ? "已有账号，去登录" : "创建账号" }}
      </button>
    </section>
    <div class="login-art" aria-hidden="true">
      <svg viewBox="0 0 600 600" fill="none">
        <path
          d="M60 300h140l55-120 80 240 60-120h145"
          stroke="#0078d4"
          stroke-width="2"
        />
        <circle cx="300" cy="300" r="180" stroke="#d8e8f4" />
        <circle cx="300" cy="300" r="240" stroke="#e5edf4" />
        <path d="M300 0v600M0 300h600" stroke="#e5edf4" />
        <circle cx="200" cy="300" r="5" fill="#0078d4" />
        <circle cx="395" cy="300" r="5" fill="#0078d4" />
      </svg>
    </div>
    <footer class="login-footer">AIOps · 知识与诊断</footer>
  </main>
</template>
