interface UrbanPatch {
    id: string;

    x: number;
    y: number;

    width: number;
    height: number;

    rotation: number;

    rows: number;
    columns: number;

    shape: string;
}


const MOSCOW_RIVER = `
  M 55 520

  C 125 480,
    195 452,
    255 458

  C 314 463,
    350 489,
    380 526

  C 410 563,
    449 586,
    486 567

  C 524 548,
    526 495,
    556 455

  C 585 417,
    623 399,
    661 409

  C 704 420,
    731 456,
    744 499

  C 758 546,
    783 580,
    822 588

  C 865 597,
    902 574,
    936 545

  C 987 503,
    1040 475,
    1148 444
`;


const PRIMARY_ROADS = [
    `
    M 96 314
    C 245 322, 358 337, 469 363
    C 589 391, 710 403, 864 380
    C 956 366, 1034 340, 1120 302
  `,

    `
    M 84 420
    C 224 408, 351 412, 470 431
    C 599 450, 736 461, 873 449
    C 967 441, 1050 421, 1142 394
  `,

    `
    M 162 672
    C 247 606, 326 550, 402 503
    C 493 446, 587 397, 690 332
    C 785 272, 860 210, 943 132
  `,

    `
    M 357 770
    C 393 657, 430 572, 478 500
    C 526 427, 579 354, 612 249
    C 627 203, 641 161, 653 104
  `,

    `
    M 646 782
    C 633 674, 624 588, 621 514
    C 617 427, 621 340, 650 250
    C 673 180, 702 131, 735 78
  `,

    `
    M 1057 621
    C 947 575, 858 531, 775 488
    C 689 442, 611 397, 534 342
    C 455 285, 386 227, 301 145
  `,

    `
    M 1095 533
    C 967 503, 858 480, 758 458
    C 652 434, 551 410, 436 388
    C 327 367, 225 353, 104 347
  `,

    `
    M 1033 181
    C 933 239, 845 293, 768 341
    C 678 397, 587 453, 502 511
    C 416 569, 337 632, 256 713
  `,
];


const SECONDARY_ROADS = [
    "M 128 252 C 275 265, 392 293, 489 329 C 620 378, 766 373, 1004 278",
    "M 121 369 C 261 362, 383 372, 493 401 C 629 437, 777 432, 1058 354",
    "M 139 472 C 268 459, 379 466, 488 490 C 625 521, 786 518, 1087 458",

    "M 221 164 C 302 252, 373 319, 457 370 C 546 424, 631 487, 709 573",
    "M 347 104 C 402 210, 456 294, 522 365 C 585 433, 643 510, 695 647",
    "M 491 82 C 517 201, 545 300, 574 377 C 603 457, 629 553, 643 716",

    "M 811 94 C 759 195, 715 278, 670 346 C 623 416, 571 479, 510 551",
    "M 950 151 C 861 239, 787 306, 719 362 C 644 424, 574 492, 493 597",

    "M 1052 271 C 938 312, 841 349, 757 385 C 658 427, 562 466, 446 517",
    "M 1087 598 C 953 553, 850 516, 758 481 C 650 440, 551 406, 417 379",
];


const RING_FRAGMENTS = [
    `
    M 389 308
    C 452 260, 540 239, 623 251
    C 696 262, 754 295, 795 345
  `,

    `
    M 814 374
    C 843 432, 839 494, 808 545
    C 771 606, 705 642, 629 651
  `,

    `
    M 590 653
    C 517 649, 452 621, 408 575
    C 367 532, 349 475, 360 421
  `,

    `
    M 458 374
    C 500 337, 555 321, 609 329
    C 658 336, 698 358, 724 390
  `,

    `
    M 735 420
    C 748 462, 738 505, 706 535
    C 672 565, 624 578, 580 570
  `,
];


const BRIDGES = [
    {
        x1: 254,
        y1: 448,
        x2: 264,
        y2: 471,
    },
    {
        x1: 378,
        y1: 516,
        x2: 398,
        y2: 537,
    },
    {
        x1: 520,
        y1: 497,
        x2: 540,
        y2: 511,
    },
    {
        x1: 699,
        y1: 427,
        x2: 720,
        y2: 441,
    },
    {
        x1: 752,
        y1: 517,
        x2: 773,
        y2: 531,
    },
    {
        x1: 909,
        y1: 549,
        x2: 925,
        y2: 568,
    },
];


