import { CalendarDays, CarFront, ClipboardList, LayoutDashboard, LogOut, Menu, Search, UserRound, WalletCards, X } from "lucide-react";
import { useState } from "react";
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryClient } from "../lib/query";
import { useCrm } from "../features/crm/useCrm";
import { EntityModal, type EntityModalState } from "../features/crm/EntityModal";
import { DetailModal, type DetailModalState } from "../features/crm/DetailModal";
import { Button, Spinner } from "../components/ui";

export type AppOutlet = { openEntity: (value: NonNullable<EntityModalState>) => void; openDetail: (value: NonNullable<DetailModalState>) => void };

const navigation = [
  { to: "/", label: "Главная", icon: LayoutDashboard },
  { to: "/calendar", label: "Календарь", icon: CalendarDays },
  { to: "/orders", label: "Заказ-наряды", icon: ClipboardList },
  { to: "/customers", label: "Клиенты", icon: UserRound },
  { to: "/cars", label: "Автомобили", icon: CarFront },
  { to: "/finance", label: "Финансы", icon: WalletCards },
];

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [entity, setEntity] = useState<EntityModalState>(null);
  const [detail, setDetail] = useState<DetailModalState>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const crm = useCrm();
  const auth = useQuery({ queryKey: ["auth-check"], queryFn: api.dashboard, retry: false });
  const logout = useMutation({ mutationFn: api.logout, onSettled: () => { queryClient.clear(); void navigate("/login", { replace: true }); } });

  if (auth.isPending || crm.isPending) return <Spinner label="Открываю CRM…" />;
  if (auth.error && "status" in auth.error && auth.error.status === 401) return <Navigate to="/login" replace />;
  if (auth.isError || crm.isError || !crm.data) return <div className="grid min-h-dvh place-items-center p-6"><div className="max-w-md text-center"><h1 className="text-2xl font-black">Не удалось открыть CRM</h1><p className="mt-2 text-muted">Проверьте соединение и повторите попытку.</p><Button className="mt-5" onClick={() => { void auth.refetch(); void crm.refetch(); }}>Повторить</Button></div></div>;

  const closeMenu = () => setMenuOpen(false);
  return <div className="min-h-dvh w-full max-w-full overflow-x-hidden bg-canvas text-white">
    <aside className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-line bg-sidebar p-4 transition-transform lg:translate-x-0 ${menuOpen ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="mb-7 flex items-center justify-between px-2"><img className="h-16 w-auto" src="/assets/brand/apex-logo.png" width="164" height="70" alt="Apex CRM" /><Button variant="ghost" className="size-11 p-0 lg:hidden" onClick={closeMenu} aria-label="Закрыть меню"><X /></Button></div>
      <nav className="grid gap-1" aria-label="Основная навигация">{navigation.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} onClick={closeMenu} className={({ isActive }) => `flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm font-semibold transition ${isActive ? "bg-apex text-black" : "text-muted hover:bg-panel-soft hover:text-white"}`}><Icon size={20} />{label}</NavLink>)}</nav>
      <div className="mt-auto border-t border-line pt-4"><button className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-sm font-semibold text-muted hover:bg-panel-soft hover:text-white" onClick={() => logout.mutate()}><LogOut size={20} />Выйти</button></div>
    </aside>
    {menuOpen && <button className="fixed inset-0 z-30 bg-black/70 lg:hidden" aria-label="Закрыть меню" onClick={closeMenu} />}
    <div className="lg:pl-72">
      <header className="sticky top-0 z-20 flex min-h-16 min-w-0 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur-xl sm:px-6 lg:px-8"><Button variant="ghost" className="size-11 shrink-0 p-0 lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Открыть меню"><Menu /></Button><button className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-xl border border-line bg-panel px-4 text-left text-sm text-muted transition hover:border-apex/50" onClick={() => { void navigate("/search"); }}><Search className="shrink-0" size={18} /><span className="min-w-0 truncate">Поиск по имени, телефону, автомобилю, VIN или номеру</span></button></header>
      <main id="main-content" key={location.pathname} className="mx-auto min-w-0 w-full max-w-[1500px] overflow-x-hidden px-3 py-5 pb-24 sm:px-6 lg:px-8 lg:pb-8"><Outlet context={{ openEntity: setEntity, openDetail: setDetail } satisfies AppOutlet} /></main>
    </div>
    <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-line bg-sidebar/95 px-1 pb-[max(.35rem,env(safe-area-inset-bottom))] pt-1 backdrop-blur-xl lg:hidden" aria-label="Мобильная навигация">{navigation.slice(0, 5).map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl text-[10px] font-semibold ${isActive ? "text-apex" : "text-muted"}`}><Icon size={20} />{label === "Заказ-наряды" ? "Заказы" : label}</NavLink>)}</nav>
    {entity && <EntityModal entity={entity} customers={crm.data.customers} cars={crm.data.cars} onClose={() => setEntity(null)} />}
    {detail && <DetailModal detail={detail} data={crm.data} onClose={() => setDetail(null)} onEdit={(value) => { setDetail(null); setEntity(value); }} onOpen={setDetail} />}
  </div>;
}
