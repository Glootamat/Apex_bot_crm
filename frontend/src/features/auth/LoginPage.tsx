import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import { queryClient } from "../../lib/query";
import { Button, inputClass } from "../../components/ui";

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useMutation({ mutationFn: () => api.login(username, password), onSuccess: async () => { queryClient.clear(); await queryClient.prefetchQuery({ queryKey: ["auth-check"], queryFn: api.dashboard }); await navigate("/", { replace: true }); } });
  if (queryClient.getQueryData(["auth-check"])) return <Navigate to="/" replace />;
  const message = mutation.error instanceof ApiError ? mutation.error.message : mutation.error ? "Не удалось войти" : "";
  return <main className="grid min-h-dvh place-items-center bg-login p-4"><form className="w-full max-w-md rounded-3xl border border-white/10 bg-panel p-6 shadow-2xl sm:p-8" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
    <img className="mx-auto h-auto w-56" src="/assets/brand/apex-logo.png" width="360" height="154" alt="Apex CRM" />
    <div className="my-7 text-center"><p className="text-xs font-black tracking-[.24em] text-apex">РАБОЧЕЕ ПРОСТРАНСТВО</p><h1 className="mt-3 text-3xl font-black">Вход в Apex CRM</h1><p className="mt-2 text-sm text-muted">Данные клиентов доступны только авторизованным сотрудникам</p></div>
    <label className="grid gap-2"><span className="text-sm font-semibold">Логин</span><input className={inputClass} value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
    <label className="mt-4 grid gap-2"><span className="text-sm font-semibold">Пароль</span><input className={inputClass} value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></label>
    {message && <p className="mt-4 rounded-xl bg-danger/10 p-3 text-sm text-danger" role="alert">{message}</p>}
    <Button className="mt-6 w-full" type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Вхожу…" : "Войти"}</Button>
  </form></main>;
}
