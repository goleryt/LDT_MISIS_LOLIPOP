import {
    Navigate,
    Route,
    Routes,
} from "react-router-dom";

import "./App.css";

import AppLayout from "./layouts/AppLayout";
import AlarmsPage from "./pages/AlarmsPage";
import EventJournalPage from "./pages/EventJournalPage";
import ImportsPage from "./pages/ImportsPage";
import MapPage from "./pages/MapPage";
import ObjectsPage from "./pages/ObjectsPage";
import RequestsPage from "./pages/RequestsPage";


function App() {
    return (
        <Routes>
            <Route element={<AppLayout />}>
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
                    path="*"
                    element={
                        <Navigate
                            to="/"
                            replace
                        />
                    }
                />
            </Route>
        </Routes>
    );
}


export default App;
