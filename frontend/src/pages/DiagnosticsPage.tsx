import {
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  FileDown,
  FileImage,
  FolderOpen,
  Gauge,
  Images,
  Search,
  Save,
  Share2,
  Trash2,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Button,
  Card,
  EmptyState,
  inputClass,
  Modal,
  Spinner,
} from "../components/ui";
import { api } from "../lib/api";
import { exportDiagnosticImage } from "../lib/diagnosticImage";
import { customerName, formatDateTime, money } from "../lib/format";
import { queryClient } from "../lib/query";
import type {
  Diagnostic,
  DiagnosticItem,
  DiagnosticItemInput,
  DiagnosticStatus,
} from "../lib/types";

const sections = [
  ["general", "Основное"],
  ["front_suspension", "Передняя подвеска"],
  ["rear_suspension", "Задняя подвеска"],
  ["brakes", "Тормозная система"],
  ["engine", "Двигатель"],
  ["body", "Кузов и салон"],
  ["electrics", "Электрика"],
  ["ac", "Климат"],
] as const;

const statusMeta: Record<
  DiagnosticStatus,
  { label: string; short: string; className: string }
> = {
  unchecked: {
    label: "Не проверено",
    short: "—",
    className: "border-line bg-panel-soft text-muted",
  },
  ok: {
    label: "Норма",
    short: "✓",
    className: "border-success/40 bg-success/10 text-success",
  },
  attention: {
    label: "Внимание",
    short: "!",
    className: "border-apex/50 bg-apex/10 text-apex",
  },
  critical: {
    label: "Неисправно",
    short: "×",
    className: "border-danger/50 bg-danger/10 text-danger",
  },
};
const statusOrder: DiagnosticStatus[] = [
  "unchecked",
  "ok",
  "attention",
  "critical",
];

function normalizeSearchValue(value: unknown) {
  const primitive = typeof value === "string" || typeof value === "number" ? value : "";
  return String(primitive)
    .toLocaleLowerCase("ru-RU")
    .replace(/ё/g, "е")
    .replace(/[^a-zа-я0-9]+/gi, "");
}

