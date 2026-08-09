import {
  CalendarDays,
  CarFront,
  ClipboardCheck,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  Trash2,
  UserRound,
  WalletCards,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Navigate,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryClient } from "../lib/query";
import { useCrm } from "../features/crm/useCrm";
import {
  EntityModal,
  type EntityModalState,
} from "../features/crm/EntityModal";
import {
  DetailModal,
  type DetailModalState,
} from "../features/crm/DetailModal";
import { BrandedLoader, Button } from "../components/ui";
import { useAppSettings, type ModuleKey } from "../lib/settings";

export type AppOutlet = {
  openEntity: (value: NonNullable<EntityModalState>) => void;
  openDetail: (value: NonNullable<DetailModalState>) => void;
};

const navigation = [
  { to: "/", label: "Главная", icon: LayoutDashboard },
  { to: "/calendar", label: "Календарь", icon: CalendarDays },
  { to: "/orders", label: "Заказ-наряды", icon: ClipboardList },
  { to: "/diagnostics", label: "Диагностика", icon: ClipboardCheck },
  { to: "/customers", label: "Клиенты", icon: UserRound },
  { to: "/cars", label: "Автомобили", icon: CarFront },
  { to: "/finance", label: "Финансы", icon: WalletCards },
  { to: "/trash", label: "Корзина", icon: Trash2 },
];

const mobileNavigation = [
  navigation[0]!,
  navigation[1]!,
  navigation[2]!,
  navigation[3]!,
  navigation[6]!,
];

