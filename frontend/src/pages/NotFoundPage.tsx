import { Link } from "react-router-dom";

export function NotFoundPage() { return <div className="grid min-h-[60dvh] place-items-center text-center"><div><p className="text-7xl font-black text-apex">404</p><h1 className="mt-3 text-2xl font-black">Страница не найдена</h1><p className="mt-2 text-muted">Вернитесь на главную страницу CRM.</p><Link className="mt-5 inline-flex min-h-11 items-center rounded-xl bg-apex px-4 py-2 text-sm font-bold text-black hover:bg-apex-bright" to="/">На главную</Link></div></div>; }
