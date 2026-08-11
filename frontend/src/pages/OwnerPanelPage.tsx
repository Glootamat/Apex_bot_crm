import {
  Ban,
  Building2,
  CalendarDays,
  CarFront,
  Clock3,
  ClipboardList,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { Button, Card, EmptyState, Field, inputClass, Modal, Spinner } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { queryClient } from "../lib/query";
import type { Organization, OrganizationStatus, StaffRole } from "../lib/types";

const emptyForm = {
  name: "",
  city: "",
  owner_name: "",
  username: "",
  password: "",
  demo: true,
};

const statusLabels: Record<OrganizationStatus, string> = {
  active: "Активен",
  demo: "Демо",
  expired: "Демо завершено",
  blocked: "Заблокирован",
};

const statusClasses: Record<OrganizationStatus, string> = {
  active: "bg-success/10 text-success",
  demo: "bg-apex/15 text-apex",
  expired: "bg-warning/15 text-warning",
  blocked: "bg-danger/15 text-danger",
};

const roleNames: Record<string, string> = { owner: "Владелец", admin: "Администратор", service_advisor: "Мастер-приёмщик", mechanic: "Механик", accountant: "Бухгалтер", viewer: "Наблюдатель" };

function dateLabel(value: string | null) {
  if (!value) return "Без ограничения";
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(value));
}

function AccessActions({ service, ownOrganization }: { service: Organization; ownOrganization: boolean }) {
  const access = useMutation({
    mutationFn: (action: "block" | "activate" | "demo") => api.updateOrganizationAccess(service.id, action),
    onSuccess: (updated) => {
      queryClient.setQueryData<Organization[]>(["platform-organizations"], (current) =>
        current?.map((item) => item.id === updated.id ? updated : item),
      );
      void queryClient.invalidateQueries({ queryKey: ["platform-organization", updated.id] });
    },
  });
  if (ownOrganization) return <span className="text-xs font-bold text-muted">Ваш автосервис</span>;
  if (service.status === "blocked" || service.status === "expired") {
    return <div className="flex flex-wrap gap-2">
      <Button className="min-h-9 px-3 py-1.5" variant="secondary" disabled={access.isPending} onClick={() => access.mutate("activate")}><RotateCcw size={15} />Вернуть доступ</Button>
      <Button className="min-h-9 px-3 py-1.5" disabled={access.isPending} onClick={() => access.mutate("demo")}><Clock3 size={15} />Демо 7 дней</Button>
    </div>;
  }
  return <div className="flex flex-wrap gap-2">
    <Button className="min-h-9 px-3 py-1.5" variant="secondary" disabled={access.isPending} onClick={() => access.mutate("demo")}><Clock3 size={15} />Демо 7 дней</Button>
    <Button className="min-h-9 px-3 py-1.5" variant="danger" disabled={access.isPending} onClick={() => {
      if (window.confirm(`Заблокировать доступ для «${service.name}» и всех сотрудников?`)) access.mutate("block");
    }}><Ban size={15} />Заблокировать</Button>
  </div>;
}

