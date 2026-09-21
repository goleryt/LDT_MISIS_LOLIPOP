import {
    Navigate,
    Route,
    Routes,
} from "react-router-dom";

import AppLayout from "./layouts/AppLayout";
import ImportsPage from "./pages/ImportsPage";
import OverviewPage from "./pages/OverviewPage";

import "./App.css";


function PlaceholderPage({
    title,
}: {
    title: string;
}) {
    return (
        <div style={{ padding: "32px" }}>
            <h1>{title}</h1>
            <p>
                Раздел находится в разработке.
            </p>
        </div>
    );
}


function App() {
    return (
        <Routes>
            <Route element={<AppLayout />}>
                <Route
                    path="/"
                    element={<OverviewPage />}
                />

                <Route
                    path="/objects"
                    element={
                        <PlaceholderPage title="Объекты" />
                    }
                />

                <Route
                    path="/events"
                    element={
                        <PlaceholderPage title="Журнал событий" />
                    }
                />

                <Route
                    path="/imports"
                    element={<ImportsPage />}
                />

                <Route
                    path="/requests"
                    element={
                        <PlaceholderPage title="Заявки" />
                    }
                />

                <Route
                    path="*"
                    element={<Navigate to="/" replace />}
                />
            </Route>
        </Routes>
    );
}

export default App;