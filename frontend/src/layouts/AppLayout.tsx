import Notifications from "../components/Notifications";
import {
    useState,
} from "react";

import {
    AlertTriangle,
    Bell,
    ChevronLeft,
    ChevronRight,
    Database,
    List,
    Map,
    Settings,
    Upload,
} from "lucide-react";

import {
    NavLink,
    Outlet,
} from "react-router-dom";


function AppLayout() {
    const [collapsed, setCollapsed] =
        useState(false);

    return (
        <div className="app-shell">
            <aside
                className={
                    collapsed
                        ? "sidebar sidebar-collapsed"
                        : "sidebar"
                }
            >
                <div className="sidebar-header">
                    <div className="brand-mark">
                        МК
                    </div>

                    {!collapsed && (
                        <div className="brand-text">
                            <strong>
                                Москоллектор
                            </strong>
                            <span>
                                Мониторинг
                            </span>
                        </div>
                    )}
                </div>

                <nav className="navigation">
                    <NavLink
                        to="/"
                        end
                        title="Карта"
                        className={({ isActive }) =>
                            isActive
                                ? "nav-item active"
                                : "nav-item"
                        }
                    >
                        <Map size={21} />
                        {!collapsed && (
                            <span>Карта</span>
                        )}
                    </NavLink>

                    <NavLink
                        to="/objects"
                        title="Объекты"
                        className={({ isActive }) =>
                            isActive
                                ? "nav-item active"
                                : "nav-item"
                        }
                    >
                        <Database size={21} />
                        {!collapsed && (
                            <span>Объекты</span>
                        )}
                    </NavLink>

                    <NavLink
                        to="/alarms"
                        title="Тревоги"
                        className={({ isActive }) =>
                            isActive
                                ? "nav-item active"
                                : "nav-item"
                        }
                    >
                        <AlertTriangle size={21} />
                        {!collapsed && (
                            <span>Тревоги</span>
                        )}
                    </NavLink>

                    <NavLink
                        to="/events"
                        title="Журнал событий"
                        className={({ isActive }) =>
                            isActive
                                ? "nav-item active"
                                : "nav-item"
                        }
                    >
                        <List size={21} />
                        {!collapsed && (
                            <span>
                                Журнал событий
                            </span>
                        )}
                    </NavLink>

                    <NavLink
                        to="/imports"
                        title="Импорт данных"
                        className={({ isActive }) =>
                            isActive
                                ? "nav-item active"
                                : "nav-item"
                        }
                    >
                        <Upload size={21} />
                        {!collapsed && (
                            <span>
                                Импорт данных
                            </span>
                        )}
                    </NavLink>

                    <NavLink
                        to="/requests"
                        title="Заявки"
                        className={({ isActive }) =>
                            isActive
                                ? "nav-item active"
                                : "nav-item"
                        }
                    >
                        <Bell size={21} />
                        {!collapsed && (
                            <span>Заявки</span>
                        )}
                    </NavLink>
                    <NavLink to="/predictions" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"} title="Прогнозы"><List size={21} />{!collapsed && <span>Прогнозы</span>}</NavLink>
                    <NavLink to="/reports" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"} title="Отчёты"><List size={21} />{!collapsed && <span>Отчёты</span>}</NavLink>
                </nav>

                <div className="sidebar-footer">
                    <button
                        type="button"
                        className="nav-item sidebar-toggle"
                        onClick={() =>
                            setCollapsed(
                                (value) => !value,
                            )
                        }
                        title={
                            collapsed
                                ? "Развернуть меню"
                                : "Свернуть меню"
                        }
                    >
                        {collapsed ? (
                            <ChevronRight size={21} />
                        ) : (
                            <ChevronLeft size={21} />
                        )}

                        {!collapsed && (
                            <span>
                                Свернуть меню
                            </span>
                        )}
                    </button>

                    <div
                        className="nav-item settings-item"
                        title="Права и учётные записи управляются администратором"
                    >
                        <Settings size={21} />
                        {!collapsed && (
                            <span>Управление доступом</span>
                        )}
                    </div>
                </div>
            </aside>

            <main className="app-workspace">
                <Notifications /><Outlet />
            </main>
        </div>
    );
}


export default AppLayout;
