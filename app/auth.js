const AUTH_TOKEN_KEY = "financial_mining_token";
const AUTH_USER_KEY = "financial_mining_user";
const API_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";
const PAGE_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";

const form = document.querySelector("[data-auth-form]");
const message = document.querySelector("#formMessage");

function setMessage(text, ok = false) {
  message.textContent = text || "";
  message.classList.toggle("ok", ok);
}

async function api(path, payload) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败，请稍后重试");
  }
  return data;
}

function saveSession(data) {
  localStorage.setItem(AUTH_TOKEN_KEY, data.token);
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(data.user));
}

function readValues() {
  const values = {};
  form.querySelectorAll("input[name]").forEach((input) => {
    values[input.name] = input.value.trim();
  });
  return values;
}

function validateLogin(values) {
  if (!values.username || !values.password) return "请输入用户名和密码";
  return "";
}

function validateRegister(values) {
  if (!values.username || values.username.length < 3) return "用户名至少需要 3 位";
  if (!/^1[3-9]\d{9}$/.test(values.phone || "")) return "请输入正确的手机号";
  if (!values.password || values.password.length < 6) return "密码至少需要 6 位";
  if (values.password !== values.confirmPassword) return "两次输入的密码不一致";
  return "";
}

async function handleSubmit(event) {
  event.preventDefault();
  const mode = form.dataset.authForm;
  const values = readValues();
  const error = mode === "register" ? validateRegister(values) : validateLogin(values);
  if (error) {
    setMessage(error);
    return;
  }

  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  setMessage(mode === "register" ? "正在创建账号..." : "正在登录...", true);
  try {
    const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const payload =
      mode === "register"
        ? { username: values.username, password: values.password, phone: values.phone }
        : { username: values.username, password: values.password };
    const data = await api(path, payload);
    saveSession(data);
    window.location.href = `${PAGE_BASE}/home.html`;
  } catch (error) {
    setMessage(error.message);
  } finally {
    button.disabled = false;
  }
}

form.addEventListener("submit", handleSubmit);
