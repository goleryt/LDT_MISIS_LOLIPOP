import {
    Minus,
    Plus,
} from "lucide-react";

import {
    useEffect,
    useMemo,
    useState,
} from "react";

import type {
    MapObject,
} from "../types/map";

import MoscowBaseMap from "./MoscowBaseMap";


interface SchematicMapProps {
    objects: MapObject[];
    selectedObject: MapObject | null;

    onSelectObject: (
        object: MapObject,
    ) => void;
}


const MIN_LONGITUDE = 37.35;
const MAX_LONGITUDE = 37.85;

const MIN_LATITUDE = 55.55;
const MAX_LATITUDE = 55.95;

const SVG_WIDTH = 1200;
const SVG_HEIGHT = 820;

const CITY_CENTER_X = 600;
const CITY_CENTER_Y = 410;

const CITY_RADIUS_X = 485;
const CITY_RADIUS_Y = 315;

interface ProjectedPoint {
    x: number;
    y: number;
}


function projectCoordinates(
    longitude: number,
    latitude: number,
): ProjectedPoint {
    /*
     * Нормализуем координаты
     * в квадрат [-1; 1].
     */

    const normalizedX =
        (
            (longitude -
                MIN_LONGITUDE) /
            (
                MAX_LONGITUDE -
                MIN_LONGITUDE
            )
        ) * 2 - 1;

    const normalizedY =
        (
            (latitude -
                MIN_LATITUDE) /
            (
                MAX_LATITUDE -
                MIN_LATITUDE
            )
        ) * 2 - 1;


    /*
     * Square-to-disc projection.
     *
     * Убирает проблему,
     * когда синтетические точки
     * оказываются в углах
     * прямоугольной области.
     */

    const diskX =
        normalizedX *
        Math.sqrt(
            Math.max(
                0,
                1 -
                (
                    normalizedY *
                    normalizedY
                ) /
                2,
            ),
        );

    const diskY =
        normalizedY *
        Math.sqrt(
            Math.max(
                0,
                1 -
                (
                    normalizedX *
                    normalizedX
                ) /
                2,
            ),
        );


    return {
        x:
            CITY_CENTER_X +
            diskX *
            CITY_RADIUS_X,

        y:
            CITY_CENTER_Y -
            diskY *
            CITY_RADIUS_Y,
    };
}




function SchematicMap({
    objects,
    selectedObject,
    onSelectObject,
}: SchematicMapProps) {
    const [zoom, setZoom] =
        useState(1);

    const [focusX, setFocusX] =
        useState(
            SVG_WIDTH / 2,
        );

    const [focusY, setFocusY] =
        useState(
            SVG_HEIGHT / 2,
        );


    const projectedObjects =
        useMemo(() => {
            return objects.map(
                (object) => {
                    const [
                        longitude,
                        latitude,
                    ] =
                        object.geometry.coordinates;

                    const point =
                        projectCoordinates(
                            longitude,
                            latitude,
                        );

                    return {
                        object,
                        x: point.x,
                        y: point.y,
                    };
                },
            );
        }, [objects]);


    useEffect(() => {
        if (!selectedObject) {
            return;
        }

        const [
            longitude,
            latitude,
        ] =
            selectedObject
                .geometry
                .coordinates;

        const point =
            projectCoordinates(
                longitude,
                latitude,
            );

        setFocusX(point.x);
        setFocusY(point.y);

        setZoom(
            (current) =>
                Math.max(
                    current,
                    2.2,
                ),
        );
    }, [
        selectedObject?.object_id,
    ]);


    function zoomIn() {
        setZoom(
            (current) =>
                Math.min(
                    current + 0.4,
                    4,
                ),
        );
    }


    function zoomOut() {
        setZoom(
            (current) =>
                Math.max(
                    current - 0.4,
                    1,
                ),
        );
    }


    function resetView() {
        setZoom(1);

        setFocusX(
            SVG_WIDTH / 2,
        );

        setFocusY(
            SVG_HEIGHT / 2,
        );
    }


    const viewWidth =
        SVG_WIDTH / zoom;

    const viewHeight =
        SVG_HEIGHT / zoom;

    const viewX = Math.max(
        0,
        Math.min(
            focusX -
            viewWidth / 2,

            SVG_WIDTH -
            viewWidth,
        ),
    );

    const viewY = Math.max(
        0,
        Math.min(
            focusY -
            viewHeight / 2,

            SVG_HEIGHT -
            viewHeight,
        ),
    );


    return (
        <div className="schematic-map">
            <svg
                className="schematic-map-svg"
                viewBox={
                    `${viewX} ${viewY} ` +
                    `${viewWidth} ${viewHeight}`
                }
                role="img"
                aria-label="Схематическая карта Москвы"
            >
                <defs>
                    <filter
                        id="point-shadow"
                        x="-50%"
                        y="-50%"
                        width="200%"
                        height="200%"
                    >
                        <feDropShadow
                            dx="0"
                            dy="2"
                            stdDeviation="3"
                            floodOpacity="0.32"
                        />
                    </filter>
                </defs>

                <rect
                    x="0"
                    y="0"
                    width={SVG_WIDTH}
                    height={SVG_HEIGHT}
                    className="schematic-map-background"
                />

                <MoscowBaseMap />

                {projectedObjects.map(
                    ({
                        object,
                        x,
                        y,
                    }) => {
                        const isSelected =
                            selectedObject?.object_id ===
                            object.object_id;

                        return (
                            <g
                                key={object.object_id}
                                className={
                                    [
                                        "schematic-object",
                                        object.status,
                                        isSelected
                                            ? "selected"
                                            : "",
                                    ]
                                        .filter(Boolean)
                                        .join(" ")
                                }
                                transform={
                                    `translate(${x} ${y})`
                                }
                                onClick={() =>
                                    onSelectObject(object)
                                }
                                role="button"
                                tabIndex={0}
                                onKeyDown={(event) => {
                                    if (
                                        event.key === "Enter" ||
                                        event.key === " "
                                    ) {
                                        event.preventDefault();

                                        onSelectObject(object);
                                    }
                                }}
                            >
                                {isSelected && (
                                    <circle
                                        r="17"
                                        className="schematic-object-pulse"
                                    />
                                )}

                                <circle
                                    r={
                                        object.status === "alarm"
                                            ? 7.5
                                            : 5.5
                                    }
                                    className={
                                        `schematic-object-point ${object.status}`
                                    }
                                    filter="url(#point-shadow)"
                                />

                                <title>
                                    {object.name ??
                                        `Объект ${object.object_id}`}
                                </title>
                            </g>
                        );
                    },
                )}
            </svg>


            <div className="schematic-map-controls">
                <button
                    type="button"
                    onClick={zoomIn}
                    aria-label="Приблизить карту"
                >
                    <Plus size={17} />
                </button>

                <button
                    type="button"
                    onClick={zoomOut}
                    aria-label="Отдалить карту"
                >
                    <Minus size={17} />
                </button>
            </div>


            <button
                type="button"
                className="schematic-reset-button"
                onClick={resetView}
            >
                Показать все
            </button>

        </div>
    );
}


export default SchematicMap;
