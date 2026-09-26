import { createElement } from "react";

import {
    Activity,
    BatteryCharging,
    Cctv,
    DoorClosed,
    Droplets,
    Fan,
    Flame,
    Gauge,
    Lock,
    PersonStanding,
    Phone,
    PlugZap,
    Radio,
    Thermometer,
    Wind,
    Zap,
} from "lucide-react";

import type {
    LucideIcon,
} from "lucide-react";


// Порядок важен: сначала узкие типы («батарея», «трансформатор»),
// потом общие («питание»). Ищем по типу, системе и названию датчика —
// точный словарь типов организаторы не давали, поэтому по ключевым словам.
const RULES: [RegExp, LucideIcon][] = [
    [/батаре|акб|аккумул/, BatteryCharging],
    [/трансформатор|подстанц|щит|ввод/, PlugZap],
    [/газ|ch4|метан/, Wind],
    [/дым|пожар|огн|пламен/, Flame],
    [/температур|тепл|нагрев/, Thermometer],
    [/влажн|подтоп|затоп|протеч|вода|водо|уровень/, Droplets],
    [/движен|присутств/, PersonStanding],
    [/камер|видео/, Cctv],
    [/двер|контакт|рычаг|замкн/, DoorClosed],
    [/вентил/, Fan],
    [/насос|давлен/, Gauge],
    [/домофон|вызов|переговор|телефон/, Phone],
    [/охран|доступ|замок|несанкц/, Lock],
    [/питан|обесточ|электр|напряж/, Zap],
    [/связь|канал|неисправ/, Radio],
];


function iconForSensor(
    ...parts: (string | null | undefined)[]
): LucideIcon {
    const text = parts
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

    for (const [pattern, icon] of RULES) {
        if (pattern.test(text)) {
            return icon;
        }
    }

    return Activity;
}


interface SensorIconProps {
    sensorType?: string | null;
    systemType?: string | null;
    name?: string | null;
    size?: number;
    className?: string;
}


function SensorIcon({
    sensorType,
    systemType,
    name,
    size = 18,
    className = "sensor-type-icon",
}: SensorIconProps) {
    // Иконка берётся из статической таблицы выше, компонент не создаётся заново.
    return createElement(
        iconForSensor(sensorType, systemType, name),
        {
            size,
            className,
            "aria-hidden": true,
        },
    );
}


export default SensorIcon;
