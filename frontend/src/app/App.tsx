import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "./AppShell";
import { LoginPage } from "../features/auth/LoginPage";
import { Spinner } from "../components/ui";

const DashboardPage = lazy(() => import("../pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const CalendarPage = lazy(() => import("../pages/CalendarPage").then((module) => ({ default: module.CalendarPage })));
const OrdersPage = lazy(() => import("../pages/OrdersPage").then((module) => ({ default: module.OrdersPage })));
const CustomersPage = lazy(() => import("../pages/CustomersPage").then((module) => ({ default: module.CustomersPage })));
const CarsPage = lazy(() => import("../pages/CarsPage").then((module) => ({ default: module.CarsPage })));
const FinancePage = lazy(() => import("../pages/FinancePage").then((module) => ({ default: module.FinancePage })));
const SearchPage = lazy(() => import("../pages/SearchPage").then((module) => ({ default: module.SearchPage })));
const NotFoundPage = lazy(() => import("../pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));

const suspense = (node: React.ReactNode) => <Suspense fallback={<Spinner />}>{node}</Suspense>;
const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/", element: <AppShell />, errorElement: suspense(<NotFoundPage />), children: [
    { index: true, element: suspense(<DashboardPage />) },
    { path: "calendar", element: suspense(<CalendarPage />) },
    { path: "orders", element: suspense(<OrdersPage />) },
    { path: "customers", element: suspense(<CustomersPage />) },
    { path: "cars", element: suspense(<CarsPage />) },
    { path: "finance", element: suspense(<FinancePage />) },
    { path: "search", element: suspense(<SearchPage />) },
    { path: "*", element: suspense(<NotFoundPage />) },
  ]},
]);

export function App() { return <RouterProvider router={router} />; }
