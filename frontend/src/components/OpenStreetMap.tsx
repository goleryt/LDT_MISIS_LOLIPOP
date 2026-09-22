import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as LeafletMap } from "leaflet";
import {
    CircleMarker,
    MapContainer,
    ScaleControl,
    TileLayer,
    Tooltip,
    useMap,
} from "react-leaflet";
import { LocateFixed, Minus, Plus } from "lucide-react";

import type { MapObject, MapObjectStatus } from "../types/map";
import "leaflet/dist/leaflet.css";


interface OpenStreetMapProps {
    objects: MapObject[];
    selectedObject: MapObject | null;
    onSelectObject: (object: MapObject) => void;
    onShowScheme: () => void;
}

const MOSCOW_CENTER: [number, number] = [55.7558, 37.6176];
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL
    ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const STATUS_COLORS: Record<MapObjectStatus, string> = {
    normal: "#16875c",
    alarm: "#d83b3b",
    unknown: "#70879a",
};

const STATUS_LABELS: Record<MapObjectStatus, string> = {
    normal: "Нет тревог",
    alarm: "Тревога",
    unknown: "Нет данных",
};


function validLocation(object: MapObject): boolean {
    const [longitude, latitude] = object.geometry.coordinates;
    return Number.isFinite(longitude)
        && Number.isFinite(latitude)
        && Math.abs(longitude) <= 180
        && Math.abs(latitude) <= 90;
}


function MapViewController({
    selectedObject,
    resetSignal,
    objects,
}: {
    selectedObject: MapObject | null;
    resetSignal: number;
    objects: MapObject[];
}) {
    const map = useMap();
    const previousReset = useRef(resetSignal);

    useEffect(() => {
        const observer = new ResizeObserver(() => {
            map.invalidateSize({ animate: false, pan: false });
        });

        observer.observe(map.getContainer());
        return () => observer.disconnect();
    }, [map]);

    useEffect(() => {
        if (!selectedObject || !validLocation(selectedObject)) {
            return;
        }

        const [longitude, latitude] = selectedObject.geometry.coordinates;
        map.setView([latitude, longitude], Math.max(map.getZoom(), 12), {
            animate: false,
        });
    }, [map, selectedObject?.object_id]);

    useEffect(() => {
        if (previousReset.current === resetSignal) {
            return;
        }
        previousReset.current = resetSignal;

        if (objects.length === 0) {
            map.setView(MOSCOW_CENTER, 10, { animate: false });
            return;
        }

        const bounds = objects.map((object) => {
            const [longitude, latitude] = object.geometry.coordinates;
            return [latitude, longitude] as [number, number];
        });
        map.fitBounds(bounds, {
            padding: [44, 44],
            maxZoom: 12,
            animate: false,
        });
    }, [map, objects, resetSignal]);

    return null;
}


function OpenStreetMap({
    objects,
    selectedObject,
    onSelectObject,
    onShowScheme,
}: OpenStreetMapProps) {
    const mapRef = useRef<LeafletMap | null>(null);
    const tileErrors = useRef(0);
    const [tilesUnavailable, setTilesUnavailable] = useState(false);
    const [resetSignal, setResetSignal] = useState(0);

    const visibleObjects = useMemo(
        () => objects.filter(validLocation),
        [objects],
    );

    return (
        <div className="osm-map-shell">
            <MapContainer
                ref={mapRef}
                center={MOSCOW_CENTER}
                zoom={10}
                minZoom={8}
                maxZoom={18}
                maxBounds={[[54.2, 35.1], [56.95, 40.3]]}
                maxBoundsViscosity={1}
                zoomControl={false}
                preferCanvas
                className="main-map osm-map"
                aria-label="Интерактивная карта Москвы"
            >
                <TileLayer
                    url={TILE_URL}
                    maxZoom={18}
                    attribution={'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>'}
                    eventHandlers={{
                        tileload: () => {
                            tileErrors.current = 0;
                            setTilesUnavailable(false);
                        },
                        tileerror: () => {
                            tileErrors.current += 1;
                            if (tileErrors.current >= 3) {
                                setTilesUnavailable(true);
                            }
                        },
                    }}
                />
                <MapViewController
                    selectedObject={selectedObject}
                    resetSignal={resetSignal}
                    objects={visibleObjects}
                />
                <ScaleControl position="bottomleft" imperial={false} />

                {visibleObjects.map((object) => {
                    const [longitude, latitude] = object.geometry.coordinates;
                    const selected = selectedObject?.object_id === object.object_id;
                    const color = STATUS_COLORS[object.status];

                    return (
                        <CircleMarker
                            key={object.object_id}
                            center={[latitude, longitude]}
                            radius={selected ? 12 : object.status === "alarm" ? 9 : 7}
                            pathOptions={{
                                color: "#ffffff",
                                weight: selected ? 4 : 3,
                                fillColor: color,
                                fillOpacity: 1,
                            }}
                            eventHandlers={{ click: () => onSelectObject(object) }}
                        >
                            <Tooltip direction="top" offset={[0, -8]}>
                                <strong>{object.name ?? `Объект ${object.object_id}`}</strong>
                                <span className="osm-tooltip-status">
                                    {STATUS_LABELS[object.status]}
                                    {object.status === "alarm" && ` · ${object.alarm_sensor_count} тревожных датчиков`}
                                </span>
                                {object.geometry_is_synthetic && (
                                    <span className="osm-tooltip-note">Условная точка, не адрес объекта</span>
                                )}
                            </Tooltip>
                        </CircleMarker>
                    );
                })}
            </MapContainer>

            <div className="osm-map-controls" aria-label="Управление картой">
                <button type="button" aria-label="Приблизить карту" title="Приблизить" onClick={() => mapRef.current?.zoomIn()}>
                    <Plus size={19} />
                </button>
                <button type="button" aria-label="Отдалить карту" title="Отдалить" onClick={() => mapRef.current?.zoomOut()}>
                    <Minus size={19} />
                </button>
                <button type="button" aria-label="Показать все объекты" title="Показать все объекты" onClick={() => setResetSignal((current) => current + 1)}>
                    <LocateFixed size={18} />
                </button>
            </div>

            {tilesUnavailable && (
                <div className="osm-tile-error" role="status">
                    <strong>Картографическая подложка недоступна</strong>
                    <span>Сеть или сервер карт не отвечает.</span>
                    <button type="button" onClick={onShowScheme}>Открыть схему Москвы</button>
                </div>
            )}
        </div>
    );
}

export default OpenStreetMap;