export function DiagnosticsIndexPage() {
  const navigate = useNavigate();
  const [diagnosticSearch, setDiagnosticSearch] = useState("");
  const diagnostics = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => api.diagnostics(),
  });
  const deleteDiagnostic = useMutation({
    mutationFn: (id: number) => api.deleteDiagnostic(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["diagnostics"] }),
    onError: () => window.alert("Не удалось удалить диагностическую карту"),
  });
  const confirmDeleteDiagnostic = (id: number) => {
    if (window.confirm("Удалить диагностическую карту без возможности восстановления?")) {
      deleteDiagnostic.mutate(id);
    }
  };
  const filteredDiagnostics = useMemo(() => {
    const terms = diagnosticSearch.trim().split(/\s+/).filter(Boolean);
    const cards = diagnostics.data ?? [];
    if (!terms.length) return cards;
    return cards.filter((card) => {
      const haystack = [
        card.id, card.brand, card.model, card.plate_number, card.vin,
        card.customer_name, card.customer_phone,
        card.status === "completed" ? "завершена" : "черновик",
      ].map(normalizeSearchValue).join(" ");
      return terms.every((term) => haystack.includes(normalizeSearchValue(term)));
    });
  }, [diagnosticSearch, diagnostics.data]);
  if (diagnostics.isPending)
    return <Spinner label="Открываю диагностику…" />;
  return (
    <div className="grid gap-5">
      <header>
        <p className="text-sm font-bold text-apex">ТЕХНИЧЕСКОЕ СОСТОЯНИЕ</p>
        <h1 className="text-3xl font-black">Диагностика автомобилей</h1>
        <p className="mt-1 text-muted">Новые карты создаются из карточки автомобиля или заказ-наряда.</p>
      </header>
      <section>
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="relative block flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted" />
            <input
              value={diagnosticSearch}
              onChange={(event) => setDiagnosticSearch(event.target.value)}
              className={`${inputClass} w-full pl-12 pr-12`}
              placeholder="Поиск: авто, клиент, телефон, госномер, VIN или №"
              autoComplete="off"
              aria-label="Поиск диагностических карт"
            />
            {diagnosticSearch && (
              <button
                type="button"
                onClick={() => setDiagnosticSearch("")}
                className="absolute right-3 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-muted transition hover:bg-panel-soft hover:text-white"
                aria-label="Очистить поиск"
              >
                <X className="size-4" />
              </button>
            )}
          </label>
          {diagnosticSearch && <span className="shrink-0 text-sm text-muted">Найдено: {filteredDiagnostics.length}</span>}
        </div>
        <h2 className="mb-3 text-lg font-black">Недавние карты</h2>
        {filteredDiagnostics.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filteredDiagnostics.map((item) => (
              <Card
                key={item.id}
                className="cursor-pointer transition hover:border-apex/50"
                onClick={() => void navigate(`/diagnostics/${item.id}`)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-bold text-apex">
                      {item.status === "completed" ? "ЗАВЕРШЕНА" : "ЧЕРНОВИК"}
                    </p>
                    <h3 className="font-black">
                      {item.brand} {item.model}
                    </h3>
                    <p className="text-sm text-muted">
                      {formatDateTime(item.updated_at)}
                    </p>
                    <p className="mt-1 truncate text-xs text-muted">{item.customer_name || item.plate_number || item.vin || "Автомобиль без номера"}{item.customer_phone ? ` · ${item.customer_phone}` : ""}</p>
                  </div>
                  <span className="rounded-full bg-panel-soft px-3 py-1 text-xs font-bold" aria-label={`Проверено ${item.checked} из ${item.total}`}>
                    Проверено: {item.checked}/{item.total}
                  </span>
                </div>
                <div className="mt-4 flex items-end justify-between gap-3">
                  <div className="flex flex-wrap gap-3 text-sm">
                    <span className="text-apex">Внимание: {item.attention}</span>
                    <span className="text-danger">
                      Неисправно: {item.critical}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      confirmDeleteDiagnostic(item.id);
                    }}
                    disabled={deleteDiagnostic.isPending}
                    className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-bold text-muted transition hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                    aria-label="Удалить диагностическую карту"
                  >
                    <Trash2 className="size-3.5" />
                    Удалить
                  </button>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState>{diagnosticSearch ? `По запросу «${diagnosticSearch}» карт не найдено.` : "Диагностических карт пока нет."}</EmptyState>
        )}
      </section>
    </div>
  );
}

export function DiagnosticPage() {
  const { diagnosticId } = useParams();
  const [search] = useSearchParams();
  const id = diagnosticId ? Number(diagnosticId) : null;
  const carId = Number(search.get("car_id"));
  const orderId = Number(search.get("order_id")) || undefined;
  const queryKey = ["diagnostic", id ?? "start", carId, orderId] as const;
  const diagnostic = useQuery({
    queryKey,
    queryFn: () =>
      id ? api.diagnostic(id) : api.startDiagnostic(carId, orderId),
    enabled: Boolean(id || carId),
  });
  if (!id && !carId) return <EmptyState>Автомобиль не выбран</EmptyState>;
  if (diagnostic.isPending)
    return <Spinner label="Готовлю карту диагностики…" />;
  if (diagnostic.isError || !diagnostic.data)
    return <EmptyState>Не удалось открыть диагностическую карту</EmptyState>;
  return <DiagnosticCard value={diagnostic.data} queryKey={queryKey} />;
}

function ProtectedDiagnosticPhoto({ id, path, alt, onOpen }: { id: number; path: string; alt: string; onOpen: () => void }) {
  const photo = useQuery({
    queryKey: ["diagnostic-photo", id, path],
    queryFn: async () => URL.createObjectURL(await api.diagnosticPhoto(path)),
    staleTime: Infinity,
  });
  useEffect(() => () => {
    if (photo.data) URL.revokeObjectURL(photo.data);
  }, [photo.data]);
  if (photo.isPending) return <div className="aspect-square animate-pulse rounded-xl bg-panel-soft" aria-label="Загрузка фото" />;
  if (photo.isError || !photo.data) return <div className="grid aspect-square place-items-center rounded-xl bg-danger/10 p-2 text-center text-xs text-danger">Фото недоступно</div>;
  return <button type="button" className="relative aspect-square overflow-hidden rounded-xl" onClick={onOpen} aria-label={`Открыть: ${alt}`}><img className="size-full object-cover transition hover:scale-105" src={photo.data} alt={alt} /></button>;
}

