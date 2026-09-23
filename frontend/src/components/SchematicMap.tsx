import {
    Minus,
    Plus,
} from "lucide-react";

import {
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import type {
    PointerEvent as ReactPointerEvent,
    WheelEvent as ReactWheelEvent,
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


interface ProjectedPoint {
    x: number;
    y: number;
}


interface DragState {
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startFocusX: number;
    startFocusY: number;
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

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const FOCUS_ZOOM = 2.2;


function clamp(
    value: number,
    min: number,
    max: number,
): number {
    return Math.min(
        Math.max(value, min),
        max,
    );
}


function getViewSize(
    zoom: number,
) {
    return {
        width: SVG_WIDTH / zoom,
        height: SVG_HEIGHT / zoom,
    };
}


function clampFocus(
    x: number,
    y: number,
    zoom: number,
) {
    const {
        width,
        height,
    } = getViewSize(zoom);

    return {
        x: clamp(
            x,
            width / 2,
            SVG_WIDTH - width / 2,
        ),
        y: clamp(
            y,
            height / 2,
            SVG_HEIGHT - height / 2,
        ),
    };
}


function projectCoordinates(
    longitude: number,
    latitude: number,
): ProjectedPoint {
    const normalizedX =
        (
            (longitude - MIN_LONGITUDE) /
            (MAX_LONGITUDE - MIN_LONGITUDE)
        ) * 2 - 1;

    const normalizedY =
        (
            (latitude - MIN_LATITUDE) /
            (MAX_LATITUDE - MIN_LATITUDE)
        ) * 2 - 1;

    /*
     * Синтетические координаты приходят из прямоугольной области.
     * Проекция square-to-disc делает распределение визуально более
     * естественным и не забивает углы схемы.
     */
    const diskX =
        normalizedX *
        Math.sqrt(
            Math.max(
                0,
                1 - normalizedY * normalizedY / 2,
            ),
        );

    const diskY =
        normalizedY *
        Math.sqrt(
            Math.max(
                0,
                1 - normalizedX * normalizedX / 2,
            ),
        );

    return {
        x:
            CITY_CENTER_X +
            diskX * CITY_RADIUS_X,
        y:
            CITY_CENTER_Y -
            diskY * CITY_RADIUS_Y,
    };
}


function SchematicMap({
    objects,
    selectedObject,
    onSelectObject,
}: SchematicMapProps) {
    const [zoom, setZoom] =
        useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 600px)").matches ? 1.8 : MIN_ZOOM);

    const [focusX, setFocusX] =
        useState(SVG_WIDTH / 2);

    const [focusY, setFocusY] =
        useState(SVG_HEIGHT / 2);

    const [isDragging, setIsDragging] =
        useState(false);

    const [hoveredObject, setHoveredObject] =
        useState<MapObject | null>(null);

    const svgRef =
        useRef<SVGSVGElement | null>(null);

    const dragStateRef =
        useRef<DragState>({
            pointerId: -1,
            startClientX: 0,
            startClientY: 0,
            startFocusX: 0,
            startFocusY: 0,
        });


    const projectedObjects =
        useMemo(() => {
            return objects.map(
                (object) => {
                    const [
                        longitude,
                        latitude,
                    ] = object.geometry.coordinates;

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
        ] = selectedObject.geometry.coordinates;

        const point =
            projectCoordinates(
                longitude,
                latitude,
            );

        const nextZoom =
            Math.max(
                zoom,
                FOCUS_ZOOM,
            );

        const nextFocus =
            clampFocus(
                point.x,
                point.y,
                nextZoom,
            );

        setZoom(nextZoom);
        setFocusX(nextFocus.x);
        setFocusY(nextFocus.y);
        setHoveredObject(null);
        // zoom intentionally omitted: selecting a new object should
        // preserve a stronger zoom chosen by the dispatcher.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedObject?.object_id]);


    function changeZoom(
        nextZoomValue: number,
    ) {
        const nextZoom =
            clamp(
                nextZoomValue,
                MIN_ZOOM,
                MAX_ZOOM,
            );

        const nextFocus =
            clampFocus(
                focusX,
                focusY,
                nextZoom,
            );

        setZoom(nextZoom);
        setFocusX(nextFocus.x);
        setFocusY(nextFocus.y);
        setHoveredObject(null);
    }


    function zoomIn() {
        changeZoom(zoom + 0.4);
    }


    function zoomOut() {
        changeZoom(zoom - 0.4);
    }


    function resetView() {
        setZoom(MIN_ZOOM);
        setFocusX(SVG_WIDTH / 2);
        setFocusY(SVG_HEIGHT / 2);
        setHoveredObject(null);
    }


    function handlePointerDown(
        event:
            ReactPointerEvent<SVGSVGElement>,
    ) {
        if (
            event.pointerType === "mouse" &&
            event.button !== 0
        ) {
            return;
        }

        const target =
            event.target as Element;

        if (
            target.closest(
                ".schematic-object",
            )
        ) {
            return;
        }

        event.currentTarget
            .setPointerCapture(
                event.pointerId,
            );

        dragStateRef.current = {
            pointerId: event.pointerId,
            startClientX: event.clientX,
            startClientY: event.clientY,
            startFocusX: focusX,
            startFocusY: focusY,
        };

        setHoveredObject(null);
        setIsDragging(true);
    }


    function handlePointerMove(
        event:
            ReactPointerEvent<SVGSVGElement>,
    ) {
        const dragState =
            dragStateRef.current;

        if (
            !isDragging ||
            dragState.pointerId !==
                event.pointerId
        ) {
            return;
        }

        const svg = svgRef.current;

        if (!svg) {
            return;
        }

        const rect =
            svg.getBoundingClientRect();

        if (
            rect.width === 0 ||
            rect.height === 0
        ) {
            return;
        }

        const deltaX =
            event.clientX -
            dragState.startClientX;

        const deltaY =
            event.clientY -
            dragState.startClientY;

        const {
            width: viewWidth,
            height: viewHeight,
        } = getViewSize(zoom);

        const nextFocus =
            clampFocus(
                dragState.startFocusX -
                    deltaX *
                    (viewWidth / rect.width),
                dragState.startFocusY -
                    deltaY *
                    (viewHeight / rect.height),
                zoom,
            );

        setFocusX(nextFocus.x);
        setFocusY(nextFocus.y);
    }


    function finishDragging(
        event:
            ReactPointerEvent<SVGSVGElement>,
    ) {
        if (
            dragStateRef.current.pointerId !==
            event.pointerId
        ) {
            return;
        }

        if (
            event.currentTarget
                .hasPointerCapture(
                    event.pointerId,
                )
        ) {
            event.currentTarget
                .releasePointerCapture(
                    event.pointerId,
                );
        }

        dragStateRef.current.pointerId = -1;
        setIsDragging(false);
    }


    function handleWheel(
        event:
            ReactWheelEvent<SVGSVGElement>,
    ) {
        event.preventDefault();

        const svg = svgRef.current;

        if (!svg) {
            return;
        }

        const rect =
            svg.getBoundingClientRect();

        if (
            rect.width === 0 ||
            rect.height === 0
        ) {
            return;
        }

        const currentView =
            getViewSize(zoom);

        const currentViewX =
            clamp(
                focusX -
                    currentView.width / 2,
                0,
                SVG_WIDTH -
                    currentView.width,
            );

        const currentViewY =
            clamp(
                focusY -
                    currentView.height / 2,
                0,
                SVG_HEIGHT -
                    currentView.height,
            );

        const cursorRatioX =
            clamp(
                (
                    event.clientX -
                    rect.left
                ) / rect.width,
                0,
                1,
            );

        const cursorRatioY =
            clamp(
                (
                    event.clientY -
                    rect.top
                ) / rect.height,
                0,
                1,
            );

        const anchorX =
            currentViewX +
            cursorRatioX *
            currentView.width;

        const anchorY =
            currentViewY +
            cursorRatioY *
            currentView.height;

        const zoomFactor =
            event.deltaY < 0
                ? 1.18
                : 1 / 1.18;

        const nextZoom =
            clamp(
                zoom * zoomFactor,
                MIN_ZOOM,
                MAX_ZOOM,
            );

        if (
            Math.abs(
                nextZoom - zoom,
            ) < 0.001
        ) {
            return;
        }

        const nextView =
            getViewSize(nextZoom);

        const nextFocus =
            clampFocus(
                anchorX -
                    (cursorRatioX - 0.5) *
                    nextView.width,
                anchorY -
                    (cursorRatioY - 0.5) *
                    nextView.height,
                nextZoom,
            );

        setZoom(nextZoom);
        setFocusX(nextFocus.x);
        setFocusY(nextFocus.y);
        setHoveredObject(null);
    }


    const viewWidth =
        SVG_WIDTH / zoom;

    const viewHeight =
        SVG_HEIGHT / zoom;

    const viewX =
        clamp(
            focusX - viewWidth / 2,
            0,
            SVG_WIDTH - viewWidth,
        );

    const viewY =
        clamp(
            focusY - viewHeight / 2,
            0,
            SVG_HEIGHT - viewHeight,
        );


    const hoveredObjectPosition =
        useMemo(() => {
            if (!hoveredObject) {
                return null;
            }

            const [
                longitude,
                latitude,
            ] = hoveredObject
                .geometry
                .coordinates;

            const point =
                projectCoordinates(
                    longitude,
                    latitude,
                );

            return {
                left: clamp(
                    (
                        (point.x - viewX) /
                        viewWidth
                    ) * 100,
                    12,
                    88,
                ),
                top: clamp(
                    (
                        (point.y - viewY) /
                        viewHeight
                    ) * 100,
                    12,
                    92,
                ),
            };
        }, [
            hoveredObject,
            viewX,
            viewY,
            viewWidth,
            viewHeight,
        ]);


    return (
        <div className="schematic-map">
            <svg
                ref={svgRef}
                className={
                    isDragging
                        ? "schematic-map-svg dragging"
                        : "schematic-map-svg"
                }
                viewBox={
                    `${viewX} ${viewY} ` +
                    `${viewWidth} ${viewHeight}`
                }
                aria-label="Схематическая карта Москвы"
                onPointerDown={
                    handlePointerDown
                }
                onPointerMove={
                    handlePointerMove
                }
                onPointerUp={
                    finishDragging
                }
                onPointerCancel={
                    finishDragging
                }
                onWheel={handleWheel}
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
                            selectedObject
                                ?.object_id ===
                            object.object_id;

                        return (
                            <g
                                key={
                                    object.object_id
                                }
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
                                onPointerDown={(
                                    event,
                                ) => {
                                    event.stopPropagation();
                                }}
                                onClick={() => {
                                    onSelectObject(
                                        object,
                                    );
                                }}
                                onPointerEnter={() => {
                                    if (!isDragging) {
                                        setHoveredObject(
                                            object,
                                        );
                                    }
                                }}
                                onPointerLeave={() => {
                                    setHoveredObject(
                                        (current) =>
                                            current
                                                ?.object_id ===
                                            object.object_id
                                                ? null
                                                : current,
                                    );
                                }}
                                role="button"
                                tabIndex={0}
                                aria-label={
                                    object.name ??
                                    `Объект ${object.object_id}`
                                }
                                onKeyDown={(
                                    event,
                                ) => {
                                    if (
                                        event.key ===
                                            "Enter" ||
                                        event.key === " "
                                    ) {
                                        event.preventDefault();
                                        onSelectObject(
                                            object,
                                        );
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
                                        object.status ===
                                        "alarm"
                                            ? 10
                                            : 8
                                    }
                                    className={
                                        `schematic-object-point ${object.status}`
                                    }
                                    filter="url(#point-shadow)"
                                />
                            </g>
                        );
                    },
                )}
            </svg>

            {hoveredObject &&
                hoveredObjectPosition &&
                !isDragging && (
                    <div
                        className={
                            `map-object-tooltip ${hoveredObject.status}`
                        }
                        style={{
                            left:
                                `${hoveredObjectPosition.left}%`,
                            top:
                                `${hoveredObjectPosition.top}%`,
                        }}
                    >
                        <div className="map-object-tooltip-header">
                            <span className="map-object-tooltip-dot" />

                            <strong>
                                {hoveredObject.name ??
                                    `Объект ${hoveredObject.object_id}`}
                            </strong>
                        </div>

                        <div className="map-object-tooltip-status">
                            {hoveredObject.status ===
                                "alarm" &&
                                "Есть активная тревога"}

                            {hoveredObject.status ===
                                "normal" &&
                                "Нет тревог"}

                            {hoveredObject.status ===
                                "unknown" &&
                                "Нет данных"}
                        </div>

                        <div className="map-object-tooltip-meta">
                            <span>
                                Каналов
                                <strong>
                                    {
                                        hoveredObject.sensor_count
                                    }
                                </strong>
                            </span>

                            <span>
                                С данными
                                <strong>
                                    {
                                        hoveredObject
                                            .sensors_with_data
                                    }
                                </strong>
                            </span>

                            {hoveredObject
                                .alarm_sensor_count >
                                0 && (
                                <span>
                                    Тревожных
                                    <strong>
                                        {
                                            hoveredObject
                                                .alarm_sensor_count
                                        }
                                    </strong>
                                </span>
                            )}
                        </div>

                        <small>
                            {hoveredObject.data_is_synthetic
                                ? "Демо-данные · точка условная"
                                : hoveredObject.geometry_is_synthetic
                                ? "Точка условная, не адрес · открыть объект"
                                : "Нажмите, чтобы открыть объект"}
                        </small>
                    </div>
                )}

            <div className="schematic-map-controls">
                <button
                    type="button"
                    onClick={zoomIn}
                    disabled={
                        zoom >= MAX_ZOOM
                    }
                    aria-label="Приблизить карту"
                >
                    <Plus size={17} />
                </button>

                <button
                    type="button"
                    onClick={zoomOut}
                    disabled={
                        zoom <= MIN_ZOOM
                    }
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