function ServiceDetails({ service, ownOrganization, onClose }: { service: Organization; ownOrganization: boolean; onClose: () => void }) {
  const detail = useQuery({ queryKey: ["platform-organization", service.id], queryFn: () => api.organization(service.id), refetchInterval: 60_000 });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<{ full_name: string; username: string; password: string; role: StaffRole }>({ full_name: "", username: "", password: "", role: "service_advisor" });
  const [resetId, setResetId] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const refresh = async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["platform-organization", service.id] }), queryClient.invalidateQueries({ queryKey: ["platform-organizations"] })]); };
  const createStaff = useMutation({ mutationFn: () => api.createOrganizationStaff(service.id, form), onSuccess: async () => { setAdding(false); setForm({ full_name: "", username: "", password: "", role: "service_advisor" }); await refresh(); } });
  const updateStaff = useMutation({ mutationFn: ({ id, active, password }: { id: number; active?: boolean; password?: string }) => api.updateOrganizationStaff(service.id, id, { active, password }), onSuccess: async () => { setResetId(null); setResetPassword(""); await refresh(); } });
  const value = detail.data;
  const createError = createStaff.error instanceof ApiError ? createStaff.error.message : "";
  return <Modal title={service.name} onClose={onClose}>
    {detail.isPending ? <Spinner label="Загружаю информацию об автосервисе…" /> : detail.isError || !value ? <EmptyState>Не удалось загрузить информацию об автосервисе</EmptyState> : <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-3"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${statusClasses[value.status]}`}>{value.status === "demo" ? `Демо · ${value.demo_days_left} дн.` : statusLabels[value.status]}</span><span className="text-sm text-muted">{value.city || "Город не указан"} · создан {dateLabel(value.created_at)}</span></div>
      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4"><ServiceMetric icon={<UsersRound size={17} />} label="Сотрудники" value={`${value.online_staff}/${value.employees}`} hint="сейчас онлайн" /><ServiceMetric icon={<ClipboardList size={17} />} label="Заказы" value={String(value.orders)} hint={`${value.active_orders} в работе`} /><ServiceMetric icon={<CarFront size={17} />} label="Автомобили" value={String(value.cars)} hint={`${value.customers} клиентов`} /><ServiceMetric icon={<CalendarDays size={17} />} label="Записи" value={String(value.scheduled_appointments)} hint="запланировано" /></section>
      <section className="rounded-2xl border border-line bg-canvas/55 p-4"><div className="flex flex-wrap items-start gap-3"><div className="min-w-0 flex-1"><h3 className="font-black">Информация</h3><p className="mt-1 text-sm text-muted">Владелец: {value.owner_name || "не указан"} · логин {value.owner_username}</p><p className="mt-1 text-xs text-muted">Последний заказ: {value.last_order_at ? formatDateTime(value.last_order_at) : "заказов ещё не было"} · доступ до {dateLabel(value.demo_expires_at)}</p></div><AccessActions service={value} ownOrganization={ownOrganization} /></div></section>
      <section><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-black">Сотрудники и доступ</h3><p className="text-sm text-muted">Статус обновляется автоматически раз в минуту</p></div><Button variant="secondary" onClick={() => setAdding((current) => !current)}><UserPlus size={17} />Добавить</Button></div>
        {adding && <form className="mt-3 grid gap-3 rounded-2xl border border-line bg-canvas p-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); createStaff.mutate(); }}><Field label="Имя"><input className={inputClass} value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} required /></Field><Field label="Логин"><input className={inputClass} value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required /></Field><Field label="Пароль от 10 символов"><input className={inputClass} type="password" minLength={10} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required /></Field><Field label="Роль"><select className={inputClass} value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as StaffRole })}><option value="admin">Администратор</option><option value="service_advisor">Мастер-приёмщик</option><option value="mechanic">Механик</option><option value="accountant">Бухгалтер</option><option value="viewer">Наблюдатель</option></select></Field>{createError && <p className="text-sm text-danger sm:col-span-2">{createError}</p>}<div className="flex gap-2 sm:col-span-2"><Button type="submit" disabled={createStaff.isPending}>{createStaff.isPending ? "Добавляю…" : "Создать сотрудника"}</Button><Button type="button" variant="ghost" onClick={() => setAdding(false)}>Отмена</Button></div></form>}
        <div className="mt-3 grid gap-2">{value.staff.map((member) => <article key={member.id} className="rounded-xl border border-line/70 bg-panel-soft p-3"><div className="flex flex-wrap items-start gap-3"><span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${member.online ? "bg-success shadow-[0_0_10px_rgba(50,213,131,.8)]" : "bg-muted"}`} /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><strong>{member.full_name}</strong><span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${member.online ? "bg-success/15 text-success" : "bg-canvas text-muted"}`}>{member.online ? "Онлайн" : "Офлайн"}</span></div><p className="text-sm text-muted">{member.username} · {roleNames[member.role]}</p><p className="mt-1 text-xs text-muted">Входов сегодня: {member.logins_today}{member.last_seen_at && !member.online ? ` · был в сети ${formatDateTime(member.last_seen_at)}` : ""}</p></div>{member.role !== "owner" && <div className="flex flex-wrap gap-2"><Button className="min-h-9 px-3 py-1.5" variant="secondary" disabled={updateStaff.isPending} onClick={() => updateStaff.mutate({ id: member.id, active: !member.active })}>{member.active ? "Отключить" : "Включить"}</Button><Button className="min-h-9 px-3 py-1.5" variant="ghost" onClick={() => { setResetId(resetId === member.id ? null : member.id); setResetPassword(""); }}><KeyRound size={15} />Пароль</Button></div>}</div>{resetId === member.id && <form className="mt-3 flex flex-col gap-2 border-t border-line pt-3 sm:flex-row" onSubmit={(event) => { event.preventDefault(); updateStaff.mutate({ id: member.id, password: resetPassword }); }}><input className={inputClass} type="password" minLength={10} placeholder="Новый пароль, минимум 10 символов" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required /><Button type="submit" disabled={updateStaff.isPending || resetPassword.length < 10}>Сохранить</Button></form>}</article>)}</div>
      </section>
    </div>}
  </Modal>;
}

function ServiceMetric({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint: string }) { return <div className="rounded-xl bg-canvas p-3"><span className="text-apex">{icon}</span><strong className="mt-2 block text-xl">{value}</strong><span className="block text-xs text-muted">{label} · {hint}</span></div>; }

