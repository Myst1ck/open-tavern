// Pure-SVG d20: a flat-shaded orthographic projection of an icosahedron
// (12 vertices, 20 triangles). All geometry is derived at module load, so the
// component itself is just markup plus a couple of CSS hooks.

type Vec3 = readonly [number, number, number];

const PHI = (1 + Math.sqrt(5)) / 2;

// Golden-ratio icosahedron, edge length 2.
const VERTICES: readonly Vec3[] = [
  [0, 1, PHI],
  [0, 1, -PHI],
  [0, -1, PHI],
  [0, -1, -PHI],
  [1, PHI, 0],
  [1, -PHI, 0],
  [-1, PHI, 0],
  [-1, -PHI, 0],
  [PHI, 0, 1],
  [-PHI, 0, 1],
  [PHI, 0, -1],
  [-PHI, 0, -1],
];

const FACES: readonly (readonly [number, number, number])[] = [
  [0, 11, 5],
  [0, 5, 1],
  [0, 1, 7],
  [0, 7, 10],
  [0, 10, 11],
  [1, 5, 9],
  [5, 11, 4],
  [11, 10, 2],
  [10, 7, 6],
  [7, 1, 8],
  [3, 9, 4],
  [3, 4, 2],
  [3, 2, 6],
  [3, 6, 8],
  [3, 8, 9],
  [4, 9, 5],
  [2, 4, 11],
  [6, 2, 10],
  [8, 6, 7],
  [9, 8, 1],
];

const VIEWBOX = 100;
const PADDING = 3;
// Fixed resting tilt: a three-quarter view that shows 10 of the 20 faces.
const TILT_Y = 0.55;
const TILT_X = 0.35;

const rotate = ([x, y, z]: Vec3): Vec3 => {
  const cy = Math.cos(TILT_Y);
  const sy = Math.sin(TILT_Y);
  const x1 = x * cy + z * sy;
  const z1 = z * cy - x * sy;
  const cx = Math.cos(TILT_X);
  const sx = Math.sin(TILT_X);
  const y1 = y * cx - z1 * sx;
  const z2 = z1 * cx + y * sx;
  return [x1, y1, z2];
};

const rotated = VERTICES.map(rotate);
const xs = rotated.map(([x]) => x);
const ys = rotated.map(([, y]) => y);
const minX = Math.min(...xs);
const maxX = Math.max(...xs);
const minY = Math.min(...ys);
const maxY = Math.max(...ys);
const scale = (VIEWBOX - PADDING * 2) / Math.max(maxX - minX, maxY - minY);
const centerX = (minX + maxX) / 2;
const centerY = (minY + maxY) / 2;

const toScreen = ([x, y]: Vec3): string =>
  `${(VIEWBOX / 2 + (x - centerX) * scale).toFixed(2)},${(
    VIEWBOX / 2 -
    (y - centerY) * scale
  ).toFixed(2)}`;

interface DieFace {
  points: string;
  front: boolean;
  depth: number;
}

// Paint far faces first so nearer ones overlap them.
const DIE_FACES: readonly DieFace[] = FACES.map(([a, b, c]) => {
  const pa = rotated[a];
  const pb = rotated[b];
  const pc = rotated[c];
  const nx =
    (pb[1] - pa[1]) * (pc[2] - pa[2]) - (pb[2] - pa[2]) * (pc[1] - pa[1]);
  const ny =
    (pb[2] - pa[2]) * (pc[0] - pa[0]) - (pb[0] - pa[0]) * (pc[2] - pa[2]);
  const nz =
    (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]);
  const cx = (pa[0] + pb[0] + pc[0]) / 3;
  const cy = (pa[1] + pb[1] + pc[1]) / 3;
  const cz = (pa[2] + pb[2] + pc[2]) / 3;
  const sign = nx * cx + ny * cy + nz * cz >= 0 ? 1 : -1;
  return {
    points: [pa, pb, pc].map(toScreen).join(" "),
    front: sign * nz > 0,
    depth: sign * cz,
  };
}).sort((left, right) => left.depth - right.depth);

interface DieProps {
  value?: number;
  rolling: boolean;
}

export default function Die({ value, rolling }: DieProps) {
  const label =
    rolling || value === undefined
      ? "Rolling a twenty-sided die"
      : `Twenty-sided die showing ${value}`;

  return (
    <svg
      className={`die-svg${rolling ? " die-svg--rolling" : ""}`}
      viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
      role="img"
      aria-label={label}
    >
      <g className="die-svg-faces">
        {DIE_FACES.map((face) => (
          <polygon
            key={face.points}
            points={face.points}
            className={`die-face ${face.front ? "die-face--front" : "die-face--back"}`}
          />
        ))}
      </g>
      {!rolling && value !== undefined && (
        <text
          className="die-value"
          x={VIEWBOX / 2}
          y={VIEWBOX / 2}
          textAnchor="middle"
          dominantBaseline="central"
        >
          {value}
        </text>
      )}
    </svg>
  );
}