const moduleByPath: Partial<Record<string, ModuleKey>> = {
  "/calendar": "calendar", "/orders": "orders", "/diagnostics": "diagnostics",
  "/customers": "customers", "/cars": "cars", "/finance": "finance", "/trash": "trash",
};

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const swipeStart = useRef<{ x: number; y: number; tracking: boolean } | null>(
    null,
  );
  const [entity, setEntity] = useState<EntityModalState>(null);
  const [detail, setDetail] = useState<DetailModalState>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const crm = useCrm();
  const settings = useAppSettings();
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, retry: false });
  const organizationName = account.data?.organization_name?.trim() || "APEX AUTO";
  const isApexOrganization = organizationName.toLocaleLowerCase("ru") === "apex auto";
  const memberName = account.data?.full_name?.trim() || account.data?.username || "Пользователь";
  const roleName = account.data?.role === "owner" ? "Владелец" : "Сотрудник";
  const isVisible = (path: string) => !moduleByPath[path] || settings.modules[moduleByPath[path]];
  const visibleNavigation = navigation.filter((item) => isVisible(item.to));
  const auth = useQuery({
    queryKey: ["auth-check"],
    queryFn: api.dashboard,
    retry: false,
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      queryClient.clear();
      void navigate("/login", { replace: true });
    },
  });

  useEffect(() => {
    if (!settings.autoLockMinutes) return;
    let timer = window.setTimeout(() => logout.mutate(), settings.autoLockMinutes * 60_000);
    const resetTimer = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => logout.mutate(), settings.autoLockMinutes * 60_000);
    };
    const events = ["pointerdown", "keydown", "touchstart"] as const;
    events.forEach((event) => window.addEventListener(event, resetTimer, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      events.forEach((event) => window.removeEventListener(event, resetTimer));
    };
  }, [logout.mutate, settings.autoLockMinutes]);

  const markModalInHistory = useCallback(() => {
    if (!window.history.state?.apexModal) {
      window.history.pushState(
        { ...window.history.state, apexModal: true },
        "",
        window.location.href,
      );
    }
  }, []);
  const openEntity = useCallback(
    (value: NonNullable<EntityModalState>) => {
      if (!entity && !detail) markModalInHistory();
      setDetail(null);
      setEntity(value);
    },
    [detail, entity, markModalInHistory],
  );
  const openDetail = useCallback(
    (value: NonNullable<DetailModalState>) => {
      if (!entity && !detail) markModalInHistory();
      setEntity(null);
      setDetail(value);
    },
    [detail, entity, markModalInHistory],
  );
  const closeModal = useCallback(() => {
    setEntity(null);
    setDetail(null);
    if (window.history.state?.apexModal) window.history.back();
  }, []);

  useEffect(() => {
    const closeOnBack = () => {
      setEntity(null);
      setDetail(null);
      setMenuOpen(false);
    };
    window.addEventListener("popstate", closeOnBack);
    return () => window.removeEventListener("popstate", closeOnBack);
  }, []);

  useEffect(() => {
    const touchStart = (event: TouchEvent) => {
      if (
        event.touches.length !== 1 ||
        !window.matchMedia("(max-width: 1023px)").matches
      )
        return;
      const touch = event.touches[0];
      if (!touch) return;
      swipeStart.current = {
        x: touch.clientX,
        y: touch.clientY,
        tracking: menuOpen || touch.clientX <= 32,
      };
    };
    const touchEnd = (event: TouchEvent) => {
      const start = swipeStart.current;
      swipeStart.current = null;
      if (!start?.tracking || event.changedTouches.length !== 1) return;
      const touch = event.changedTouches[0];
      if (!touch) return;
      const deltaX = touch.clientX - start.x;
      const deltaY = touch.clientY - start.y;
      if (
        Math.abs(deltaY) > 70 ||
        Math.abs(deltaX) < 72 ||
        Math.abs(deltaX) < Math.abs(deltaY) * 1.4
      )
        return;
      if (!menuOpen && deltaX > 0) setMenuOpen(true);
      if (menuOpen && deltaX < 0) setMenuOpen(false);
    };
    const cancelSwipe = () => {
      swipeStart.current = null;
    };
    document.addEventListener("touchstart", touchStart, { passive: true });
    document.addEventListener("touchend", touchEnd, { passive: true });
    document.addEventListener("touchcancel", cancelSwipe, { passive: true });
    return () => {
      document.removeEventListener("touchstart", touchStart);
      document.removeEventListener("touchend", touchEnd);
      document.removeEventListener("touchcancel", cancelSwipe);
    };
  }, [menuOpen]);

  if (auth.isPending || crm.isPending) return <BrandedLoader />;
  if (auth.error && "status" in auth.error && auth.error.status === 401)
    return <Navigate to="/login" replace />;
  if (auth.isError || crm.isError || !crm.data)
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <div className="max-w-md text-center">
          <h1 className="text-2xl font-black">Не удалось открыть CRM</h1>
          <p className="mt-2 text-muted">
            Проверьте соединение и повторите попытку.
          </p>
          <Button
            className="mt-5"
            onClick={() => {
              void auth.refetch();
              void crm.refetch();
            }}
          >
            Повторить
          </Button>
        </div>
      </div>
    );

  const closeMenu = () => setMenuOpen(false);
  return (
    <div className={`min-h-dvh w-full max-w-full overflow-x-hidden bg-canvas text-white ${settings.compactMode ? "app-compact" : ""} ${settings.reduceMotion ? "app-reduce-motion" : ""}`}>
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-line bg-sidebar p-4 transition-transform lg:translate-x-0 ${menuOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-7 flex items-center justify-between px-2">
          <div className="flex min-w-0 items-center gap-3">
            {isApexOrganization ? <img
              className="size-14 shrink-0 rounded-2xl object-cover shadow-[0_8px_24px_rgba(255,214,0,.14)]"
              src="/assets/brand/apex-logo.png"
              width="56"
              height="56"
              alt="Apex CRM"
            /> : <div className="grid size-14 shrink-0 place-items-center rounded-2xl bg-apex/15 text-2xl font-black text-apex shadow-[0_8px_24px_rgba(255,214,0,.14)]" aria-label={organizationName}>{organizationName.slice(0, 1).toLocaleUpperCase("ru")}</div>}
            <p className="min-w-0 truncate text-xl font-black leading-none tracking-tight text-white">
              {organizationName}
            </p>
          </div>
          <Button
            variant="ghost"
            className="size-11 p-0 lg:hidden"
            onClick={closeMenu}
            aria-label="Закрыть меню"
          >
            <X />
          </Button>
        </div>
        <nav className="grid gap-1" aria-label="Основная навигация">
          {visibleNavigation.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={closeMenu}
              className={({ isActive }) =>
                `flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm font-semibold transition ${isActive ? "bg-apex text-black" : "text-muted hover:bg-panel-soft hover:text-white"}`
              }
            >
              <Icon size={20} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto border-t border-line pt-4">
          {Boolean(account.data?.platform_admin) && <NavLink
            to="/owner"
            onClick={closeMenu}
            className={({ isActive }) => `mb-1 flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm font-semibold transition ${isActive ? "bg-apex text-black" : "text-muted hover:bg-panel-soft hover:text-white"}`}
          >
            <ShieldCheck size={20} />
            Панель владельца
          </NavLink>}
          {account.data && (
            <div className="mb-3 rounded-xl border border-line bg-panel-soft px-3 py-2.5">
              <p className="truncate text-sm font-bold text-white">{memberName}</p>
              <p className="mt-0.5 truncate text-xs text-muted">
                {organizationName} · {roleName}
              </p>
            </div>
          )}
          <NavLink
            to="/settings"
            onClick={closeMenu}
            className={({ isActive }) => `mb-1 flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm font-semibold transition ${isActive ? "bg-apex text-black" : "text-muted hover:bg-panel-soft hover:text-white"}`}
          >
            <Settings size={20} />
            Настройки
          </NavLink>
          <button
            className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-sm font-semibold text-muted hover:bg-panel-soft hover:text-white"
            onClick={() => logout.mutate()}
          >
            <LogOut size={20} />
            Выйти
          </button>
        </div>
      </aside>
      {menuOpen && (
        <button
          className="fixed inset-0 z-30 bg-black/70 lg:hidden"
          aria-label="Закрыть меню"
          onClick={closeMenu}
        />
      )}
      <div className="lg:pl-72">
        <header className="sticky top-0 z-20 flex min-h-16 min-w-0 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
          <Button
            variant="ghost"
            className="size-11 shrink-0 p-0 lg:hidden"
            onClick={() => setMenuOpen(true)}
            aria-label="Открыть меню"
          >
            <Menu />
          </Button>
          <button
            className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-xl border border-line bg-panel px-4 text-left text-sm text-muted transition hover:border-apex/50"
            onClick={() => {
              void navigate("/search");
            }}
          >
            <Search className="shrink-0" size={18} />
            <span className="min-w-0 truncate">
              Поиск по имени, телефону, автомобилю, VIN или номеру
            </span>
          </button>
          <Button
            variant="ghost"
            className="size-11 shrink-0 p-0 lg:hidden"
            onClick={() => void navigate("/trash")}
            aria-label="Открыть корзину"
          >
            <Trash2 size={20} />
          </Button>
        </header>
        <main
          id="main-content"
          key={location.pathname}
          className="mx-auto min-w-0 w-full max-w-[1500px] overflow-x-hidden px-3 py-5 pb-24 sm:px-6 lg:px-8 lg:pb-8"
        >
          <Outlet context={{ openEntity, openDetail } satisfies AppOutlet} />
        </main>
      </div>
      <nav
        className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-line bg-sidebar/95 px-1 pb-[max(.35rem,env(safe-area-inset-bottom))] pt-1 backdrop-blur-xl lg:hidden"
        aria-label="Мобильная навигация"
      >
        {mobileNavigation.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl px-0.5 text-center text-[10px] font-semibold leading-tight ${isActive ? "text-apex" : "text-muted"}`
            }
          >
            <Icon size={20} />
            {label}
          </NavLink>
        ))}
      </nav>
      {entity && (
        <EntityModal
          entity={entity}
          customers={crm.data.customers}
          cars={crm.data.cars}
          onClose={closeModal}
        />
      )}
      {detail && (
        <DetailModal
          key={`${detail.kind}-${detail.value.id}`}
          detail={detail}
          data={crm.data}
          onClose={closeModal}
          onEdit={(value) => {
            setDetail(null);
            setEntity(value);
          }}
          onOpen={(value) => {
            setEntity(null);
            setDetail(value);
          }}
        />
      )}
    </div>
  );
}
