import { X } from "lucide-react";
import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export function Button({ className, variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const styles = { primary: "bg-apex text-black hover:bg-apex-bright", secondary: "bg-panel-soft text-white hover:bg-line", danger: "bg-danger/15 text-danger hover:bg-danger/25", ghost: "bg-transparent text-muted hover:bg-panel-soft hover:text-white" };
  return <button className={twMerge("inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-bold transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-apex", styles[variant], className)} {...props} />;
}

export function Card({ className, children }: PropsWithChildren<{ className?: string }>) {
  return <section className={twMerge("rounded-2xl border border-line bg-panel p-4 shadow-card", className)}>{children}</section>;
}

export function EmptyState({ children }: PropsWithChildren) {
  return <div className="rounded-2xl border border-dashed border-line px-6 py-12 text-center text-muted">{children}</div>;
}

export function Modal({ title, children, onClose }: PropsWithChildren<{ title: string; onClose: () => void }>) {
  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-5" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-labelledby="modal-title" className="max-h-[94dvh] w-full overflow-y-auto rounded-t-3xl border border-line bg-panel p-5 shadow-2xl sm:max-w-2xl sm:rounded-3xl sm:p-6">
      <header className="mb-5 flex items-center justify-between gap-4"><h2 id="modal-title" className="text-xl font-black">{title}</h2><Button variant="ghost" className="size-11 p-0" onClick={onClose} aria-label="Закрыть"><X size={20} /></Button></header>
      {children}
    </section>
  </div>;
}

export function Field({ label, children, full = false }: { label: string; children: ReactNode; full?: boolean }) {
  return <label className={full ? "grid gap-2 sm:col-span-2" : "grid gap-2"}><span className="text-sm font-semibold text-muted">{label}</span>{children}</label>;
}

export const inputClass = "min-h-12 w-full rounded-xl border border-line bg-canvas px-3 py-2.5 text-base text-white outline-none transition placeholder:text-muted/70 focus:border-apex focus:ring-2 focus:ring-apex/20";

export function Spinner({ label = "Загрузка" }: { label?: string }) {
  return <div className="flex min-h-56 items-center justify-center gap-3 text-muted" role="status"><span className="size-5 animate-spin rounded-full border-2 border-line border-t-apex" /><span>{label}</span></div>;
}