const URBAN_PATCHES: UrbanPatch[] = [
    {
        id: "north-west",
        x: 135,
        y: 135,
        width: 285,
        height: 210,
        rotation: -11,
        rows: 8,
        columns: 10,
        shape: `
      M 145 175
      C 195 120, 305 117, 376 154
      C 426 182, 439 244, 407 300
      C 365 341, 281 350, 206 318
      C 146 290, 118 226, 145 175
      Z
    `,
    },

    {
        id: "north",
        x: 405,
        y: 105,
        width: 300,
        height: 230,
        rotation: 3,
        rows: 9,
        columns: 11,
        shape: `
      M 425 134
      C 491 93, 598 85, 671 118
      C 729 145, 750 208, 721 270
      C 685 322, 603 343, 515 320
      C 446 302, 389 245, 397 186
      C 400 165, 409 146, 425 134
      Z
    `,
    },

    {
        id: "north-east",
        x: 700,
        y: 140,
        width: 330,
        height: 225,
        rotation: 12,
        rows: 8,
        columns: 11,
        shape: `
      M 741 158
      C 817 111, 918 127, 984 177
      C 1036 217, 1034 287, 993 331
      C 939 379, 846 379, 773 345
      C 705 312, 681 237, 714 188
      C 722 176, 730 166, 741 158
      Z
    `,
    },

    {
        id: "west",
        x: 105,
        y: 340,
        width: 330,
        height: 230,
        rotation: 4,
        rows: 8,
        columns: 11,
        shape: `
      M 137 365
      C 197 326, 298 325, 378 355
      C 429 381, 447 437, 424 493
      C 393 553, 318 580, 233 559
      C 158 540, 112 490, 112 426
      C 112 399, 121 379, 137 365
      Z
    `,
    },

    {
        id: "center",
        x: 370,
        y: 310,
        width: 430,
        height: 280,
        rotation: -4,
        rows: 11,
        columns: 15,
        shape: `
      M 413 337
      C 479 299, 585 286, 681 310
      C 769 333, 816 389, 810 459
      C 801 528, 738 572, 659 585
      C 567 603, 475 578, 420 527
      C 367 478, 350 402, 382 356
      C 391 347, 401 340, 413 337
      Z
    `,
    },

    {
        id: "east",
        x: 780,
        y: 350,
        width: 305,
        height: 235,
        rotation: -9,
        rows: 8,
        columns: 11,
        shape: `
      M 808 371
      C 872 334, 967 342, 1029 387
      C 1073 426, 1074 488, 1039 533
      C 995 584, 913 602, 844 573
      C 786 548, 757 494, 769 438
      C 774 410, 786 387, 808 371
      Z
    `,
    },

    {
        id: "south-west",
        x: 190,
        y: 560,
        width: 320,
        height: 190,
        rotation: 12,
        rows: 7,
        columns: 10,
        shape: `
      M 224 580
      C 290 538, 390 542, 455 580
      C 504 610, 511 666, 476 704
      C 428 748, 343 755, 273 720
      C 216 692, 187 632, 224 580
      Z
    `,
    },

    {
        id: "south",
        x: 455,
        y: 575,
        width: 310,
        height: 190,
        rotation: -3,
        rows: 7,
        columns: 10,
        shape: `
      M 483 590
      C 548 559, 651 558, 716 592
      C 763 617, 776 668, 747 708
      C 708 751, 633 769, 558 748
      C 494 729, 449 685, 456 635
      C 459 615, 467 600, 483 590
      Z
    `,
    },

    {
        id: "south-east",
        x: 730,
        y: 560,
        width: 330,
        height: 190,
        rotation: -13,
        rows: 7,
        columns: 11,
        shape: `
      M 769 578
      C 837 542, 933 550, 1000 588
      C 1052 619, 1061 674, 1026 711
      C 981 753, 895 758, 820 726
      C 758 698, 724 634, 769 578
      Z
    `,
    },
];


