import { lazy, Suspense } from "react";
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
import SessionGate from "./components/SessionGate";
const PredictionsPage = lazy(() => import("./pages/PredictionsPage"));
import {
    Navigate,
    Route,
    Routes,
} from "react-router-dom";

import "./App.css";

import AppLayout from "./layouts/AppLayout";
const AlarmsPage = lazy(() => import("./pages/AlarmsPage"));
const EventJournalPage = lazy(() => import("./pages/EventJournalPage"));
const ImportsPage = lazy(() => import("./pages/ImportsPage"));
const MapPage = lazy(() => import("./pages/MapPage"));
const ObjectsPage = lazy(() => import("./pages/ObjectsPage"));
const RequestsPage = lazy(() => import("./pages/RequestsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));


function App() {
    return (
        <SessionGate><Suspense fallback={<div className="operations-page">Загрузка раздела…</div>}><Routes>
            <Route element={<AppLayout />}>
                <Route path="/predictions" element={<PredictionsPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route
                    path="/"
                    element={<MapPage />}
                />

                <Route
                    path="/objects"
                    element={<ObjectsPage />}
                />

                <Route
                    path="/alarms"
                    element={<AlarmsPage />}
                />

                <Route
                    path="/events"
                    element={<EventJournalPage />}
                />

                <Route
                    path="/imports"
                    element={<ImportsPage />}
                />

                <Route
                    path="/requests"
                    element={<RequestsPage />}
                />

                <Route
                    path="/settings"
                    element={<SettingsPage />}
                />

                <Route
                    path="*"
                    element={
                        <Navigate
                            to="/"
                            replace
                        />
                    }
                />
            </Route>
        </Routes></Suspense></SessionGate>
    );
}


export default App;
