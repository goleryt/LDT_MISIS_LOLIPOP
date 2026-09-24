import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// Порядок стилей важен: у правил равная специфичность, побеждает последнее.
// Сначала базовые, потом App.css, и только затем тема — иначе старые
// цвета из App.css перебивают её.
import "./index.css";
import "./App.css";
import "./styles/moscow-map.css";

import App from "./App";
import { initTheme } from "./theme";

initTheme();

createRoot(
    document.getElementById("root")!,
).render(
    <StrictMode>
        <BrowserRouter>
            <App />
        </BrowserRouter>
    </StrictMode>,
);
