// Original vector illustration for the prototype. It provides recognisable
// Moscow orientation, not survey geometry or a source for object locations.
const RIVER = "M -40 506 C 91 466 178 445 258 459 C 332 474 357 541 425 551 C 481 559 502 500 548 458 C 593 414 639 408 684 432 C 735 460 728 528 783 563 C 846 604 919 568 973 518 C 1030 463 1111 448 1240 432";

const AVENUES = [
    "M 60 197 C 247 273 405 329 598 402 C 796 470 974 531 1155 622",
    "M 161 31 C 321 191 466 320 602 405 C 766 510 910 638 1050 818",
    "M 481 -28 C 531 137 568 263 606 405 C 639 556 681 696 730 858",
    "M 822 -19 C 754 160 695 286 609 410 C 500 553 400 685 312 847",
    "M 1203 188 C 956 282 776 343 608 405 C 416 477 233 549 -40 622",
    "M -25 371 C 226 376 415 390 603 405 C 810 425 1002 410 1240 353",
    "M 38 715 C 231 582 424 483 606 403 C 812 308 1005 227 1196 77",
];

const STREETS = [
    "M 35 283 C 270 331 468 359 680 356 C 890 351 1050 310 1215 265",
    "M 14 455 C 235 421 399 430 575 464 C 777 507 962 484 1212 454",
    "M 64 685 C 243 610 388 542 511 470 C 644 394 777 282 942 115",
    "M 254 -20 C 353 153 448 305 553 396 C 677 505 835 635 1001 844",
    "M 1008 11 C 908 178 817 306 705 407 C 594 501 492 642 435 829",
    "M 628 -30 C 667 166 651 299 603 408 C 556 543 537 686 562 839",
    "M 104 108 C 332 226 497 300 675 300 C 851 299 1013 258 1192 197",
    "M -18 567 C 195 518 342 507 467 533 C 650 570 877 626 1198 666",
];

const AREAS = [
    { name: "ХАМОВНИКИ", x: 363, y: 572 },
    { name: "АРБАТ", x: 458, y: 390 },
    { name: "ПРЕСНЕНСКИЙ", x: 365, y: 295 },
    { name: "ТВЕРСКОЙ", x: 550, y: 276 },
    { name: "БАСМАННЫЙ", x: 811, y: 330 },
    { name: "ТАГАНСКИЙ", x: 817, y: 535 },
    { name: "ЗАМОСКВОРЕЧЬЕ", x: 612, y: 596 },
    { name: "ЯКИМАНКА", x: 501, y: 681 },
    { name: "СОКОЛЬНИКИ", x: 905, y: 184 },
];

const PARKS = [
    { d: "M 92 146 Q 163 93 259 116 L 300 194 Q 255 236 156 238 Z", name: "Парк Фили", x: 170, y: 177 },
    { d: "M 860 82 Q 936 48 1020 103 L 1057 176 Q 1013 220 909 206 Z", name: "Сокольники", x: 947, y: 145 },
    { d: "M 330 660 Q 392 624 455 651 L 481 749 Q 426 797 354 755 Z", name: "Лужники", x: 399, y: 710 },
    { d: "M 632 649 Q 706 617 741 666 L 752 749 Q 702 783 649 745 Z", name: "Парк Горького", x: 693, y: 706 },
    { d: "M 1029 535 Q 1112 502 1200 539 L 1216 680 Q 1131 721 1041 670 Z", name: "Измайлово", x: 1115, y: 606 },
];

const LANDMARKS = [
    { name: "Кремль", x: 594, y: 409 },
    { name: "Москва-Сити", x: 327, y: 409 },
    { name: "ВДНХ", x: 751, y: 109 },
];

function MoscowBaseMap() {
    return (
        <g className="moscow-base-map" aria-hidden="true">
            <defs>
                <pattern id="city-minor-grid" width="35" height="35" patternUnits="userSpaceOnUse" patternTransform="rotate(-12)">
                    <path d="M 35 0 H 0 V 35" className="city-grid-line" />
                </pattern>
            </defs>
            <rect width="1200" height="820" className="city-ground" />
            <rect width="1200" height="820" fill="url(#city-minor-grid)" />

            <path className="city-neighborhood" d="M 185 231 C 391 111 737 124 976 250 C 1080 307 1119 461 1025 621 C 869 733 485 755 262 615 C 137 522 103 336 185 231 Z" />
            <path className="city-neighborhood city-core" d="M 398 291 C 533 222 737 249 815 353 C 907 474 799 615 641 627 C 477 646 350 564 338 424 C 333 369 358 316 398 291 Z" />

            <g className="city-parks">
                {PARKS.map((park) => (
                    <g key={park.name}>
                        <path d={park.d} />
                        <text x={park.x} y={park.y} textAnchor="middle">{park.name}</text>
                    </g>
                ))}
            </g>

            <g className="city-street-casing">
                {STREETS.map((path, index) => <path key={index} d={path} />)}
            </g>
            <g className="city-streets">
                {STREETS.map((path, index) => <path key={index} d={path} />)}
            </g>
            <g className="city-avenue-casing">
                {AVENUES.map((path, index) => <path key={index} d={path} />)}
            </g>
            <g className="city-avenues">
                {AVENUES.map((path, index) => <path key={index} d={path} />)}
            </g>

            <ellipse className="city-ring-casing" cx="607" cy="411" rx="349" ry="249" />
            <ellipse className="city-ring" cx="607" cy="411" rx="349" ry="249" />
            <ellipse className="city-ring-casing" cx="607" cy="411" rx="169" ry="125" />
            <ellipse className="city-ring inner" cx="607" cy="411" rx="169" ry="125" />

            <path className="city-river-bank" d={RIVER} />
            <path className="city-river" d={RIVER} />
            <text className="city-river-label" x="833" y="589" transform="rotate(-10 833 589)">МОСКВА-РЕКА</text>

            <g className="city-area-labels">
                {AREAS.map((area) => <text key={area.name} x={area.x} y={area.y} textAnchor="middle">{area.name}</text>)}
            </g>
            <g className="city-landmarks">
                {LANDMARKS.map((place) => (
                    <g key={place.name} transform={`translate(${place.x} ${place.y})`}>
                        <circle r="4" />
                        <text x="10" y="-10">{place.name}</text>
                    </g>
                ))}
            </g>
        </g>
    );
}

export default MoscowBaseMap;
