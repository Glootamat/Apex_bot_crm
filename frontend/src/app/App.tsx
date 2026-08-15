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
const CarHistoryPage = lazy(() => import("../pages/CarHistoryPage").then((module) => ({ default: module.CarHistoryPage })));
const FinancePage = lazy(() => import("../pages/FinancePage").then((module) => ({ default: module.FinancePage })));
const SearchPage = lazy(() => import("../pages/SearchPage").then((module) => ({ default: module.SearchPage })));
const TrashPage = lazy(() => import("../pages/TrashPage").then((module) => ({ default: module.TrashPage })));
const DiagnosticsIndexPage = lazy(() => import("../pages/DiagnosticsPage").then((module) => ({ default: module.DiagnosticsIndexPage })));
const DiagnosticPage = lazy(() => import("../pages/DiagnosticsPage").then((module) => ({ default: module.DiagnosticPage })));
const NotFoundPage = lazy(() => import("../pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));
const SettingsPage = lazy(() => import("../pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const OwnerPanelPage = lazy(() => import("../pages/OwnerPanelPage").then((module) => ({ default: module.OwnerPanelPage })));
const PartsCatalogPage = lazy(() => import("../pages/PartsCatalogPage").then((module) => ({ default: module.PartsCatalogPage })));
const LaborStandardsPage = lazy(() => import("../pages/LaborStandardsPage").then((module) => ({ default: module.LaborStandardsPage })));

const suspense = (node: React.ReactNode) => <Suspense fallback={<Spinner />}>{node}</Suspense>;
const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/", element: <AppShell />, errorElement: suspense(<NotFoundPage />), children: [
    { index: true, element: suspense(<DashboardPage />) },
    { path: "calendar", element: suspense(<CalendarPage />) },
    { path: "orders", element: suspense(<OrdersPage />) },
    { path: "customers", element: suspense(<CustomersPage />) },
    { path: "cars", element: suspense(<CarsPage />) },
    { path: "cars/:carId/history", element: suspense(<CarHistoryPage />) },
    { path: "finance", element: suspense(<FinancePage />) },
    { path: "search", element: suspense(<SearchPage />) },
    { path: "trash", element: suspense(<TrashPage />) },
    { path: "settings", element: suspense(<SettingsPage />) },
    { path: "owner", element: suspense(<OwnerPanelPage />) },
    { path: "parts-catalog", element: suspense(<PartsCatalogPage />) },
    { path: "labor-standards", element: suspense(<LaborStandardsPage />) },
    { path: "diagnostics", element: suspense(<DiagnosticsIndexPage />) },
    { path: "diagnostics/start", element: suspense(<DiagnosticPage />) },
    { path: "diagnostics/:diagnosticId", element: suspense(<DiagnosticPage />) },
    { path: "*", element: suspense(<NotFoundPage />) },
  ]},
]);

export function App() { return <RouterProvider router={router} />; }