export function OwnerPanelPage() {
  const account = useQuery({ queryKey: ["account"], queryFn: api.account });
  const services = useQuery({ queryKey: ["platform-organizations"], queryFn: api.organizations, enabled: Boolean(account.data?.platform_admin) });
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<OrganizationStatus | "all">("all");
  const [form, setForm] = useState(emptyForm);
  const [showPassword, setShowPassword] = useState(false);
  const [createdCredentials, setCreatedCredentials] = useState<{ name: string; username: string; password: string } | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const create = useMutation({
    mutationFn: api.createOrganization,
    onSuccess: async () => {
      setCreatedCredentials({ name: form.name, username: form.username, password: form.password });
      setOpen(false);
      setForm(emptyForm);
      await queryClient.invalidateQueries({ queryKey: ["platform-organizations"] });
    },
  });
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ru-RU");
    return (services.data ?? []).filter((item) =>
      (status === "all" || item.status === status) &&
      (!needle || [item.name, item.city, item.owner_name, item.owner_username].some((value) => value?.toLocaleLowerCase("ru-RU").includes(needle))),
    );
  }, [query, services.data, status]);

  if (account.isPending) return <Spinner label="Открываю панель владельца…" />;
  if (!account.data?.platform_admin) return <Navigate to="/" replace />;
  const counts = (services.data ?? []).reduce((result, item) => ({
    total: result.total + 1,
    active: result.active + (item.status === "active" ? 1 : 0),
    attention: result.attention + (["expired", "blocked"].includes(item.status) ? 1 : 0),
  }), { total: 0, active: 0, attention: 0 });
  const createError = create.error instanceof ApiError ? create.error.message : "";
  const selectedService = (services.data ?? []).find((item) => item.id === selectedId) ?? null;

  return <div className="grid gap-5">
    <header className="flex flex-wrap items-start gap-4">
      <div className="flex min-w-0 flex-1 items-center gap-4">
        <img className="size-16 rounded-2xl object-cover shadow-[0_10px_30px_rgba(255,214,0,.16)]" src="/assets/brand/apex-logo.png" alt="Apex Auto" />
        <div><p className="text-xs font-black tracking-wide text-apex sm:text-sm">APEX CONTROL · КЛИЕНТЫ ПЛАТФОРМЫ</p><h1 className="text-2xl font-black sm:text-4xl">Панель владельца</h1><p className="mt-1 text-sm text-muted">{counts.total} автосервисов · {counts.active} активных · {counts.attention} требуют внимания</p></div>
      </div>
      <Button className="w-full sm:w-auto" onClick={() => setOpen(true)}><Plus size={18} />Новый автосервис</Button>
    </header>

    {createdCredentials && <Card className="border-apex/40 bg-apex/5">
      <div className="flex flex-wrap items-start gap-3"><KeyRound className="text-apex" /><div className="min-w-0 flex-1"><h2 className="font-black">Автосервис «{createdCredentials.name}» подключён</h2><p className="mt-1 text-sm text-muted">Передайте владельцу данные для первого входа. Пароль после закрытия уведомления больше не показывается.</p><p className="mt-3 break-all rounded-xl bg-canvas p-3 font-mono text-sm">Логин: {createdCredentials.username}<br />Пароль: {createdCredentials.password}</p></div><Button variant="secondary" onClick={() => void navigator.clipboard.writeText(`Apex CRM\nЛогин: ${createdCredentials.username}\nПароль: ${createdCredentials.password}`)}><Copy size={16} />Копировать</Button><Button variant="ghost" onClick={() => setCreatedCredentials(null)}>Скрыть</Button></div>
    </Card>}

    <Card className="grid gap-3 sm:grid-cols-[1fr_auto]">
      <label className="flex min-h-12 items-center gap-3 rounded-xl border border-line bg-canvas px-4 focus-within:border-apex"><Search className="text-muted" size={18} /><input className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted" placeholder="Название, владелец, город или логин" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <select className={`${inputClass} sm:w-52`} value={status} onChange={(event) => setStatus(event.target.value as OrganizationStatus | "all")}><option value="all">Все состояния</option><option value="active">Активные</option><option value="demo">Демо</option><option value="expired">Демо завершено</option><option value="blocked">Заблокированные</option></select>
    </Card>

    {services.isPending ? <Spinner label="Загружаю автосервисы…" /> : services.isError ? <EmptyState>Не удалось загрузить автосервисы</EmptyState> : filtered.length ? <>
      <div className="hidden overflow-x-auto rounded-2xl border border-line bg-panel shadow-card lg:block"><table className="w-full text-left text-sm"><thead className="border-b border-line text-xs uppercase tracking-wide text-muted"><tr><th className="p-4">Автосервис</th><th className="p-4">Владелец</th><th className="p-4">Сотрудники</th><th className="p-4">Заказы</th><th className="p-4">Доступ до</th><th className="p-4">Состояние</th><th className="p-4">Управление</th></tr></thead><tbody className="divide-y divide-line">{filtered.map((service) => <tr key={service.id} className="align-top"><td className="p-4"><button type="button" className="group text-left" onClick={() => setSelectedId(service.id)}><strong className="block text-base transition group-hover:text-apex">{service.name}</strong><span className="text-muted">{service.city || "Город не указан"} · подробнее</span></button></td><td className="p-4"><strong className="block">{service.owner_name || "Не указан"}</strong><span className="text-muted">{service.owner_username}</span></td><td className="p-4 font-bold">{service.employees}</td><td className="p-4 font-bold">{service.orders}</td><td className="p-4">{dateLabel(service.demo_expires_at)}</td><td className="p-4"><span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-black ${statusClasses[service.status]}`}>{service.status === "demo" ? `Демо · ${service.demo_days_left} дн.` : statusLabels[service.status]}</span></td><td className="p-4"><AccessActions service={service} ownOrganization={service.id === account.data.organization_id} /></td></tr>)}</tbody></table></div>
      <div className="grid gap-3 lg:hidden">{filtered.map((service) => <Card key={service.id}><button type="button" className="flex w-full items-start gap-3 text-left" onClick={() => setSelectedId(service.id)}><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-apex/10 text-apex"><Building2 size={21} /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-black">{service.name}</h2><span className={`rounded-full px-2.5 py-1 text-xs font-black ${statusClasses[service.status]}`}>{service.status === "demo" ? `Демо · ${service.demo_days_left} дн.` : statusLabels[service.status]}</span></div><p className="text-sm text-muted">{service.city || "Город не указан"} · {service.owner_name || "Владелец не указан"}</p><span className="mt-1 block text-xs font-bold text-apex">Открыть подробную информацию</span></div></button><dl className="my-4 grid grid-cols-3 gap-2 rounded-xl bg-canvas p-3 text-center"><div><dt className="text-xs text-muted">Сотрудники</dt><dd className="font-black">{service.employees}</dd></div><div><dt className="text-xs text-muted">Заказы</dt><dd className="font-black">{service.orders}</dd></div><div><dt className="text-xs text-muted">Доступ до</dt><dd className="text-xs font-bold">{dateLabel(service.demo_expires_at)}</dd></div></dl><AccessActions service={service} ownOrganization={service.id === account.data.organization_id} /></Card>)}</div>
    </> : <EmptyState>Автосервисы по выбранным условиям не найдены</EmptyState>}

    {selectedService && <ServiceDetails service={selectedService} ownOrganization={selectedService.id === account.data.organization_id} onClose={() => setSelectedId(null)} />}
    {open && <Modal title="Подключить новый автосервис" onClose={() => setOpen(false)}><form className="grid gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate(form); }}><Field label="Название автосервиса"><input className={inputClass} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /></Field><Field label="Город"><input className={inputClass} value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} /></Field><Field label="Имя владельца"><input className={inputClass} value={form.owner_name} onChange={(event) => setForm({ ...form, owner_name: event.target.value })} required /></Field><Field label="Логин владельца"><input className={inputClass} value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} autoComplete="off" required /></Field><Field label="Временный пароль (от 10 символов)" full><div className="relative"><input className={`${inputClass} pr-12`} type={showPassword ? "text" : "password"} minLength={10} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} autoComplete="new-password" required /><button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-2 text-muted hover:bg-panel-soft hover:text-white" onClick={() => setShowPassword((current) => !current)} aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"} title={showPassword ? "Скрыть пароль" : "Показать пароль"}>{showPassword ? <EyeOff size={19} /> : <Eye size={19} />}</button></div></Field><label className="flex items-center gap-3 rounded-xl border border-line bg-canvas p-4 sm:col-span-2"><input className="size-5 accent-[#ffd600]" type="checkbox" checked={form.demo} onChange={(event) => setForm({ ...form, demo: event.target.checked })} /><span><strong className="block">Демо-доступ на 7 дней</strong><span className="text-sm text-muted">По окончании недели вход автоматически закроется</span></span></label>{createError && <p className="text-sm text-danger sm:col-span-2">{createError}</p>}<div className="flex flex-wrap gap-2 sm:col-span-2"><Button type="submit" disabled={create.isPending}><ShieldCheck size={17} />{create.isPending ? "Подключаю…" : "Создать автосервис"}</Button><Button type="button" variant="secondary" onClick={() => setOpen(false)}>Отмена</Button></div></form></Modal>}
  </div>;
}
