import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Bell, ChevronLeft, ChevronRight, Database, FileBarChart, Map, Menu, ScrollText, Settings, TrendingUp, Upload, X } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import Notifications from "../components/Notifications";
import { useMediaQuery } from "../hooks/useMediaQuery";

import "../styles/moscow-map.css";
import "../styles/ui-readability.css";
import "../styles/ui-layout.css";
import "../styles/ui-chrome.css";
import "../styles/designer-polish.css";
import "../styles/responsive-polish.css";

const NAVIGATION = [
    { to: "/", label: "Карта", icon: Map },
    { to: "/objects", label: "Объекты", icon: Database },
    { to: "/alarms", label: "Тревоги", icon: AlertTriangle },
    { to: "/events", label: "Журнал событий", icon: ScrollText },
    { to: "/imports", label: "Импорт данных", icon: Upload },
    { to: "/requests", label: "Заявки", icon: Bell },
    { to: "/predictions", label: "Прогнозы", icon: TrendingUp },
    { to: "/reports", label: "Отчёты", icon: FileBarChart },
];

export default function AppLayout() {
    const [collapsed, setCollapsed] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const isMobile = useMediaQuery("(max-width: 800px)");
    const dialog = useRef<HTMLDialogElement>(null);
    const location = useLocation();
    const showLabels = isMobile || !collapsed;

    useEffect(() => {
        const element = dialog.current;
        if (isMobile && menuOpen && element && !element.open) element.showModal();
        else if (element?.open) element.close();
    }, [isMobile, menuOpen]);
    // Close for browser Back/Forward as well as navigation link clicks.
    useEffect(() => { dialog.current?.close(); }, [location.key]);
    useEffect(() => {
        const media = window.matchMedia("(max-width: 800px)");
        const resetMenu = () => setMenuOpen(false);
        media.addEventListener("change", resetMenu);
        return () => media.removeEventListener("change", resetMenu);
    }, []);

    function closeMenu() { setMenuOpen(false); }

    const sidebar = <aside className={!isMobile && collapsed ? "sidebar sidebar-collapsed" : "sidebar"}>
        <div className="sidebar-header">
            <div className="brand-mark">МК</div>
            {showLabels && <div className="brand-text"><strong>Москоллектор</strong><span>Мониторинг</span></div>}
        </div>
        {isMobile && <button type="button" className="mobile-nav-close" onClick={closeMenu} aria-label="Закрыть меню"><X size={22} /></button>}
        <nav className="navigation" id="main-navigation">
            {NAVIGATION.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} title={label}
                onClick={closeMenu} className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
                <Icon size={21} />{showLabels && <span>{label}</span>}
            </NavLink>)}
        </nav>
        <div className="sidebar-footer">
            {!isMobile && <button type="button" className="nav-item sidebar-toggle" aria-controls="main-navigation"
                aria-expanded={!collapsed} onClick={() => setCollapsed(value => !value)}
                title={collapsed ? "Развернуть меню" : "Свернуть меню"}>
                {collapsed ? <ChevronRight size={21} /> : <ChevronLeft size={21} />}
                {!collapsed && <span>Свернуть меню</span>}
            </button>}
            <NavLink to="/settings" title="Настройки" onClick={closeMenu}
                className={({ isActive }) => isActive ? "nav-item settings-item active" : "nav-item settings-item"}>
                <Settings size={21} />{showLabels && <span>Настройки</span>}
            </NavLink>
        </div>
    </aside>;

    return <div className="app-shell">
        {isMobile ? <dialog ref={dialog} className="mobile-nav-dialog" aria-label="Главное меню"
            onKeyDown={event => {
                if (event.key !== "Tab") return;
                const items = event.currentTarget.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]");
                const first = items[0], last = items[items.length - 1];
                const active = document.activeElement;
                if (event.shiftKey && (active === first || active === event.currentTarget)) {
                    event.preventDefault(); last?.focus();
                } else if (!event.shiftKey && (active === last || active === event.currentTarget)) {
                    event.preventDefault(); first?.focus();
                }
            }}
            onClose={closeMenu} onClick={event => {
                const box = event.currentTarget.getBoundingClientRect();
                if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeMenu();
            }}>{sidebar}</dialog> : sidebar}
        <main className="app-workspace">
            {isMobile && <header className="mobile-topbar">
                <button type="button" onClick={() => setMenuOpen(true)} aria-label="Открыть меню"
                    aria-haspopup="dialog" aria-controls="main-navigation" aria-expanded={menuOpen}>
                    <Menu size={22} /><span>Меню</span>
                </button>
                <strong>Москоллектор</strong>
            </header>}
            <Notifications /><Outlet />
        </main>
    </div>;
}
