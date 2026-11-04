import { FormEvent, useState } from "react";
import { ApiError, api, auth } from "../api";

export default function Login({ onDone }: { onDone: () => void }) {
  const [err, setErr] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const r = await api<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email: f.get("email"), password: f.get("password") }) });
      auth.set(r.access_token); onDone();
    } catch (x) { setErr(x instanceof ApiError ? x.message : "Không kết nối được máy chủ"); }
  }
  return (
    <form onSubmit={submit} className="card login">
      <h1>PAACC Construction AI</h1>
      <input name="email" type="email" placeholder="Email" required />
      <input name="password" type="password" placeholder="Mật khẩu" required />
      {err && <p className="error">{err}</p>}
      <button>Đăng nhập</button>
    </form>
  );
}