function DiagnosticPhotoViewer({ photos, index, onChange, onClose }: { photos: Diagnostic["photos"]; index: number; onChange: (index: number) => void; onClose: () => void }) {
  const current = photos[index]!;
  const photo = useQuery({ queryKey: ["diagnostic-photo-viewer", current.id, current.url], queryFn: async () => URL.createObjectURL(await api.diagnosticPhoto(current.url)), staleTime: Infinity });
  useEffect(() => () => { if (photo.data) URL.revokeObjectURL(photo.data); }, [photo.data]);
  return <Modal title={`Фото ${index + 1} из ${photos.length}`} onClose={onClose}><div className="grid gap-3"><div className="grid min-h-64 place-items-center rounded-xl bg-canvas">{photo.data ? <img className="max-h-[65dvh] w-full rounded-xl object-contain" src={photo.data} alt={current.caption || "Фото диагностики"} /> : <Spinner label="Загружаю фото…" />}</div><div className="grid grid-cols-2 gap-2"><Button variant="secondary" disabled={index === 0} onClick={() => onChange(index - 1)}>← Предыдущее</Button><Button variant="secondary" disabled={index === photos.length - 1} onClick={() => onChange(index + 1)}>Следующее →</Button></div></div></Modal>;
}

function DiagnosticCard({
  value,
  queryKey,
}: {
  value: Diagnostic;
  queryKey: readonly unknown[];
}) {
  const [statusFilter, setStatusFilter] = useState<DiagnosticStatus | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [photoSourceOpen, setPhotoSourceOpen] = useState(false);
  const [photoIndex, setPhotoIndex] = useState<number | null>(null);
  const navigate = useNavigate();
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, retry: false });
  const organizationName = account.data?.organization_name?.trim() || "APEX AUTO";
  const cameraInput = useRef<HTMLInputElement>(null);
  const galleryInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const updateLocal = (updater: (current: Diagnostic) => Diagnostic) =>
    queryClient.setQueryData<Diagnostic>(queryKey, (current) =>
      current ? updater(current) : current,
    );
  const itemMutation = useMutation({
    mutationFn: ({ key, input }: { key: string; input: DiagnosticItemInput }) =>
      api.updateDiagnosticItem(value.id, key, input),
    onSuccess: (item) =>
      updateLocal((current) => ({
        ...current,
        items: current.items.map((old) =>
          old.item_key === item.item_key ? item : old,
        ),
      })),
  });
  const cardMutation = useMutation({
    mutationFn: (input: {
      mileage: number | null;
      notes: string | null;
      status: "draft" | "completed";
    }) => api.updateDiagnostic(value.id, input),
    onSuccess: (card) => {
      queryClient.setQueryData(queryKey, card);
      void queryClient.invalidateQueries({ queryKey: ["diagnostics"] });
    },
  });
  const photoMutation = useMutation({
    mutationFn: (file: File) => api.uploadDiagnosticPhoto(value.id, file),
    onSuccess: (photo) =>
      updateLocal((current) => ({
        ...current,
        photos: [...current.photos, photo],
      })),
  });
  const orderMutation = useMutation({
    mutationFn: () => api.createOrderFromDiagnostic(value.id),
    onSuccess: async (order) => {
      updateLocal((current) => ({ ...current, service_order_id: order.id }));
      await queryClient.invalidateQueries({ queryKey: ["crm"] });
      void navigate(`/parts-catalog?order_id=${order.id}`);
    },
  });
  const uploadPhoto = (file?: File) => {
    if (file) photoMutation.mutate(file);
    setPhotoSourceOpen(false);
  };
  const savePdf = (blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `apex-diagnostic-${value.id}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  };
  const pdfMutation = useMutation({
    mutationFn: () => api.diagnosticPdf(value.id),
    onSuccess: (blob) => {
      savePdf(blob);
      setExportOpen(false);
    },
  });
  const imageMutation = useMutation({
    mutationFn: (share: boolean) => exportDiagnosticImage(value, share),
    onSuccess: () => setExportOpen(false),
  });
  const grouped = useMemo(
    () =>
      Object.fromEntries(
        sections.map(([key]) => [
          key,
          value.items.filter((item) => item.section_key === key),
        ]),
      ),
    [value.items],
  );
  const counts = useMemo(() => summarize(value.items), [value.items]);
  const filteredItems = statusFilter ? value.items.filter((item) => worstStatus(item) === statusFilter) : [];
  const checked = value.items.filter(isChecked).length;
  const complete = () =>
    cardMutation.mutate({
      mileage: value.mileage,
      notes: value.notes,
      status: value.status === "completed" ? "draft" : "completed",
    });
  const patchItem = (item: DiagnosticItem, input: DiagnosticItemInput) => {
    updateLocal((current) => ({
      ...current,
      items: current.items.map((old) =>
        old.item_key === item.item_key ? { ...old, ...input } : old,
      ),
    }));
    itemMutation.mutate({ key: item.item_key, input });
  };

  return (
    <article className="diagnostic-print grid gap-3">
      <header className="grid gap-2 print:hidden sm:flex sm:items-center">
        <div className="min-w-0 sm:flex-1 [&>p:last-child]:hidden">
          <p className="text-xl font-black tracking-tight"><span className="text-white">{organizationName}</span> <span className="ml-2 text-xs font-bold text-muted">Диагностика №{value.id}</span></p>
          <p className="text-xl font-black tracking-tight"><span className="text-white">APEX</span> <span className="text-apex">AUTO</span> <span className="ml-2 text-xs font-bold text-muted">ДИАГНОСТИКА №{value.id}</span></p>
        </div>
        <div className="grid min-w-0 grid-cols-[44px_44px_minmax(0,1fr)] gap-2 sm:grid-cols-[44px_44px_130px]">
          <Button className="size-11 min-h-0 border border-line bg-panel p-0 hover:border-apex/50 hover:bg-panel-soft" variant="secondary" onClick={() => setExportOpen((current) => !current)} disabled={pdfMutation.isPending || imageMutation.isPending} aria-label="Сохранить" title="Сохранить">
            <Save className="shrink-0" size={21} />
          </Button>
          <Button className="size-11 min-h-0 border border-line bg-panel p-0 hover:border-apex/50 hover:bg-panel-soft" variant="secondary" onClick={() => imageMutation.mutate(true)} disabled={imageMutation.isPending} aria-label="Отправить" title="Отправить">
            <Share2 className="shrink-0" size={21} />
          </Button>
          <Button className={value.status === "completed" ? "min-w-0 whitespace-nowrap border border-line bg-panel px-2 text-xs text-white hover:border-apex/50 hover:bg-panel-soft sm:text-sm" : "min-w-0 whitespace-nowrap px-2 text-xs sm:text-sm"} variant={value.status === "completed" ? "secondary" : "primary"} onClick={complete} disabled={cardMutation.isPending}>
            {value.status === "completed" ? (
              <Wrench className="shrink-0" size={17} />
            ) : (
              <CheckCircle2 className="shrink-0" size={17} />
            )}
            {value.status === "completed" ? "В работу" : "Завершить"}
          </Button>
        </div>
      </header>

      {exportOpen && (
        <Card className="grid gap-3 border-apex/40 print:hidden sm:grid-cols-2">
          <div className="sm:col-span-2">
            <h2 className="font-black">Выберите формат отчёта</h2>
            <p className="text-sm text-muted">Логотип, результаты диагностики, работы и запчасти будут добавлены автоматически.</p>
          </div>
          <Button variant="secondary" onClick={() => pdfMutation.mutate()}><FileDown size={17} />Сохранить PDF</Button>
          <Button variant="secondary" onClick={() => imageMutation.mutate(false)}><FileImage size={17} />Сохранить картинкой</Button>
        </Card>
      )}

      <Card className="grid gap-3 overflow-hidden border-l-4 border-l-apex bg-gradient-to-br from-panel to-panel-soft p-3 md:grid-cols-[1fr_auto] md:items-center">
        <div className="min-w-0">
          <h1 className="text-2xl font-black leading-tight break-normal sm:text-3xl">{value.brand} {value.model}</h1>
          <p className="truncate text-sm text-muted">
            {value.plate_number || "Без госномера"}
            {value.vin ? ` · ${value.vin}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2"><p className="font-semibold"><span className="mr-2 text-xs uppercase text-muted">Клиент</span>{customerName(value.customer_name)}</p>
          <label className="flex max-w-56 items-center gap-2 text-sm text-muted">
            <Gauge size={17} />
            <input
              className={`${inputClass} min-h-9 py-1`}
              type="number"
              min="0"
              value={value.mileage ?? ""}
              onChange={(event) =>
                updateLocal((current) => ({
                  ...current,
                  mileage: event.target.value
                    ? Number(event.target.value)
                    : null,
                }))
              }
              onBlur={() =>
                cardMutation.mutate({
                  mileage: value.mileage,
                  notes: value.notes,
                  status: value.status,
                })
              }
              placeholder="Пробег, км"
            />
          </label></div>
        </div>
        <ProgressRing checked={checked} total={value.items.length} />
      </Card>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Норма"
          value={counts.ok}
          color="text-success"
          icon={<Check />}
          active={statusFilter === "ok"}
          onClick={() => setStatusFilter((current) => current === "ok" ? null : "ok")}
        />
        <Stat
          label="Внимание"
          value={counts.attention}
          color="text-apex"
          icon={<CircleAlert />}
          active={statusFilter === "attention"}
          onClick={() => setStatusFilter((current) => current === "attention" ? null : "attention")}
        />
        <Stat
          label="Неисправно"
          value={counts.critical}
          color="text-danger"
          icon={<XCircle />}
          active={statusFilter === "critical"}
          onClick={() => setStatusFilter((current) => current === "critical" ? null : "critical")}
        />
        <Stat
          label="Не проверено"
          value={counts.unchecked}
          color="text-muted"
          icon={<span>—</span>}
          active={statusFilter === "unchecked"}
          onClick={() => setStatusFilter((current) => current === "unchecked" ? null : "unchecked")}
        />
      </div>

      {statusFilter && (
        <Card className="scroll-mt-20" id="diagnostic-status-details">
          <div className="flex items-center justify-between gap-3">
            <div><p className="text-xs font-bold uppercase tracking-wide text-muted">Выбранный статус</p><h2 className="text-xl font-black">{statusMeta[statusFilter].label}: {filteredItems.length}</h2></div>
            <Button variant="ghost" onClick={() => setStatusFilter(null)}>Скрыть</Button>
          </div>
          <div className="mt-3 grid gap-2">
            {filteredItems.map((item) => (
              <button key={item.id} type="button" onClick={() => document.getElementById(`diagnostic-${item.section_key}`)?.scrollIntoView({ behavior: "smooth", block: "start" })} className="rounded-xl bg-panel-soft p-3 text-left transition hover:bg-line">
                <strong className="block">{item.label}</strong>
                <span className="mt-1 block text-sm text-muted">{statusDescription(item)}</span>
                {(item.comment || item.recommendation) && <span className="mt-1 block text-sm">{[item.comment, item.recommendation].filter(Boolean).join(" · ")}</span>}
              </button>
            ))}
            {!filteredItems.length && <p className="rounded-xl bg-panel-soft p-4 text-sm text-muted">Пунктов с таким статусом нет.</p>}
          </div>
        </Card>
      )}

      <details className="rounded-xl border border-line bg-panel px-3 py-2 print:hidden">
        <summary className="cursor-pointer text-sm font-bold text-muted">Подсказка по заполнению</summary>
        <p className="mt-2 text-sm text-muted">
          Выберите состояние каждого узла. Для деталей подвески состояние
          указывается отдельно для левой и правой стороны.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {statusOrder.map((status) => (
            <span
              key={status}
              className={`rounded-lg border px-2.5 py-1.5 text-xs font-bold ${statusMeta[status].className}`}
            >
              {statusMeta[status].label}
            </span>
          ))}
        </div>
      </details>

      <nav className="flex gap-2 overflow-x-auto pb-1 print:hidden">
        {sections.map(([key, label]) => {
          const items = grouped[key] ?? [];
          const done = items.filter(isChecked).length;
          return (
            <button
              key={key}
              onClick={() =>
                document
                  .getElementById(`diagnostic-${key}`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
              className="min-w-36 shrink-0 rounded-xl border border-line bg-panel px-3 py-2 text-left transition hover:border-apex"
            >
              <strong className="block text-sm">{label}</strong>
              <span className="text-xs text-muted">
                {done}/{items.length}
              </span>
            </button>
          );
        })}
      </nav>

      {sections.map(([sectionKey, title]) => (
        <section
          id={`diagnostic-${sectionKey}`}
          key={sectionKey}
          className="scroll-mt-20"
        >
          <div className="mb-2 flex items-end justify-between">
            <h2 className="text-lg font-black">{title}</h2>
            <span className="text-sm text-muted">
              {(grouped[sectionKey] ?? []).filter(isChecked).length}/
              {(grouped[sectionKey] ?? []).length}
            </span>
          </div>
          <Card className="divide-y divide-line p-0">
            {(grouped[sectionKey] ?? []).map((item) => (
              <DiagnosticRow
                key={item.id}
                item={item}
                patch={(input) => patchItem(item, input)}
              />
            ))}
          </Card>
        </section>
      ))}

      <Card className="p-3">
        <h2 className="font-black">Фото диагностики</h2>
        <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {value.photos.map((photo, index) => (
            <ProtectedDiagnosticPhoto key={photo.id} id={photo.id} path={photo.url} alt={photo.caption || "Фото диагностики"} onOpen={() => setPhotoIndex(index)} />
          ))}
          <button type="button" onClick={() => setPhotoSourceOpen(true)} disabled={photoMutation.isPending} className="grid aspect-square cursor-pointer place-items-center rounded-xl border border-dashed border-line text-center text-sm text-muted transition hover:border-apex hover:text-apex disabled:opacity-50 print:hidden">
            <span>
              <Camera className="mx-auto mb-2" />
              {photoMutation.isPending ? "Загрузка…" : "Добавить фото"}
            </span>
          </button>
          <input ref={cameraInput} className="sr-only" type="file" accept="image/*" capture="environment" onChange={(event) => { uploadPhoto(event.target.files?.[0]); event.currentTarget.value = ""; }} />
          <input ref={galleryInput} className="sr-only" type="file" accept="image/*" onChange={(event) => { uploadPhoto(event.target.files?.[0]); event.currentTarget.value = ""; }} />
          <input ref={fileInput} className="sr-only" type="file" accept=".jpg,.jpeg,.png,.webp" onChange={(event) => { uploadPhoto(event.target.files?.[0]); event.currentTarget.value = ""; }} />
        </div>
      </Card>

      {photoSourceOpen && (
        <Modal title="Добавить фото" onClose={() => setPhotoSourceOpen(false)}>
          <div className="grid grid-cols-3 gap-2">
            <Button className="min-h-24 flex-col" variant="secondary" onClick={() => cameraInput.current?.click()}><Camera size={25} />Камера</Button>
            <Button className="min-h-24 flex-col" variant="secondary" onClick={() => galleryInput.current?.click()}><Images size={25} />Галерея</Button>
            <Button className="min-h-24 flex-col" variant="secondary" onClick={() => fileInput.current?.click()}><FolderOpen size={25} />Файл</Button>
          </div>
        </Modal>
      )}
      {photoIndex !== null && value.photos[photoIndex] && <DiagnosticPhotoViewer photos={value.photos} index={photoIndex} onChange={setPhotoIndex} onClose={() => setPhotoIndex(null)} />}

      <Card className="p-3">
        <label className="grid gap-2">
          <span className="font-black">Итоговый комментарий мастера</span>
          <textarea
            className={`${inputClass} min-h-20 resize-y`}
            value={value.notes ?? ""}
            onChange={(event) =>
              updateLocal((current) => ({
                ...current,
                notes: event.target.value,
              }))
            }
            onBlur={() =>
              cardMutation.mutate({
                mileage: value.mileage,
                notes: value.notes,
                status: value.status,
              })
            }
            placeholder="Общее состояние автомобиля и приоритет работ"
          />
        </label>
      </Card>

      <Card className="diagnostic-summary p-3">
        <h2 className="text-lg font-black">Рекомендованные работы</h2>
        <div className="mt-2 grid gap-1.5">
          {value.items
            .filter(
              (item) =>
                item.recommendation ||
                item.status === "critical" ||
                item.status === "attention" ||
                item.left_status === "critical" ||
                item.right_status === "critical",
            )
            .map((item) => (
              <div
                key={item.id}
                className="flex flex-wrap items-center gap-2 rounded-xl bg-panel-soft px-3 py-2"
              >
                <span
                  className={`size-2 rounded-full ${hasCritical(item) ? "bg-danger" : "bg-apex"}`}
                />
                <strong className="min-w-0 flex-1">
                  {item.recommendation || item.label}
                </strong>
                {item.estimated_cost != null && (
                  <span className="font-bold text-apex">
                    {money(item.estimated_cost)}
                  </span>
                )}
              </div>
            ))}
          {!value.items.some(
            (item) => item.recommendation || hasIssue(item),
          ) && <p className="text-muted">Проблем и рекомендаций пока нет.</p>}
        </div>
        <div className="mt-3 grid gap-2 border-t border-line pt-3 sm:grid-cols-[1fr_auto] sm:items-center">
          <div>
            <p className="font-bold">Смета и заказ-наряд</p>
            <p className="text-sm text-muted">Работы будут перенесены автоматически, запчасти — без артикула со статусом «Требуется подбор».</p>
          </div>
          {value.service_order_id ? (
            <Button variant="secondary" onClick={() => orderMutation.mutate()} disabled={orderMutation.isPending}><ClipboardCheck size={17} />{orderMutation.isPending ? "Обновляю заказ…" : `Подобрать запчасти · заказ №${value.service_order_id}`}</Button>
          ) : (
            <Button onClick={() => orderMutation.mutate()} disabled={orderMutation.isPending}><ClipboardCheck size={17} />{orderMutation.isPending ? "Создаю…" : "Создать заказ-наряд"}</Button>
          )}
          {orderMutation.error && <p className="text-sm text-danger sm:col-span-2">{orderMutation.error instanceof Error ? orderMutation.error.message : "Не удалось создать заказ-наряд"}</p>}
        </div>
      </Card>

      <Button className="min-h-14 text-base print:hidden" onClick={complete} disabled={cardMutation.isPending}>
        {value.status === "completed" ? <Wrench size={19} /> : <Check size={19} />}
        {value.status === "completed" ? "Вернуть диагностику в работу" : "Завершить диагностику"}
      </Button>
    </article>
  );
}

function DiagnosticRow({
  item,
  patch,
}: {
  item: DiagnosticItem;
  patch: (input: DiagnosticItemInput) => void;
}) {
  const sided = item.left_status !== null || item.right_status !== null;
  const issue = hasIssue(item);
  const [expanded, setExpanded] = useState(false);
  const status = worstStatus(item);
  return (
    <div className={`grid border-l-4 ${hasCritical(item) ? "border-l-danger bg-danger/5" : issue ? "border-l-apex bg-apex/5" : status === "ok" ? "border-l-success" : "border-l-transparent"}`}>
      <button type="button" onClick={() => setExpanded((current) => !current)} className="flex min-h-14 min-w-0 items-center gap-2 px-3 py-2 text-left">
        <strong className="min-w-0 flex-1 break-words text-sm sm:text-base">{item.label}</strong>
        <span className={`shrink-0 rounded-lg border px-2 py-1 text-[11px] font-bold ${statusMeta[status].className}`}>{statusMeta[status].label}</span>
        {expanded ? <ChevronDown className="shrink-0 text-muted" size={19} /> : <ChevronRight className="shrink-0 text-muted" size={19} />}
      </button>
      {expanded && <div className="grid gap-2 border-t border-line px-3 pb-3 pt-2">
        {sided ? (
          <div className="grid grid-cols-2 gap-2 print:hidden">
            <StatusSelect
              label="Левая сторона"
              value={item.left_status}
              onChange={(status) => patch({ left_status: status })}
            />
            <StatusSelect
              label="Правая сторона"
              value={item.right_status}
              onChange={(status) => patch({ right_status: status })}
            />
          </div>
        ) : (
          <div className="w-full print:hidden">
            <StatusSelect
              label="Состояние"
              value={item.status}
              onChange={(status) => patch({ status })}
            />
          </div>
        )}
        <span className={`hidden rounded-lg border px-2 py-1 text-xs font-bold print:inline ${statusMeta[status].className}`}>{statusMeta[status].label}</span>
      {issue && (
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_130px]">
          <input
            className={inputClass}
            defaultValue={item.comment ?? ""}
            onBlur={(event) => patch({ comment: event.target.value })}
            placeholder="Что обнаружено"
          />
          <input
            className={inputClass}
            defaultValue={item.recommendation ?? ""}
            onBlur={(event) => patch({ recommendation: event.target.value })}
            placeholder="Рекомендованная работа"
          />
          <input
            className={inputClass}
            type="number"
            min="0"
            defaultValue={item.estimated_cost ?? ""}
            onBlur={(event) =>
              patch({
                estimated_cost: event.target.value
                  ? Number(event.target.value)
                  : null,
              })
            }
            placeholder="Стоимость"
          />
        </div>
      )}
      </div>}
    </div>
  );
}

function StatusSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: DiagnosticStatus | null;
  onChange: (status: DiagnosticStatus) => void;
}) {
  const status = value ?? "unchecked";
  return (
    <label className="grid min-w-0 gap-1">
      <span className="text-[11px] font-semibold text-muted">{label}</span>
      <select
        aria-label={label}
        value={status}
        onChange={(event) => onChange(event.target.value as DiagnosticStatus)}
        className={`min-h-9 min-w-0 rounded-lg border px-2 text-sm font-bold outline-none focus:ring-2 focus:ring-apex/30 ${statusMeta[status].className}`}
      >
        {statusOrder.map((option) => (
          <option key={option} value={option} className="bg-panel text-white">
            {statusMeta[option].label}
          </option>
        ))}
      </select>
    </label>
  );
}
function ProgressRing({ checked, total }: { checked: number; total: number }) {
  const percent = total ? Math.round((checked / total) * 100) : 0;
  return (
    <div
      className="relative grid size-16 shrink-0 place-items-center rounded-full"
      aria-label={`Проверено ${checked} из ${total}: ${percent}%`}
      style={{ background: `conic-gradient(#ffd600 ${percent}%, #26313c 0)` }}
    >
      <div className="grid size-11 place-items-center rounded-full bg-panel text-center">
        <span>
          <strong className="block text-sm leading-none">{percent}%</strong>
          <small className="block text-[8px] leading-none text-muted">проверено</small>
        </span>
      </div>
    </div>
  );
}
function Stat({
  label,
  value,
  color,
  icon,
  active,
  onClick,
}: {
  label: string;
  value: number;
  color: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={`flex min-w-0 items-center gap-2 rounded-xl border bg-gradient-to-br from-panel to-panel-soft p-2 text-left shadow-card transition hover:border-apex/60 ${active ? "border-apex ring-2 ring-apex/20" : "border-line"}`}>
      <span className="flex min-w-0 items-center gap-2">
        <span className={`${color} [&>svg]:size-5`}>{icon}</span>
        <small className="truncate text-muted">{label}</small>
      </span>
      <strong className={`ml-auto block text-2xl ${color}`}>{value}</strong>
    </button>
  );
}
function statusDescription(item: DiagnosticItem) {
  if (item.left_status !== null || item.right_status !== null) {
    return `Левая: ${statusMeta[item.left_status ?? "unchecked"].label} · Правая: ${statusMeta[item.right_status ?? "unchecked"].label}`;
  }
  return statusMeta[item.status].label;
}
function isChecked(item: DiagnosticItem) {
  return (
    item.status !== "unchecked" ||
    (item.left_status != null && item.left_status !== "unchecked") ||
    (item.right_status != null && item.right_status !== "unchecked")
  );
}
function hasCritical(item: DiagnosticItem) {
  return (
    item.status === "critical" ||
    item.left_status === "critical" ||
    item.right_status === "critical"
  );
}
function hasIssue(item: DiagnosticItem) {
  return (
    hasCritical(item) ||
    item.status === "attention" ||
    item.left_status === "attention" ||
    item.right_status === "attention"
  );
}
function worstStatus(item: DiagnosticItem): DiagnosticStatus {
  const values = [item.status, item.left_status, item.right_status].filter(
    Boolean,
  ) as DiagnosticStatus[];
  return values.includes("critical")
    ? "critical"
    : values.includes("attention")
      ? "attention"
      : values.includes("ok")
        ? "ok"
        : "unchecked";
}
function summarize(items: DiagnosticItem[]) {
  return items.reduce(
    (result, item) => {
      result[worstStatus(item)] += 1;
      return result;
    },
    { unchecked: 0, ok: 0, attention: 0, critical: 0 },
  );
}