function UrbanTexture() {
    return (
        <>
            <defs>
                {URBAN_PATCHES.map(
                    (patch) => (
                        <clipPath
                            key={patch.id}
                            id={`urban-${patch.id}`}
                        >
                            <path
                                d={patch.shape}
                            />
                        </clipPath>
                    ),
                )}
            </defs>

            <g className="moscow-urban-texture">
                {URBAN_PATCHES.map(
                    (
                        patch,
                        patchIndex,
                    ) => {
                        const centerX =
                            patch.x +
                            patch.width / 2;

                        const centerY =
                            patch.y +
                            patch.height / 2;

                        return (
                            <g
                                key={patch.id}
                                clipPath={
                                    `url(#urban-${patch.id})`
                                }
                            >
                                <g
                                    transform={
                                        `rotate(${patch.rotation} ${centerX} ${centerY})`
                                    }
                                >
                                    {Array.from(
                                        {
                                            length:
                                                patch.rows + 1,
                                        },
                                        (_, index) => {
                                            const y =
                                                patch.y +
                                                (
                                                    patch.height *
                                                    index
                                                ) /
                                                patch.rows;

                                            const bend =
                                                Math.sin(
                                                    index * 1.71 +
                                                    patchIndex,
                                                ) * 8;

                                            return (
                                                <path
                                                    key={
                                                        `h-${index}`
                                                    }
                                                    d={`
                            M
                            ${patch.x - 25}
                            ${y}

                            Q
                            ${centerX}
                            ${y + bend}

                            ${patch.x +
                                                        patch.width +
                                                        25
                                                        }
                            ${y +
                                                        bend * 0.35
                                                        }
                          `}
                                                />
                                            );
                                        },
                                    )}


                                    {Array.from(
                                        {
                                            length:
                                                patch.columns +
                                                1,
                                        },
                                        (_, index) => {
                                            const x =
                                                patch.x +
                                                (
                                                    patch.width *
                                                    index
                                                ) /
                                                patch.columns;

                                            const bend =
                                                Math.cos(
                                                    index * 1.43 +
                                                    patchIndex,
                                                ) * 8;

                                            return (
                                                <path
                                                    key={
                                                        `v-${index}`
                                                    }
                                                    d={`
                            M
                            ${x}
                            ${patch.y - 25}

                            Q
                            ${x + bend}
                            ${centerY}

                            ${x +
                                                        bend * 0.4
                                                        }
                            ${patch.y +
                                                        patch.height +
                                                        25
                                                        }
                          `}
                                                />
                                            );
                                        },
                                    )}
                                </g>
                            </g>
                        );
                    },
                )}
            </g>
        </>
    );
}


function MoscowBaseMap() {
    return (
        <g
            className="moscow-base-map"
            aria-hidden="true"
        >
            <defs>
                <radialGradient
                    id="moscow-v4-glow"
                    cx="50%"
                    cy="45%"
                    r="70%"
                >
                    <stop
                        offset="0%"
                        stopColor="#32424f"
                        stopOpacity="0.24"
                    />

                    <stop
                        offset="60%"
                        stopColor="#25333e"
                        stopOpacity="0.08"
                    />

                    <stop
                        offset="100%"
                        stopColor="#172129"
                        stopOpacity="0"
                    />
                </radialGradient>
            </defs>


            <rect
                x="0"
                y="0"
                width="1200"
                height="820"
                className="moscow-v4-background"
            />

            <ellipse
                cx="600"
                cy="390"
                rx="540"
                ry="355"
                fill="url(#moscow-v4-glow)"
                pointerEvents="none"
            />


            <UrbanTexture />


            <g className="moscow-secondary-v4">
                {SECONDARY_ROADS.map(
                    (path, index) => (
                        <path
                            key={index}
                            d={path}
                        />
                    ),
                )}
            </g>


            <g className="moscow-primary-v4">
                {PRIMARY_ROADS.map(
                    (path, index) => (
                        <path
                            key={index}
                            d={path}
                        />
                    ),
                )}
            </g>


            <g className="moscow-ring-fragments-v4">
                {RING_FRAGMENTS.map(
                    (path, index) => (
                        <path
                            key={index}
                            d={path}
                        />
                    ),
                )}
            </g>


            <path
                d={MOSCOW_RIVER}
                className="moscow-river-bank-v4"
            />

            <path
                d={MOSCOW_RIVER}
                className="moscow-river-v4"
            />


            <g className="moscow-bridges-v4">
                {BRIDGES.map(
                    (bridge, index) => (
                        <line
                            key={index}
                            {...bridge}
                        />
                    ),
                )}
            </g>
        </g>
    );
}


export default MoscowBaseMap;
